import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.adapters.razorpay.payment_links import (
    CreatePaymentLinkRequest,
    FakePaymentLinkProvider,
)
from retrypay.budget.engine import BudgetEngine
from retrypay.decision.diagnosis import ActionType
from retrypay.domain.models import (
    EventSource,
    Order,
    OrderStatus,
    ProviderOperationStatus,
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryCase,
    RecoveryCaseState,
    generate_deterministic_reference_id,
)
from retrypay.execution.orchestrator import ExecutionOrchestrator
from retrypay.policy.engine import PolicyEngine
from retrypay.storage.repositories.actions import RecoveryActionRepository
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.links import PaymentLinkRepository
from retrypay.storage.repositories.orders import OrderRepository
from tests.conftest import compute_signature


@pytest.mark.asyncio
async def test_reconciliation_repairs_local_state_when_link_found(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reconciliation searches by deterministic reference_id and repairs local state."""
    now = datetime.now(UTC)
    case_id = "rcv_recon_repair_123"
    action_id = "act_recon_repair_456"
    source = EventSource.RAZORPAY_TEST_MODE.value

    reference_id = generate_deterministic_reference_id(case_id, action_id)

    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        action_repo = RecoveryActionRepository(session)
        budget_engine = BudgetEngine(session)

        # 1. Setup pending case & action
        case = RecoveryCase(
            case_id=case_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id="order_recon_1",
            failed_attempt_id="pay_fail_recon_1",
            state=RecoveryCaseState.ACTION_APPROVED,
            policy_version="recovery-v1.3",
            created_at=now,
            updated_at=now,
        )
        await case_repo.save_case(case, source=source)

        action = RecoveryAction(
            action_id=action_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            case_id=case_id,
            action_type=ActionType.SEND_RETRY_LINK,
            policy_version="recovery-v1.3",
            idempotency_key=f"idem_{case_id}",
            status=RecoveryActionStatus.FAILED,
            provider_operation_status=ProviderOperationStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )
        await action_repo.save_action(action, source=source)

        reservation = await budget_engine.reserve_budget(
            case_id=case_id, action_id=action_id, amount_paise=150000
        )
        res_id = reservation.reservation_id
        await session.commit()

    # 2. Setup provider with pre-existing link under the deterministic reference_id
    provider = FakePaymentLinkProvider(mode="success")
    dummy_req = CreatePaymentLinkRequest(
        order_id="order_recon_1",
        amount_paise=150000,
        currency="INR",
        case_id=case_id,
        action_id=action_id,
        reference_id=reference_id,
        expire_by=now + timedelta(hours=1),
    )
    await provider.create_payment_link(dummy_req)

    # 3. Run reconciliation via orchestrator
    async with test_session_factory() as session:
        orchestrator = ExecutionOrchestrator(
            session=session,
            link_provider=provider,
            policy_engine=PolicyEngine(),
        )
        result = await orchestrator.reconcile_provider_operation(
            case_id=case_id, action_id=action_id, reservation_id=res_id
        )
        await session.commit()

        assert result["reconciled"] is True
        assert result["link_found"] is True
        assert result["action_status"] == RecoveryActionStatus.COMPLETED.value
        assert result["provider_operation_status"] == ProviderOperationStatus.SUCCEEDED.value

    # 4. Verify local DB state repaired
    async with test_session_factory() as session:
        link_repo = PaymentLinkRepository(session)
        case_repo = RecoveryCaseRepository(session)
        action_repo = RecoveryActionRepository(session)

        reconciled_link = await link_repo.get_by_reference_id(reference_id, source=source)
        assert reconciled_link is not None
        assert reconciled_link.reference_id == reference_id

        reconciled_case = await case_repo.get_case(case_id, source=source)
        assert reconciled_case is not None
        assert reconciled_case.state == RecoveryCaseState.LINK_CREATED

        reconciled_action = await action_repo.get_action(action_id)
        assert reconciled_action is not None
        assert reconciled_action.status == RecoveryActionStatus.COMPLETED
        assert reconciled_action.provider_operation_status == ProviderOperationStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_reconciliation_handles_missing_provider_link(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Missing provider link during reconciliation marks action FAILED."""
    now = datetime.now(UTC)
    case_id = "rcv_recon_missing_123"
    action_id = "act_recon_missing_456"
    source = EventSource.RAZORPAY_TEST_MODE.value

    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        action_repo = RecoveryActionRepository(session)
        budget_engine = BudgetEngine(session)

        case = RecoveryCase(
            case_id=case_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id="order_recon_missing_1",
            failed_attempt_id="pay_fail_recon_missing_1",
            state=RecoveryCaseState.ACTION_APPROVED,
            policy_version="recovery-v1.3",
            created_at=now,
            updated_at=now,
        )
        await case_repo.save_case(case, source=source)

        action = RecoveryAction(
            action_id=action_id,
            source=EventSource.RAZORPAY_TEST_MODE,
            case_id=case_id,
            action_type=ActionType.SEND_RETRY_LINK,
            policy_version="recovery-v1.3",
            idempotency_key=f"idem_{case_id}",
            status=RecoveryActionStatus.FAILED,
            provider_operation_status=ProviderOperationStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )
        await action_repo.save_action(action, source=source)

        reservation = await budget_engine.reserve_budget(
            case_id=case_id, action_id=action_id, amount_paise=100000
        )
        res_id = reservation.reservation_id
        await session.commit()

    provider = FakePaymentLinkProvider(mode="success")

    async with test_session_factory() as session:
        orchestrator = ExecutionOrchestrator(
            session=session,
            link_provider=provider,
            policy_engine=PolicyEngine(),
        )
        result = await orchestrator.reconcile_provider_operation(
            case_id=case_id, action_id=action_id, reservation_id=res_id
        )
        await session.commit()

        assert result["reconciled"] is True
        assert result["link_found"] is False
        assert result["action_status"] == RecoveryActionStatus.FAILED.value
        assert result["provider_operation_status"] == ProviderOperationStatus.FAILED.value

    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        action_repo = RecoveryActionRepository(session)

        reconciled_case = await case_repo.get_case(case_id, source=source)
        assert reconciled_case is not None
        assert reconciled_case.state == RecoveryCaseState.MANUAL_REVIEW

        reconciled_action = await action_repo.get_action(action_id)
        assert reconciled_action is not None
        assert reconciled_action.status == RecoveryActionStatus.FAILED
        assert reconciled_action.provider_operation_status == ProviderOperationStatus.FAILED


@pytest.mark.asyncio
async def test_payment_authorized_event_does_not_mark_order_paid(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """payment.authorized webhook does NOT mark order paid (remains attempted)."""
    now = datetime.now(UTC)
    source = EventSource.RAZORPAY_TEST_MODE.value

    # 0. Pre-create order in ATTEMPTED state
    async with test_session_factory() as session:
        order_repo = OrderRepository(session)
        order = Order(
            order_id="order_auth_test_101",
            source=EventSource.RAZORPAY_TEST_MODE,
            amount_paise=500000,
            currency="INR",
            status=OrderStatus.ATTEMPTED,
            created_at=now,
            updated_at=now,
        )
        await order_repo.save_order(order, source=source)
        await session.commit()

    # 1. Send payment.authorized
    payload_auth = {
        "entity": "event",
        "event": "payment.authorized",
        "event_id": "evt_auth_101",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_auth_101",
                    "order_id": "order_auth_test_101",
                    "amount": 500000,
                    "currency": "INR",
                    "status": "authorized",
                    "method": "card",
                }
            }
        },
    }
    raw_auth = json.dumps(payload_auth).encode("utf-8")
    sig_auth = compute_signature(raw_auth)

    r1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_auth,
        headers={"X-Razorpay-Signature": sig_auth},
    )
    assert r1.status_code == 200

    # Order status MUST remain ATTEMPTED after authorized
    async with test_session_factory() as session:
        order_repo = OrderRepository(session)
        order_after_auth = await order_repo.get_order("order_auth_test_101", source=source)
        assert order_after_auth is not None
        assert order_after_auth.status == OrderStatus.ATTEMPTED

    # 2. Send payment.captured for the same order
    payload_cap = {
        "entity": "event",
        "event": "payment.captured",
        "event_id": "evt_cap_101",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_auth_101",
                    "order_id": "order_auth_test_101",
                    "amount": 500000,
                    "currency": "INR",
                    "status": "captured",
                    "method": "card",
                }
            }
        },
    }
    raw_cap = json.dumps(payload_cap).encode("utf-8")
    sig_cap = compute_signature(raw_cap)

    r2 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_cap,
        headers={"X-Razorpay-Signature": sig_cap},
    )
    assert r2.status_code == 200

    # Order status MUST now be PAID
    async with test_session_factory() as session:
        order_paid = await order_repo.get_order("order_auth_test_101", source=source)
        assert order_paid is not None
        assert order_paid.status == OrderStatus.PAID

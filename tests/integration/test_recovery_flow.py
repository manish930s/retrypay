"""Integration tests for recovery case lifecycle, policy evaluation, and event audit trail."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.errors import DuplicateActiveCaseError
from retrypay.domain.models import (
    AuditEventType,
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentStatus,
    PolicyDecisionType,
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)
from retrypay.storage.models import (
    AuditEventModel,
    PolicyEvaluationModel,
    RecoveryCaseModel,
)
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.storage.repositories.orders import OrderRepository
from tests.conftest import compute_signature, load_fixture


@pytest.mark.asyncio
async def test_recovery_flow_eligible_case_creation(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure failed payment for a consented customer creates a POLICY_EVALUATED recovery case."""
    # 1. Pre-seed synthetic customer with OPTED_IN consent
    async with test_session_factory() as session:
        cust_repo = CustomerRepository(session)
        customer = Customer(
            customer_id="cust_order_test_001",
            masked_phone="+91******1234",
            masked_email="c***@example.com",
        )
        await cust_repo.save_customer(customer)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=customer.customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )
        await session.commit()

    # 2. Ingest payment.failed webhook
    payload_bytes = load_fixture("valid_payment_failed.json")
    sig = compute_signature(payload_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_rec_test_001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"

    # 3. Verify database persistence
    async with test_session_factory() as session:
        # Check recovery case
        case_res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = case_res.scalar_one_or_none()
        assert case is not None
        assert case.state in (
            RecoveryCaseState.POLICY_EVALUATED.value,
            RecoveryCaseState.LINK_CREATED.value,
            RecoveryCaseState.NOTIFIED.value,
        )
        assert case.closed_at is None

        # Check policy evaluation record
        eval_res = await session.execute(
            select(PolicyEvaluationModel).where(PolicyEvaluationModel.case_id == case.case_id)
        )
        evaluation = eval_res.scalar_one_or_none()
        assert evaluation is not None
        assert evaluation.decision_type == PolicyDecisionType.ELIGIBLE.value
        assert len(evaluation.context_hash) == 64

        # Check audit events trail
        audit_res = await session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.case_id == case.case_id)
            .order_by(AuditEventModel.timestamp.asc())
        )
        audit_events = audit_res.scalars().all()
        assert len(audit_events) >= 3
        event_types = [e.event_type for e in audit_events]
        assert "CASE_CREATED" in event_types
        assert "STATE_TRANSITION" in event_types
        assert "POLICY_EVALUATED" in event_types


@pytest.mark.asyncio
async def test_payment_captured_closes_active_recovery_case(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure payment.captured automatically closes an existing active recovery case."""
    # 1. Pre-seed consented customer so recovery case stays active (POLICY_EVALUATED)
    async with test_session_factory() as session:
        cust_repo = CustomerRepository(session)
        customer = Customer(
            customer_id="cust_order_test_001",
            masked_phone="+91******1234",
            masked_email="c***@example.com",
        )
        await cust_repo.save_customer(customer)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=customer.customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )
        await session.commit()

    # Ingest failed payment -> creates active case
    fail_bytes = load_fixture("valid_payment_failed.json")
    fail_sig = compute_signature(fail_bytes)
    await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=fail_bytes,
        headers={"X-Razorpay-Signature": fail_sig, "X-Razorpay-Event-Id": "evt_cap_close_001"},
    )

    # 2. Ingest payment.captured -> closes case
    cap_bytes = load_fixture("valid_payment_captured.json")
    cap_sig = compute_signature(cap_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=cap_bytes,
        headers={"X-Razorpay-Signature": cap_sig, "X-Razorpay-Event-Id": "evt_cap_close_002"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"

    # 3. Verify DB state
    async with test_session_factory() as session:
        case_res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = case_res.scalar_one_or_none()
        assert case is not None
        assert case.state == RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION.value
        assert case.closed_at is None

        # Check PAYMENT_TRUTH_AWAITING_LINK_ATTRIBUTION audit event
        audit_res = await session.execute(
            select(AuditEventModel).where(
                AuditEventModel.case_id == case.case_id,
                AuditEventModel.event_type
                == AuditEventType.PAYMENT_TRUTH_AWAITING_LINK_ATTRIBUTION.value,
            )
        )
        awaiting_event = audit_res.scalar_one_or_none()
        assert awaiting_event is not None


@pytest.mark.asyncio
async def test_order_paid_closes_active_recovery_case(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure order.paid closes an active recovery case."""
    # 1. Pre-seed consented customer
    async with test_session_factory() as session:
        cust_repo = CustomerRepository(session)
        customer = Customer(
            customer_id="cust_order_test_001",
            masked_phone="+91******1234",
            masked_email="c***@example.com",
        )
        await cust_repo.save_customer(customer)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=customer.customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
            )
        )
        await session.commit()

    # Ingest failed payment -> creates active case
    fail_bytes = load_fixture("valid_payment_failed.json")
    fail_sig = compute_signature(fail_bytes)
    await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=fail_bytes,
        headers={"X-Razorpay-Signature": fail_sig, "X-Razorpay-Event-Id": "evt_ord_close_001"},
    )

    # 2. Ingest order.paid
    paid_bytes = load_fixture("valid_order_paid.json")
    paid_sig = compute_signature(paid_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=paid_bytes,
        headers={"X-Razorpay-Signature": paid_sig, "X-Razorpay-Event-Id": "evt_ord_close_002"},
    )
    assert resp.status_code == 200

    # 3. Verify DB state
    async with test_session_factory() as session:
        case_res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = case_res.scalar_one_or_none()
        assert case is not None
        assert case.state == RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION.value
        assert case.closed_at is None


@pytest.mark.asyncio
async def test_failed_event_on_already_paid_order_does_not_create_active_case(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure late failed payment on already PAID order creates no active recovery case."""
    # 1. Ingest captured payment first
    cap_bytes = load_fixture("valid_payment_captured.json")
    cap_sig = compute_signature(cap_bytes)
    await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=cap_bytes,
        headers={"X-Razorpay-Signature": cap_sig, "X-Razorpay-Event-Id": "evt_paid_pre_001"},
    )

    # 2. Ingest late failed payment for same order
    late_fail_bytes = load_fixture("payment_captured_then_failed.json")
    late_fail_sig = compute_signature(late_fail_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=late_fail_bytes,
        headers={"X-Razorpay-Signature": late_fail_sig, "X-Razorpay-Event-Id": "evt_late_fail_002"},
    )
    assert resp.status_code == 200

    # 3. Verify no active recovery case exists
    async with test_session_factory() as session:
        case_res = await session.execute(
            select(RecoveryCaseModel).where(
                RecoveryCaseModel.order_id == "order_test_001",
                RecoveryCaseModel.closed_at.is_(None),
            )
        )
        active_cases = case_res.scalars().all()
        assert len(active_cases) == 0


@pytest.mark.asyncio
async def test_database_enforces_one_active_case_uniqueness_on_concurrent_insert(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure SQLite partial index prevents concurrent active cases for same order."""
    order_id = "order_concurrent_test_001"
    attempt_id_1 = "pay_attempt_c1"
    attempt_id_2 = "pay_attempt_c2"

    async with test_session_factory() as session:
        order_repo = OrderRepository(session)
        case_repo = RecoveryCaseRepository(session)

        # 1. Create base order and attempt records
        await order_repo.save_order(
            Order(order_id=order_id, amount_paise=50000, status=OrderStatus.ATTEMPTED)
        )
        await order_repo.record_payment_attempt(
            PaymentAttempt(
                payment_id=attempt_id_1,
                order_id=order_id,
                amount_paise=50000,
                status=PaymentStatus.FAILED,
            )
        )
        await order_repo.record_payment_attempt(
            PaymentAttempt(
                payment_id=attempt_id_2,
                order_id=order_id,
                amount_paise=50000,
                status=PaymentStatus.FAILED,
            )
        )

        # 2. Insert first active case
        case1 = RecoveryCase(
            case_id="rcv_conc_001",
            order_id=order_id,
            failed_attempt_id=attempt_id_1,
            state=RecoveryCaseState.RECEIVED,
        )
        await case_repo.save_case(case1)
        await session.commit()

    # 3. Simulate concurrent race inserting a second active case for same order
    async with test_session_factory() as session2:
        case_repo2 = RecoveryCaseRepository(session2)
        case2 = RecoveryCase(
            case_id="rcv_conc_002",
            order_id=order_id,
            failed_attempt_id=attempt_id_2,
            state=RecoveryCaseState.RECEIVED,
        )
        with pytest.raises(DuplicateActiveCaseError):
            await case_repo2.save_case(case2)
            await session2.commit()

    # 4. Assert exactly ONE active recovery case exists in database
    async with test_session_factory() as session3:
        stmt = select(RecoveryCaseModel).where(
            RecoveryCaseModel.order_id == order_id,
            RecoveryCaseModel.closed_at.is_(None),
        )
        res = await session3.execute(stmt)
        active_cases = res.scalars().all()
        assert len(active_cases) == 1
        assert active_cases[0].case_id == "rcv_conc_001"


@pytest.mark.asyncio
async def test_new_active_case_allowed_after_previous_case_closed(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure partial unique index permits a new active case after previous case has closed."""
    order_id = "order_reopen_test_001"
    attempt_id_1 = "pay_attempt_r1"
    attempt_id_2 = "pay_attempt_r2"

    async with test_session_factory() as session:
        order_repo = OrderRepository(session)
        case_repo = RecoveryCaseRepository(session)

        # 1. Create order & attempt
        await order_repo.save_order(
            Order(order_id=order_id, amount_paise=50000, status=OrderStatus.ATTEMPTED)
        )
        await order_repo.record_payment_attempt(
            PaymentAttempt(
                payment_id=attempt_id_1,
                order_id=order_id,
                amount_paise=50000,
                status=PaymentStatus.FAILED,
            )
        )
        await order_repo.record_payment_attempt(
            PaymentAttempt(
                payment_id=attempt_id_2,
                order_id=order_id,
                amount_paise=50000,
                status=PaymentStatus.FAILED,
            )
        )

        # 2. Create and close first case
        case1 = RecoveryCase(
            case_id="rcv_closed_001",
            order_id=order_id,
            failed_attempt_id=attempt_id_1,
            state=RecoveryCaseState.RECEIVED,
        )
        await case_repo.save_case(case1)
        await case_repo.close_active_case_for_order(
            order_id, closure_reason=RecoveryCaseClosureReason.POLICY_BLOCKED
        )
        await session.commit()

    # 3. Create second active case for same order
    async with test_session_factory() as session2:
        case_repo2 = RecoveryCaseRepository(session2)
        case2 = RecoveryCase(
            case_id="rcv_active_002",
            order_id=order_id,
            failed_attempt_id=attempt_id_2,
            state=RecoveryCaseState.RECEIVED,
        )
        await case_repo2.save_case(case2)
        await session2.commit()

    # 4. Verify both exist in DB, with exactly one active
    async with test_session_factory() as session3:
        all_res = await session3.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == order_id)
        )
        all_cases = all_res.scalars().all()
        assert len(all_cases) == 2

        active_res = await session3.execute(
            select(RecoveryCaseModel).where(
                RecoveryCaseModel.order_id == order_id,
                RecoveryCaseModel.closed_at.is_(None),
            )
        )
        active_cases = active_res.scalars().all()
        assert len(active_cases) == 1
        assert active_cases[0].case_id == "rcv_active_002"

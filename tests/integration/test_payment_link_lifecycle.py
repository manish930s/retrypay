"""Integration tests for Payment Link webhook handling, attribution, and timeout."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.api.routes.webhooks import reconcile_expired_attribution_cases
from retrypay.domain.models import (
    EventSource,
    Order,
    OrderStatus,
    PaymentLink,
    PaymentLinkStatus,
    RecoveryCase,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)
from retrypay.storage.models import RecoveryCaseModel
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.links import PaymentLinkRepository
from retrypay.storage.repositories.orders import OrderRepository
from tests.conftest import compute_signature


def make_plink_payload(
    event: str,
    link_id: str,
    status_str: str,
    order_id: str = "order_test_001",
    payment_id: str | None = None,
    amount: int = 50000,
) -> bytes:
    """Helper to generate signed payment_link.* webhook payload."""
    plink_entity: dict[str, Any] = {
        "id": link_id,
        "amount": amount,
        "currency": "INR",
        "status": status_str,
        "reference_id": f"ref_{link_id}",
        "order_id": order_id,
        "notes": {"recovery_case_id": "rcv_test_001", "order_id": order_id},
    }
    payload_container: dict[str, Any] = {"payment_link": {"entity": plink_entity}}
    if payment_id:
        payload_container["payment"] = {
            "entity": {
                "id": payment_id,
                "order_id": order_id,
                "amount": amount,
                "status": "captured",
            }
        }

    data: dict[str, Any] = {
        "entity": "event",
        "event": event,
        "event_id": f"evt_plink_{event.replace('.', '_')}_{link_id}",
        "payload": payload_container,
        "created_at": 1771913100,
    }
    return json.dumps(data).encode("utf-8")


def make_payment_captured_payload(
    payment_id: str,
    order_id: str,
    amount: int = 50000,
    notes: dict[str, Any] | None = None,
    description: str = "",
) -> bytes:
    """Helper to generate signed payment.captured webhook payload."""
    data: dict[str, Any] = {
        "entity": "event",
        "event": "payment.captured",
        "event_id": f"evt_pay_cap_{payment_id}",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                    "notes": notes or {},
                    "description": description,
                }
            }
        },
        "created_at": 1771913150,
    }
    return json.dumps(data).encode("utf-8")


@pytest.mark.asyncio
async def test_sequence_a_payment_link_paid_then_payment_captured(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sequence A: payment_link.paid arrives first -> payment.captured later -> RECOVERED."""
    link_id = "plink_seq_a_001"
    order_id = "order_seq_a_001"
    payment_id = "pay_seq_a_001"

    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        link_repo = PaymentLinkRepository(session)
        order_repo = OrderRepository(session)

        await order_repo.save_order(
            Order(
                order_id=order_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=50000,
                status=OrderStatus.ATTEMPTED,
            ),
            source=EventSource.RAZORPAY_TEST_MODE.value,
        )
        case = RecoveryCase(
            case_id="rcv_seq_a_001",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            failed_attempt_id="pay_fail_001",
            state=RecoveryCaseState.LINK_CREATED,
        )
        await case_repo.save_case(case, source=EventSource.RAZORPAY_TEST_MODE.value)

        link = PaymentLink(
            link_id="plink_local_seq_a",
            source=EventSource.RAZORPAY_TEST_MODE,
            case_id=case.case_id,
            action_id="act_seq_a_001",
            provider_link_id=link_id,
            reference_id=f"ref_{link_id}",
            short_url=f"https://rzp.io/i/{link_id}",
            amount_paise=50000,
            currency="INR",
            status=PaymentLinkStatus.CREATED,
            expire_by=case.created_at,
            provider_created_at=case.created_at,
        )
        await link_repo.save_link(link, source=EventSource.RAZORPAY_TEST_MODE.value)
        await session.commit()

    # Step 1: payment_link.paid webhook arrives first
    payload_plink = make_plink_payload("payment_link.paid", link_id, "paid", order_id=order_id)
    resp1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_plink,
        headers={
            "X-Razorpay-Signature": compute_signature(payload_plink),
            "X-Razorpay-Event-Id": "evt_a_1",
        },
    )
    assert resp1.status_code == 200

    # Case transitions to RECOVERED via payment_link.paid settlement correlation
    async with test_session_factory() as session:
        c1 = (
            await session.execute(
                select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == "rcv_seq_a_001")
            )
        ).scalar_one()
        assert c1.state == RecoveryCaseState.RECOVERED.value

    # Step 2: payment.captured webhook arrives later
    payload_pay = make_payment_captured_payload(payment_id, order_id)
    resp2 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_pay,
        headers={
            "X-Razorpay-Signature": compute_signature(payload_pay),
            "X-Razorpay-Event-Id": "evt_a_2",
        },
    )
    assert resp2.status_code == 200

    # Case transitions to RECOVERED (RECOVERED_VIA_LINK)
    async with test_session_factory() as session:
        c2 = (
            await session.execute(
                select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == "rcv_seq_a_001")
            )
        ).scalar_one()
        assert c2.state == RecoveryCaseState.RECOVERED.value
        assert c2.closure_reason == RecoveryCaseClosureReason.RECOVERED_VIA_LINK.value


@pytest.mark.asyncio
async def test_sequence_b_payment_captured_then_payment_link_paid(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sequence B: payment.captured -> PENDING_ATTRIBUTION -> payment_link.paid -> RECOVERED."""
    link_id = "plink_seq_b_001"
    order_id = "order_seq_b_001"
    payment_id = "pay_seq_b_001"

    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        link_repo = PaymentLinkRepository(session)
        order_repo = OrderRepository(session)

        await order_repo.save_order(
            Order(
                order_id=order_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=50000,
                status=OrderStatus.ATTEMPTED,
            ),
            source=EventSource.RAZORPAY_TEST_MODE.value,
        )
        case = RecoveryCase(
            case_id="rcv_seq_b_001",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            failed_attempt_id="pay_fail_001",
            state=RecoveryCaseState.NOTIFIED,
        )
        await case_repo.save_case(case, source=EventSource.RAZORPAY_TEST_MODE.value)

        link = PaymentLink(
            link_id="plink_local_seq_b",
            source=EventSource.RAZORPAY_TEST_MODE,
            case_id=case.case_id,
            action_id="act_seq_b_001",
            provider_link_id=link_id,
            reference_id=f"ref_{link_id}",
            short_url=f"https://rzp.io/i/{link_id}",
            amount_paise=50000,
            currency="INR",
            status=PaymentLinkStatus.CREATED,
            expire_by=case.created_at,
            provider_created_at=case.created_at,
        )
        await link_repo.save_link(link, source=EventSource.RAZORPAY_TEST_MODE.value)
        await session.commit()

    # Step 1: payment.captured arrives first without link notes
    payload_pay = make_payment_captured_payload(payment_id, order_id)
    resp1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_pay,
        headers={
            "X-Razorpay-Signature": compute_signature(payload_pay),
            "X-Razorpay-Event-Id": "evt_b_1",
        },
    )
    assert resp1.status_code == 200

    # Case transitions to PAYMENT_CONFIRMED_PENDING_ATTRIBUTION (NOT CLOSED_BLOCKED!)
    async with test_session_factory() as session:
        c1 = (
            await session.execute(
                select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == "rcv_seq_b_001")
            )
        ).scalar_one()
        assert c1.state == RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION.value
        assert c1.closed_at is None

    # Step 2: payment_link.paid arrives later
    payload_plink = make_plink_payload(
        "payment_link.paid", link_id, "paid", order_id=order_id, payment_id=payment_id
    )
    resp2 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_plink,
        headers={
            "X-Razorpay-Signature": compute_signature(payload_plink),
            "X-Razorpay-Event-Id": "evt_b_2",
        },
    )
    assert resp2.status_code == 200

    # Case transitions to RECOVERED (RECOVERED_VIA_LINK)
    async with test_session_factory() as session:
        c2 = (
            await session.execute(
                select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == "rcv_seq_b_001")
            )
        ).scalar_one()
        assert c2.state == RecoveryCaseState.RECOVERED.value
        assert c2.closure_reason == RecoveryCaseClosureReason.RECOVERED_VIA_LINK.value


@pytest.mark.asyncio
async def test_order_paid_then_payment_link_paid_recovers(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure order.paid -> payment_link.paid reconciles to RECOVERED."""
    link_id = "plink_seq_op_001"
    order_id = "order_seq_op_001"

    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        link_repo = PaymentLinkRepository(session)
        order_repo = OrderRepository(session)

        await order_repo.save_order(
            Order(
                order_id=order_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=50000,
                status=OrderStatus.ATTEMPTED,
            ),
            source=EventSource.RAZORPAY_TEST_MODE.value,
        )
        case = RecoveryCase(
            case_id="rcv_seq_op_001",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            failed_attempt_id="pay_fail_001",
            state=RecoveryCaseState.LINK_CREATED,
        )
        await case_repo.save_case(case, source=EventSource.RAZORPAY_TEST_MODE.value)

        link = PaymentLink(
            link_id="plink_local_seq_op",
            source=EventSource.RAZORPAY_TEST_MODE,
            case_id=case.case_id,
            action_id="act_seq_op_001",
            provider_link_id=link_id,
            reference_id=f"ref_{link_id}",
            short_url=f"https://rzp.io/i/{link_id}",
            amount_paise=50000,
            currency="INR",
            status=PaymentLinkStatus.CREATED,
            expire_by=case.created_at,
            provider_created_at=case.created_at,
        )
        await link_repo.save_link(link, source=EventSource.RAZORPAY_TEST_MODE.value)
        await session.commit()

    # Step 1: order.paid arrives
    order_payload = json.dumps(
        {
            "entity": "event",
            "event": "order.paid",
            "event_id": "evt_op_1",
            "payload": {
                "order": {
                    "entity": {
                        "id": order_id,
                        "amount": 50000,
                        "currency": "INR",
                        "status": "paid",
                    }
                }
            },
        }
    ).encode("utf-8")
    resp1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=order_payload,
        headers={
            "X-Razorpay-Signature": compute_signature(order_payload),
            "X-Razorpay-Event-Id": "evt_op_1",
        },
    )
    assert resp1.status_code == 200

    # Step 2: payment_link.paid arrives
    payload_plink = make_plink_payload("payment_link.paid", link_id, "paid", order_id=order_id)
    resp2 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_plink,
        headers={
            "X-Razorpay-Signature": compute_signature(payload_plink),
            "X-Razorpay-Event-Id": "evt_op_2",
        },
    )
    assert resp2.status_code == 200

    async with test_session_factory() as session:
        c = (
            await session.execute(
                select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == "rcv_seq_op_001")
            )
        ).scalar_one()
        assert c.state == RecoveryCaseState.RECOVERED.value
        assert c.closure_reason == RecoveryCaseClosureReason.RECOVERED_VIA_LINK.value


@pytest.mark.asyncio
async def test_reconciliation_timeout_closes_case_unconfirmed(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure cases in pending attribution past 30-min window close as CLOSED_BLOCKED."""
    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        order_repo = OrderRepository(session)

        await order_repo.save_order(
            Order(order_id="order_timeout_001", amount_paise=50000, status=OrderStatus.PAID)
        )
        old_time = datetime.now(UTC) - timedelta(minutes=35)
        case = RecoveryCase(
            case_id="rcv_timeout_001",
            order_id="order_timeout_001",
            failed_attempt_id="pay_fail_001",
            state=RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION,
            created_at=old_time,
            updated_at=old_time,
        )
        await case_repo.save_case(case)
        await session.commit()

        # Run reconciliation timeout check
        closed = await reconcile_expired_attribution_cases(session, window_minutes=30)
        assert "rcv_timeout_001" in closed
        await session.commit()

        c = (
            await session.execute(
                select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == "rcv_timeout_001")
            )
        ).scalar_one()
        assert c.state == RecoveryCaseState.CLOSED_BLOCKED.value
        assert c.closure_reason == RecoveryCaseClosureReason.PAYMENT_ATTRIBUTION_UNCONFIRMED.value


@pytest.mark.asyncio
async def test_independent_payment_without_active_link_closes_immediately(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure independent payment with no active link closes immediately as CLOSED_BLOCKED."""
    order_id = "order_indep_001"
    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        order_repo = OrderRepository(session)

        await order_repo.save_order(
            Order(
                order_id=order_id,
                source=EventSource.RAZORPAY_TEST_MODE,
                amount_paise=50000,
                status=OrderStatus.ATTEMPTED,
            ),
            source=EventSource.RAZORPAY_TEST_MODE.value,
        )
        case = RecoveryCase(
            case_id="rcv_indep_001",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order_id,
            failed_attempt_id="pay_fail_001",
            state=RecoveryCaseState.ENRICHING,  # No link exists
        )
        await case_repo.save_case(case, source=EventSource.RAZORPAY_TEST_MODE.value)
        await session.commit()

    payload_pay = make_payment_captured_payload("pay_indep_001", order_id)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_pay,
        headers={
            "X-Razorpay-Signature": compute_signature(payload_pay),
            "X-Razorpay-Event-Id": "evt_indep_1",
        },
    )
    assert resp.status_code == 200

    async with test_session_factory() as session:
        c = (
            await session.execute(
                select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == "rcv_indep_001")
            )
        ).scalar_one()
        assert c.state == RecoveryCaseState.CLOSED_BLOCKED.value
        assert c.closure_reason == RecoveryCaseClosureReason.PAYMENT_CAPTURED.value


@pytest.mark.asyncio
async def test_duplicate_events_idempotent_no_state_change(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure replaying a processed event is completely idempotent and changes no state."""
    payload = make_payment_captured_payload("pay_dup_001", "order_dup_001")
    sig = compute_signature(payload)

    # First post
    r1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_dup_001"},
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "accepted"

    # Duplicate post with same event ID
    r2 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_dup_001"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"

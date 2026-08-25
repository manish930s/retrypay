"""Scenario tests for event ordering, out-of-order handling, and order reconciliation."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.models import OrderStatus, PaymentStatus
from retrypay.storage.models import OrderModel, PaymentAttemptModel
from tests.conftest import compute_signature, load_fixture


@pytest.mark.asyncio
async def test_scenario_failed_then_captured_reconciliation(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scenario: payment.failed received, followed by payment.captured for the same order.

    Order progresses from ATTEMPTED -> PAID.
    Both payment attempts remain in audit history.
    """
    # 1. Ingest failed payment
    fail_bytes = load_fixture("valid_payment_failed.json")
    fail_sig = compute_signature(fail_bytes)
    resp1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=fail_bytes,
        headers={"X-Razorpay-Signature": fail_sig, "X-Razorpay-Event-Id": "evt_sc1_fail"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "accepted"

    # 2. Ingest captured payment
    cap_bytes = load_fixture("valid_payment_captured.json")
    cap_sig = compute_signature(cap_bytes)
    resp2 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=cap_bytes,
        headers={"X-Razorpay-Signature": cap_sig, "X-Razorpay-Event-Id": "evt_sc1_cap"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "accepted"

    # 3. Verify final DB state
    async with test_session_factory() as session:
        order_res = await session.execute(
            select(OrderModel).where(OrderModel.order_id == "order_test_001")
        )
        order = order_res.scalar_one_or_none()
        assert order is not None
        assert order.status == OrderStatus.PAID.value

        attempts_res = await session.execute(
            select(PaymentAttemptModel)
            .where(PaymentAttemptModel.order_id == "order_test_001")
            .order_by(PaymentAttemptModel.occurred_at.asc())
        )
        attempts = attempts_res.scalars().all()
        assert len(attempts) == 2
        assert attempts[0].status == PaymentStatus.FAILED.value
        assert attempts[1].status == PaymentStatus.CAPTURED.value


@pytest.mark.asyncio
async def test_scenario_out_of_order_captured_then_failed_precedence(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scenario: payment.captured received BEFORE payment.failed (out-of-order delivery).

    Order transitions to PAID on capture and is NOT downgraded when the late failure arrives.
    """
    # 1. Ingest captured payment first
    cap_bytes = load_fixture("valid_payment_captured.json")
    cap_sig = compute_signature(cap_bytes)
    resp1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=cap_bytes,
        headers={"X-Razorpay-Signature": cap_sig, "X-Razorpay-Event-Id": "evt_sc2_cap"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "accepted"

    # 2. Ingest out-of-order failed payment for the same order
    late_fail_bytes = load_fixture("payment_captured_then_failed.json")
    late_fail_sig = compute_signature(late_fail_bytes)
    resp2 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=late_fail_bytes,
        headers={"X-Razorpay-Signature": late_fail_sig, "X-Razorpay-Event-Id": "evt_sc2_late_fail"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "accepted"

    # 3. Verify final DB state
    async with test_session_factory() as session:
        order_res = await session.execute(
            select(OrderModel).where(OrderModel.order_id == "order_test_001")
        )
        order = order_res.scalar_one_or_none()
        assert order is not None
        assert order.status == OrderStatus.PAID.value


@pytest.mark.asyncio
async def test_scenario_captured_then_order_paid_idempotence(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scenario: payment.captured followed by order.paid event.

    Both events succeed and order remains in PAID status.
    """
    # 1. Ingest captured payment
    cap_bytes = load_fixture("valid_payment_captured.json")
    cap_sig = compute_signature(cap_bytes)
    await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=cap_bytes,
        headers={"X-Razorpay-Signature": cap_sig, "X-Razorpay-Event-Id": "evt_sc3_cap"},
    )

    # 2. Ingest order.paid
    order_paid_bytes = load_fixture("valid_order_paid.json")
    order_paid_sig = compute_signature(order_paid_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=order_paid_bytes,
        headers={
            "X-Razorpay-Signature": order_paid_sig,
            "X-Razorpay-Event-Id": "evt_sc3_order_paid",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    async with test_session_factory() as session:
        order_res = await session.execute(
            select(OrderModel).where(OrderModel.order_id == "order_test_001")
        )
        order = order_res.scalar_one_or_none()
        assert order is not None
        assert order.status == OrderStatus.PAID.value

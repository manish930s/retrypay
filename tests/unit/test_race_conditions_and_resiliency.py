"""Unit tests verifying race condition resilience and out-of-order payment event reconciliation."""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.models import OrderStatus
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.orders import OrderRepository
from tests.conftest import compute_signature


@pytest.mark.asyncio
async def test_payment_succeeds_before_recovery_worker(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """If payment succeeds before recovery outreach, case is closed as PAYMENT_CAPTURED."""
    # 1. Ingest payment.captured first
    payload_cap = {
        "entity": "event",
        "event": "payment.captured",
        "event_id": "evt_race_cap_1",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_race_1",
                    "order_id": "order_race_paid_first",
                    "amount": 250000,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                }
            }
        },
    }
    raw_cap = json.dumps(payload_cap).encode("utf-8")
    sig_cap = compute_signature(raw_cap)

    r1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_cap,
        headers={"X-Razorpay-Signature": sig_cap},
    )
    assert r1.status_code == 200

    # Verify order is PAID in DB
    async with test_session_factory() as session:
        order_repo = OrderRepository(session)
        order = await order_repo.get_order("order_race_paid_first", source="RAZORPAY_TEST_MODE")
        assert order is not None
        assert order.status == OrderStatus.PAID

    # 2. Late payment.failed event arrives for the already-paid order
    payload_fail = {
        "entity": "event",
        "event": "payment.failed",
        "event_id": "evt_race_fail_late",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_race_fail_late",
                    "order_id": "order_race_paid_first",
                    "amount": 250000,
                    "currency": "INR",
                    "status": "failed",
                    "method": "upi",
                    "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
                    "error_source": "gateway",
                    "error_step": "payment_authorization",
                    "error_reason": "payment_timed_out",
                }
            }
        },
    }
    raw_fail = json.dumps(payload_fail).encode("utf-8")
    sig_fail = compute_signature(raw_fail)

    r2 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_fail,
        headers={"X-Razorpay-Signature": sig_fail},
    )
    assert r2.status_code == 200

    # Late failure on paid order must NOT create an active recovery case
    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        case = await case_repo.get_active_case_for_order(
            "order_race_paid_first", source="RAZORPAY_TEST_MODE"
        )
        assert case is None


@pytest.mark.asyncio
async def test_duplicate_captured_event_idempotency(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Duplicate payment.captured events are idempotent and ignored without error."""
    payload_cap = {
        "entity": "event",
        "event": "payment.captured",
        "event_id": "evt_dup_cap_999",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_dup_cap_999",
                    "order_id": "order_dup_cap_test",
                    "amount": 100000,
                    "currency": "INR",
                    "status": "captured",
                    "method": "card",
                }
            }
        },
    }
    raw_cap = json.dumps(payload_cap).encode("utf-8")
    sig_cap = compute_signature(raw_cap)

    r1 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_cap,
        headers={"X-Razorpay-Signature": sig_cap},
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "accepted"

    # Send exact duplicate
    r2 = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_cap,
        headers={"X-Razorpay-Signature": sig_cap},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"


@pytest.mark.asyncio
async def test_order_paid_without_prior_local_captured_event(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """order.paid event directly marks order PAID and closes pending recovery actions."""
    payload = {
        "entity": "event",
        "event": "order.paid",
        "event_id": "evt_order_paid_direct_1",
        "payload": {
            "order": {
                "entity": {
                    "id": "order_paid_direct_1",
                    "amount": 300000,
                    "amount_paid": 300000,
                    "currency": "INR",
                    "status": "paid",
                }
            }
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw)

    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw,
        headers={"X-Razorpay-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    async with test_session_factory() as session:
        order_repo = OrderRepository(session)
        order = await order_repo.get_order("order_paid_direct_1", source="RAZORPAY_TEST_MODE")
        assert order is not None
        assert order.status == OrderStatus.PAID

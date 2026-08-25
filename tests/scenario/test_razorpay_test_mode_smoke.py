"""End-to-End Scenario Test for Razorpay Test Mode Smoke Test (Steps 1 through 19)."""

import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
    EventSource,
    OrderStatus,
    RecoveryCaseState,
)
from retrypay.storage.models import WebhookOutboxJobModel
from retrypay.storage.repositories.audit import AuditRepository
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.storage.repositories.links import PaymentLinkRepository
from retrypay.storage.repositories.orders import OrderRepository
from tests.conftest import compute_signature


@pytest.mark.asyncio
async def test_full_razorpay_test_mode_smoke_test_lifecycle(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Execute complete 19-step developer Test Mode smoke-test lifecycle."""
    order_id = "ord_smoke_test_999"
    payment_id = "pay_smoke_failed_999"
    event_id = "evt_smoke_failed_999"
    customer_id = f"cust_{order_id}"

    # Pre-seed customer profile & consent so policy evaluation yields ELIGIBLE
    now = datetime.now(UTC)
    async with test_session_factory() as session:
        cust_repo = CustomerRepository(session)
        customer = Customer(
            customer_id=customer_id,
            masked_email="smo***@example.com",
            masked_phone="+91******3210",
            successful_purchase_count=1,
            created_at=now,
        )
        await cust_repo.save_customer(customer)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_IN,
                updated_at=now,
            )
        )
        await session.commit()

    # ---------------------------------------------------------
    # STEP 1, 2, 3, 4, 5, 6: Trigger payment.failed via external webhook
    # ---------------------------------------------------------
    payload_failed = {
        "entity": "event",
        "event": "payment.failed",
        "event_id": event_id,
        "created_at": 1771761600,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
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
    raw_bytes = json.dumps(payload_failed).encode("utf-8")
    sig = compute_signature(raw_bytes)

    resp_ingest = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_bytes,
        headers={
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": event_id,
        },
    )
    assert resp_ingest.status_code == 200
    ingest_json = resp_ingest.json()
    assert ingest_json["status"] == "accepted"
    assert ingest_json["source"] == EventSource.RAZORPAY_TEST_MODE.value
    assert "outbox_job_id" in ingest_json

    # ---------------------------------------------------------
    # STEP 6, 7: Verify outbox job was created and marked COMPLETED
    # ---------------------------------------------------------
    async with test_session_factory() as session:
        res = await session.execute(
            select(WebhookOutboxJobModel).where(WebhookOutboxJobModel.provider_event_id == event_id)
        )
        outbox_job = res.scalar_one_or_none()
        assert outbox_job is not None
        assert outbox_job.status == "COMPLETED"
        assert outbox_job.source == EventSource.RAZORPAY_TEST_MODE.value

    # ---------------------------------------------------------
    # STEP 8, 9, 10, 11, 12, 13: Verify Case State & Created Payment Link
    # ---------------------------------------------------------
    case_id: str = ""
    link_id: str = ""
    ref_id: str = ""

    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        order_repo = OrderRepository(session)
        link_repo = PaymentLinkRepository(session)

        order = await order_repo.get_order(order_id, source=EventSource.RAZORPAY_TEST_MODE.value)
        assert order is not None
        assert order.status == OrderStatus.ATTEMPTED

        case = await case_repo.get_active_case_for_order(
            order_id, source=EventSource.RAZORPAY_TEST_MODE.value
        )
        assert case is not None
        case_id = case.case_id

        active_link = await link_repo.get_active_link_for_case(
            case_id, source=EventSource.RAZORPAY_TEST_MODE.value
        )
        assert active_link is not None
        link_id = active_link.provider_link_id
        ref_id = active_link.reference_id

    # ---------------------------------------------------------
    # STEP 14, 15, 16, 17, 18: Ingest payment_link.paid webhook to complete recovery
    # ---------------------------------------------------------
    paid_event_id = "evt_smoke_link_paid_999"

    payload_paid = {
        "entity": "event",
        "event": "payment_link.paid",
        "event_id": paid_event_id,
        "payload": {
            "payment_link": {
                "entity": {
                    "id": link_id,
                    "reference_id": ref_id,
                    "amount": 250000,
                    "status": "paid",
                }
            }
        },
    }
    raw_paid_bytes = json.dumps(payload_paid).encode("utf-8")
    sig_paid = compute_signature(raw_paid_bytes)

    resp_paid = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_paid_bytes,
        headers={
            "X-Razorpay-Signature": sig_paid,
            "X-Razorpay-Event-Id": paid_event_id,
        },
    )
    assert resp_paid.status_code == 200

    # Verify final state: Order is PAID, case is RECOVERED / CLOSED
    async with test_session_factory() as session:
        order_repo = OrderRepository(session)
        case_repo = RecoveryCaseRepository(session)
        audit_repo = AuditRepository(session)

        final_order = await order_repo.get_order(
            order_id, source=EventSource.RAZORPAY_TEST_MODE.value
        )
        assert final_order is not None
        assert final_order.status == OrderStatus.PAID

        final_case = await case_repo.get_case(case_id, source=EventSource.RAZORPAY_TEST_MODE.value)
        assert final_case is not None
        assert not final_case.is_active
        assert final_case.state in (
            RecoveryCaseState.RECOVERED,
            RecoveryCaseState.CLOSED_BLOCKED,
        )

        # ---------------------------------------------------------
        # STEP 19: Verify complete audit timeline
        # ---------------------------------------------------------
        audit_events = await audit_repo.get_audit_events_for_case(case_id)
        assert len(audit_events) >= 2
        event_types = [e.event_type for e in audit_events]
        assert "CASE_CREATED" in event_types

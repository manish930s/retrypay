"""Integration tests for the Milestone 4 bounded recovery execution pipeline."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
    PaymentLinkStatus,
    RecoveryCaseClosureReason,
    RecoveryCaseState,
)
from retrypay.storage.models import (
    BudgetReservationModel,
    NotificationLogModel,
    PaymentLinkModel,
    RecoveryCaseModel,
)
from retrypay.storage.repositories.customers import CustomerRepository
from tests.conftest import compute_signature, load_fixture


@pytest.mark.asyncio
async def test_end_to_end_execution_flow_to_notified(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure eligible failure moves through link creation, budget, and notification to NOTIFIED."""
    # 1. Pre-seed synthetic customer with OPTED_IN consent
    async with test_session_factory() as session:
        cust_repo = CustomerRepository(session)
        customer = Customer(
            customer_id="cust_order_test_001",
            masked_phone="+91******1234",
            masked_email="c***@example.com",
            successful_purchase_count=2,
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
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_exec_test_001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"

    # 3. Verify database state
    async with test_session_factory() as session:
        case_res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = case_res.scalar_one_or_none()
        assert case is not None
        assert case.state == RecoveryCaseState.LINK_CREATED.value
        assert case.contact_count == 0

        # Check PaymentLink record
        link_res = await session.execute(
            select(PaymentLinkModel).where(PaymentLinkModel.case_id == case.case_id)
        )
        link = link_res.scalar_one_or_none()
        assert link is not None
        assert link.status == PaymentLinkStatus.CREATED.value

        # Check NotificationLog record (must be None in TERMINAL_ONLY delivery mode)
        notif_res = await session.execute(
            select(NotificationLogModel).where(NotificationLogModel.case_id == case.case_id)
        )
        notif = notif_res.scalar_one_or_none()
        assert notif is None

        # Check BudgetReservation record
        bres_res = await session.execute(
            select(BudgetReservationModel).where(BudgetReservationModel.case_id == case.case_id)
        )
        bres = bres_res.scalar_one_or_none()
        assert bres is not None
        assert bres.status == "COMMITTED"


@pytest.mark.asyncio
async def test_attributable_payment_capture_marks_recovered(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure payment capture explicitly tied to active recovery link marks case as RECOVERED."""
    # 1. Pre-seed customer and execute recovery to NOTIFIED
    async with test_session_factory() as session:
        cust_repo = CustomerRepository(session)
        customer = Customer(
            customer_id="cust_order_test_001",
            masked_phone="+91******1234",
            masked_email="c***@example.com",
            successful_purchase_count=1,
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

    fail_bytes = load_fixture("valid_payment_failed.json")
    fail_sig = compute_signature(fail_bytes)
    await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=fail_bytes,
        headers={"X-Razorpay-Signature": fail_sig, "X-Razorpay-Event-Id": "evt_att_001"},
    )

    # 2. Get created link ID
    case_id: str
    link_id: str
    async with test_session_factory() as session:
        case_res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = case_res.scalar_one()
        case_id = case.case_id
        link_res = await session.execute(
            select(PaymentLinkModel).where(PaymentLinkModel.case_id == case_id)
        )
        link = link_res.scalar_one()
        link_id = link.link_id

    # 3. Ingest payment.captured with explicit note matching recovery_case_id
    cap_data: dict[str, Any] = {
        "event": "payment.captured",
        "entity": "event",
        "event_id": "evt_att_cap_002",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_recovered_123",
                    "order_id": "order_test_001",
                    "amount": 50000,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                    "notes": {"recovery_case_id": case_id, "link_id": link_id},
                    "created_at": 1771913100,
                }
            }
        },
    }
    cap_bytes = json_bytes(cap_data)
    cap_sig = compute_signature(cap_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=cap_bytes,
        headers={"X-Razorpay-Signature": cap_sig, "X-Razorpay-Event-Id": "evt_att_cap_002"},
    )
    assert resp.status_code == 200

    # 4. Verify case is RECOVERED and link is PAID
    async with test_session_factory() as session:
        case_res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == case_id)
        )
        updated_case = case_res.scalar_one()
        assert updated_case.state == RecoveryCaseState.RECOVERED.value
        assert updated_case.closure_reason == RecoveryCaseClosureReason.RECOVERED_VIA_LINK.value

        link_res = await session.execute(
            select(PaymentLinkModel).where(PaymentLinkModel.link_id == link_id)
        )
        updated_link = link_res.scalar_one()
        assert updated_link.status == PaymentLinkStatus.PAID.value


@pytest.mark.asyncio
async def test_unattributed_capture_marks_closed_blocked_not_recovered(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure independent unlinked capture closes case as CLOSED_BLOCKED, not RECOVERED."""
    # 1. Pre-seed customer and execute recovery to NOTIFIED
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

    fail_bytes = load_fixture("valid_payment_failed.json")
    fail_sig = compute_signature(fail_bytes)
    await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=fail_bytes,
        headers={"X-Razorpay-Signature": fail_sig, "X-Razorpay-Event-Id": "evt_unatt_001"},
    )

    # 2. Ingest standard captured fixture without link attribution notes
    cap_bytes = load_fixture("valid_payment_captured.json")
    cap_sig = compute_signature(cap_bytes)
    await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=cap_bytes,
        headers={"X-Razorpay-Signature": cap_sig, "X-Razorpay-Event-Id": "evt_unatt_002"},
    )

    # 3. Verify case is PAYMENT_CONFIRMED_PENDING_ATTRIBUTION, NOT RECOVERED
    async with test_session_factory() as session:
        case_res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = case_res.scalar_one()
        assert case.state == RecoveryCaseState.PAYMENT_CONFIRMED_PENDING_ATTRIBUTION.value
        assert case.closed_at is None

        # When reconciliation window expires -> closes as CLOSED_BLOCKED
        from retrypay.api.routes.webhooks import reconcile_expired_attribution_cases

        closed = await reconcile_expired_attribution_cases(session, window_minutes=0)
        assert case.case_id in closed
        await session.commit()

        updated = (
            await session.execute(
                select(RecoveryCaseModel).where(RecoveryCaseModel.case_id == case.case_id)
            )
        ).scalar_one()
        assert updated.state == RecoveryCaseState.CLOSED_BLOCKED.value
        assert (
            updated.closure_reason
            == RecoveryCaseClosureReason.PAYMENT_ATTRIBUTION_UNCONFIRMED.value
        )


def json_bytes(data: dict[str, Any]) -> bytes:
    import json

    return json.dumps(data).encode("utf-8")

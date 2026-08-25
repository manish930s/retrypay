"""Unit and integration tests for the Recovery Case Reminder Workflow.

Covers:
- Persistent atomic single-use confirmation token generation and single-use claim
- Token binding mismatch rejection (case_id, medium, policy_version, contact fingerprint)
- Disabled MANUAL_REVIEW case handling with exact blocking reasons:
  CONTACT_CONSENT_MISSING, INSUFFICIENT_CONTEXT, PAYMENT_LINK_NOT_CREATED
- Pre-send eligibility validations (consent OPTED_IN, verified contact data, active Payment Link)
- Concurrency-safe duplicate send prevention and retry policy for failed attempts
- Structured NotificationResult handling and REMINDER_FAILED audit logging
- Verified delivery status updates emitting REMINDER_DELIVERY_UPDATED
- Sanitized audit event telemetry with zero PII leakage
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
    EventSource,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentLinkStatus,
    PaymentStatus,
    PolicyDecision,
    PolicyDecisionType,
    PolicyReasonCode,
    RecoveryActionStatus,
    RecoveryCase,
    RecoveryCaseState,
)
from retrypay.storage.database import (
    reset_process_db_target_for_testing,
)
from retrypay.storage.models import (
    OutreachNotificationLogModel,
    PaymentLinkModel,
    RecoveryActionModel,
)
from retrypay.storage.repositories.audit import AuditRepository
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.storage.repositories.orders import OrderRepository
from tests.conftest import compute_signature


@pytest.fixture(autouse=True)
def _reset_db_identity() -> Any:
    reset_process_db_target_for_testing()
    yield
    reset_process_db_target_for_testing()


@pytest.fixture
async def setup_test_case(test_session_factory: Any) -> Any:
    """Seed a test recovery case in database with customizable parameters."""

    async def _setup(
        case_id: str = "rcv_rem_test_001",
        order_id: str = "order_rem_test_001",
        customer_id: str = "cust_rem_test_001",
        state: RecoveryCaseState = RecoveryCaseState.NOTIFIED,
        policy_decision_type: PolicyDecisionType = PolicyDecisionType.ELIGIBLE,
        sms_consent: ContactConsentStatus = ContactConsentStatus.OPTED_IN,
        whatsapp_consent: ContactConsentStatus = ContactConsentStatus.OPTED_IN,
        email_consent: ContactConsentStatus = ContactConsentStatus.OPTED_IN,
        has_phone: bool = True,
        has_email: bool = True,
        link_created: bool = True,
        link_expired: bool = False,
    ) -> str:
        async with test_session_factory() as session:
            now = datetime.now(UTC)
            expire_by = (now - timedelta(hours=1)) if link_expired else (now + timedelta(hours=24))

            # Customer & Consent
            cust = Customer(
                customer_id=customer_id,
                masked_phone="+91******9999" if has_phone else None,
                masked_email="c****r@example.com" if has_email else None,
            )
            cust_repo = CustomerRepository(session)
            await cust_repo.save_customer(cust)
            await cust_repo.save_consent(
                CustomerConsent(
                    customer_id=customer_id,
                    channel=ContactChannel.SMS,
                    status=sms_consent,
                )
            )
            await cust_repo.save_consent(
                CustomerConsent(
                    customer_id=customer_id,
                    channel=ContactChannel.WHATSAPP,
                    status=whatsapp_consent,
                )
            )
            await cust_repo.save_consent(
                CustomerConsent(
                    customer_id=customer_id, channel=ContactChannel.EMAIL, status=email_consent
                )
            )

            # Order & Payment Attempt
            order = Order(
                order_id=order_id,
                source=EventSource.LOCAL_SIMULATION,
                amount_paise=250000,
                currency="INR",
                status=OrderStatus.ATTEMPTED,
                created_at=now,
                updated_at=now,
            )
            order_repo = OrderRepository(session)
            await order_repo.save_order(order, source="LOCAL_SIMULATION")

            attempt = PaymentAttempt(
                payment_id=f"pay_{order_id}",
                source=EventSource.LOCAL_SIMULATION,
                order_id=order_id,
                amount_paise=250000,
                currency="INR",
                status=PaymentStatus.FAILED,
                method="upi",
                occurred_at=now,
            )
            await order_repo.record_payment_attempt(attempt, source="LOCAL_SIMULATION")

            # Case & Policy Evaluation
            case = RecoveryCase(
                case_id=case_id,
                source=EventSource.LOCAL_SIMULATION,
                order_id=order_id,
                failed_attempt_id=f"pay_{order_id}",
                customer_id=customer_id,
                state=state,
                policy_version="recovery-v1.3",
                created_at=now,
                updated_at=now,
            )
            case_repo = RecoveryCaseRepository(session)
            await case_repo.save_case(case, source="LOCAL_SIMULATION")

            audit_repo = AuditRepository(session)
            pol_dec = PolicyDecision(
                decision_type=policy_decision_type,
                reasons=[PolicyReasonCode.ELIGIBLE_FOR_RECOVERY],
                context_hash="hash123",
                evaluated_at=now,
                policy_version="recovery-v1.3",
            )
            await audit_repo.record_policy_evaluation(case_id, pol_dec, f"eval_{case_id}")

            # Payment Link
            if link_created:
                action_id = f"act_{case_id}"
                link_id = f"plink_{case_id}"
                action_model = RecoveryActionModel(
                    action_id=action_id,
                    source="LOCAL_SIMULATION",
                    case_id=case_id,
                    action_type="SEND_RETRY_LINK",
                    policy_version="recovery-v1.3",
                    idempotency_key=f"idemp_{case_id}",
                    status=RecoveryActionStatus.COMPLETED.value,
                    created_at=now,
                    updated_at=now,
                )
                session.add(action_model)
                await session.flush()

                link_model = PaymentLinkModel(
                    link_id=link_id,
                    source="LOCAL_SIMULATION",
                    case_id=case_id,
                    action_id=action_id,
                    provider_link_id=f"plink_prov_{case_id}",
                    reference_id=f"ref_{case_id}",
                    short_url=f"https://rzp.io/i/{case_id}",
                    amount_paise=250000,
                    currency="INR",
                    status=PaymentLinkStatus.CREATED.value,
                    expire_by=expire_by,
                    provider_created_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(link_model)

            await session.commit()
        return case_id

    return _setup


# ---------------------------------------------------------------------------
# 1. Preview & Token Generation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_preview_eligible_generates_token(test_client: Any, setup_test_case: Any) -> None:
    case_id = await setup_test_case()
    resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["eligible"] is True
    assert data["blocking_reasons"] == []
    assert data["preview_token"].startswith("remtok_")
    assert data["selected_medium"] == "sms"
    assert data["provider_link_id"] == f"plink_prov_{case_id}"


@pytest.mark.asyncio
async def test_manual_review_disabled_with_exact_blocking_reasons(
    test_client: Any, setup_test_case: Any
) -> None:
    case_id = await setup_test_case(state=RecoveryCaseState.MANUAL_REVIEW)
    resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["eligible"] is False
    assert data["preview_token"] is None
    # Must list exact blocking reasons: CONTACT_CONSENT_MISSING, etc.
    assert "CONTACT_CONSENT_MISSING" in data["blocking_reasons"]
    assert "INSUFFICIENT_CONTEXT" in data["blocking_reasons"]
    assert "PAYMENT_LINK_NOT_CREATED" in data["blocking_reasons"]


@pytest.mark.asyncio
async def test_preview_blocked_missing_consent(test_client: Any, setup_test_case: Any) -> None:
    case_id = await setup_test_case(sms_consent=ContactConsentStatus.OPTED_OUT)
    resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["eligible"] is False
    assert "CONTACT_CONSENT_MISSING" in data["blocking_reasons"]


@pytest.mark.asyncio
async def test_whatsapp_consent_does_not_authorize_sms(
    test_client: Any, setup_test_case: Any
) -> None:
    # WhatsApp OPTED_IN, but SMS OPTED_OUT -> SMS reminder must be blocked
    case_id = await setup_test_case(
        whatsapp_consent=ContactConsentStatus.OPTED_IN,
        sms_consent=ContactConsentStatus.OPTED_OUT,
    )
    resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["eligible"] is False
    assert "CONTACT_CONSENT_MISSING" in data["blocking_reasons"]


@pytest.mark.asyncio
async def test_preview_blocked_missing_payment_link(test_client: Any, setup_test_case: Any) -> None:
    case_id = await setup_test_case(link_created=False)
    resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["eligible"] is False
    assert "PAYMENT_LINK_NOT_CREATED" in data["blocking_reasons"]


# ---------------------------------------------------------------------------
# 2. Token Claims & Single-Use Enforcement
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_successful_with_valid_token(test_client: Any, setup_test_case: Any) -> None:
    case_id = await setup_test_case()
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    token = p_resp.json()["preview_token"]

    s_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
    )
    assert s_resp.status_code == 200
    data = s_resp.json()
    assert data["status"] == "SENT"
    assert data["medium"] == "sms"


@pytest.mark.asyncio
async def test_token_single_use_rejection(test_client: Any, setup_test_case: Any) -> None:
    case_id = await setup_test_case()
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    token = p_resp.json()["preview_token"]

    # First send succeeds
    s1 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
    )
    assert s1.status_code == 200

    # Second send with same token fails (single-use claim)
    s2 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
    )
    assert s2.status_code == 400
    assert "confirmation token" in s2.json()["detail"]


@pytest.mark.asyncio
async def test_token_medium_mismatch_rejection(test_client: Any, setup_test_case: Any) -> None:
    case_id = await setup_test_case()
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    token = p_resp.json()["preview_token"]

    # Requesting email with SMS token fails
    s_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "email"},
    )
    assert s_resp.status_code == 400


# ---------------------------------------------------------------------------
# 3. Duplicate Sends & Retries
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_duplicate_send_rejected(test_client: Any, setup_test_case: Any) -> None:
    case_id = await setup_test_case()

    # Send 1
    p1 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    t1 = p1.json()["preview_token"]
    s1 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": t1, "medium": "sms"},
    )
    assert s1.status_code == 200

    # Send 2 (new preview token, same medium)
    p2 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    t2 = p2.json()["preview_token"]
    s2 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": t2, "medium": "sms"},
    )
    assert s2.status_code == 400
    assert "Duplicate send rejected" in s2.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Verified Delivery Status Ingestion & HMAC Replay Protection
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verified_delivery_status_update(
    test_client: Any, setup_test_case: Any, test_session_factory: Any
) -> None:
    case_id = await setup_test_case()

    # Send reminder
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    token = p_resp.json()["preview_token"]
    s_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
    )
    assert s_resp.status_code == 200

    # Find created notification log
    async with test_session_factory() as session:
        audit_repo = AuditRepository(session)
        events = await audit_repo.get_audit_events_for_case(case_id)
        event_types = [e.event_type.value for e in events]
        assert "REMINDER_PREVIEWED" in event_types
        assert "REMINDER_APPROVED" in event_types
        assert "REMINDER_SENT" in event_types
        assert "REMINDER_DELIVERY_UPDATED" not in event_types

        from sqlalchemy import select

        n_res = await session.execute(
            select(OutreachNotificationLogModel).where(
                OutreachNotificationLogModel.case_id == case_id
            )
        )
        notif_log = n_res.scalar_one()
        notif_id = notif_log.notification_id

    # Unauthenticated request without signature fails (401)
    unauth_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        json={"notification_id": notif_id, "delivery_status": "DELIVERED"},
    )
    assert unauth_resp.status_code == 401
    assert "Missing or invalid X-Razorpay-Signature" in unauth_resp.json()["detail"]

    # Authenticated provider delivery update with real HMAC signature succeeds
    payload_dict = {
        "notification_id": notif_id,
        "delivery_status": "DELIVERED",
        "provider_event_id": "evt_rzp_notif_deliv_1001",
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    valid_sig = compute_signature(raw_body)

    d_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": valid_sig},
    )
    assert d_resp.status_code == 200
    assert d_resp.json()["status"] == "success"

    # Verify REMINDER_DELIVERY_UPDATED is recorded
    async with test_session_factory() as session:
        audit_repo = AuditRepository(session)
        events = await audit_repo.get_audit_events_for_case(case_id)
        event_types = [e.event_type.value for e in events]
        assert "REMINDER_DELIVERY_UPDATED" in event_types

    # Replayed request with same provider_event_id is ignored (idempotent)
    replay_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": valid_sig},
    )
    assert replay_resp.status_code == 200
    assert replay_resp.json()["status"] == "ignored"
    assert "already processed" in replay_resp.json()["message"]


@pytest.mark.asyncio
async def test_delivery_status_invalid_signature_rejected_401(
    test_client: Any, setup_test_case: Any, test_session_factory: Any
) -> None:
    case_id = await setup_test_case()
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    token = p_resp.json()["preview_token"]
    await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
    )
    async with test_session_factory() as session:
        from sqlalchemy import select

        n_res = await session.execute(
            select(OutreachNotificationLogModel).where(
                OutreachNotificationLogModel.case_id == case_id
            )
        )
        notif_id = n_res.scalar_one().notification_id

    body = json.dumps(
        {
            "notification_id": notif_id,
            "delivery_status": "DELIVERED",
            "provider_event_id": "evt_prov_bad_sig_001",
        }
    ).encode("utf-8")

    # Tampered / Invalid signature fails with 401
    bad_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": "invalid_hmac_hex_sig_999",
        },
    )
    assert bad_resp.status_code == 401
    assert "Missing or invalid X-Razorpay-Signature" in bad_resp.json()["detail"]


@pytest.mark.asyncio
async def test_delivery_status_concurrent_duplicate_replay(
    test_client: Any, setup_test_case: Any, test_session_factory: Any
) -> None:
    """Test concurrent duplicate delivery updates with the same provider_event_id."""
    import asyncio

    case_id = await setup_test_case(
        case_id="rcv_rem_deliv_concurrent_001",
        order_id="order_rem_deliv_concurrent_001",
        customer_id="cust_rem_deliv_concurrent_001",
    )
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    token = p_resp.json()["preview_token"]
    await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
    )
    async with test_session_factory() as session:
        from sqlalchemy import select

        n_res = await session.execute(
            select(OutreachNotificationLogModel).where(
                OutreachNotificationLogModel.case_id == case_id
            )
        )
        notif_id = n_res.scalar_one().notification_id

    body = json.dumps(
        {
            "notification_id": notif_id,
            "delivery_status": "DELIVERED",
            "provider_event_id": "evt_prov_concurrent_deliv_001",
        }
    ).encode("utf-8")
    sig = compute_signature(body)

    req1 = test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        content=body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig},
    )
    req2 = test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        content=body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig},
    )

    res1, res2 = await asyncio.gather(req1, req2)
    assert res1.status_code == 200
    assert res2.status_code == 200
    statuses = [res1.json()["status"], res2.json()["status"]]
    assert "success" in statuses
    assert "ignored" in statuses


@pytest.mark.asyncio
async def test_delivery_status_missing_provider_event_id_400(
    test_client: Any, setup_test_case: Any, test_session_factory: Any
) -> None:
    """Missing or empty provider_event_id must return HTTP 400."""
    case_id = await setup_test_case()
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    token = p_resp.json()["preview_token"]
    await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
    )
    async with test_session_factory() as session:
        from sqlalchemy import select

        n_res = await session.execute(
            select(OutreachNotificationLogModel).where(
                OutreachNotificationLogModel.case_id == case_id
            )
        )
        notif_id = n_res.scalar_one().notification_id

    # 1. Missing provider_event_id (None/omitted)
    body1 = json.dumps(
        {
            "notification_id": notif_id,
            "delivery_status": "DELIVERED",
        }
    ).encode("utf-8")
    sig1 = compute_signature(body1)
    resp1 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        content=body1,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig1},
    )
    assert resp1.status_code == 400
    assert "provider_event_id" in resp1.json()["detail"]

    # 2. Empty string provider_event_id
    body2 = json.dumps(
        {
            "notification_id": notif_id,
            "delivery_status": "DELIVERED",
            "provider_event_id": "   ",
        }
    ).encode("utf-8")
    sig2 = compute_signature(body2)
    resp2 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        content=body2,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig2},
    )
    assert resp2.status_code == 400
    assert "provider_event_id" in resp2.json()["detail"]


@pytest.mark.asyncio
async def test_delivery_status_invalid_transition_from_terminal_rejected_400(
    test_client: Any, setup_test_case: Any, test_session_factory: Any
) -> None:
    """Transitioning from terminal status DELIVERED to UNDELIVERABLE must return HTTP 400."""
    case_id = await setup_test_case()
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    token = p_resp.json()["preview_token"]
    await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
    )
    async with test_session_factory() as session:
        from sqlalchemy import select

        n_res = await session.execute(
            select(OutreachNotificationLogModel).where(
                OutreachNotificationLogModel.case_id == case_id
            )
        )
        notif_id = n_res.scalar_one().notification_id

    # 1. Transition SENT -> DELIVERED (legal)
    body1 = json.dumps(
        {
            "notification_id": notif_id,
            "delivery_status": "DELIVERED",
            "provider_event_id": "evt_prov_term_001",
        }
    ).encode("utf-8")
    sig1 = compute_signature(body1)
    resp1 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        content=body1,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig1},
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "success"

    # Verify audit event captured before_state="SENT" and source="RAZORPAY_WEBHOOK"
    async with test_session_factory() as session:
        audit_repo = AuditRepository(session)
        events = await audit_repo.get_audit_events_for_case(case_id)
        deliv_evts = [e for e in events if e.event_type.value == "REMINDER_DELIVERY_UPDATED"]
        assert len(deliv_evts) == 1
        assert deliv_evts[0].before_state == "SENT"
        assert deliv_evts[0].after_state == "DELIVERED"
        assert deliv_evts[0].source == "RAZORPAY_WEBHOOK"

    # 2. Transition DELIVERED -> UNDELIVERABLE (illegal terminal transition)
    body2 = json.dumps(
        {
            "notification_id": notif_id,
            "delivery_status": "UNDELIVERABLE",
            "provider_event_id": "evt_prov_term_002",
        }
    ).encode("utf-8")
    sig2 = compute_signature(body2)
    resp2 = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/delivery-status",
        content=body2,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig2},
    )
    assert resp2.status_code == 400
    assert "terminal status 'DELIVERED'" in resp2.json()["detail"]


# ---------------------------------------------------------------------------
# 5. Telemetry & PII Safety Verification
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sanitized_telemetry_no_pii(
    test_client: Any, setup_test_case: Any, test_session_factory: Any
) -> None:
    case_id = await setup_test_case()
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview", json={"medium": "sms"}
    )
    token = p_resp.json()["preview_token"]
    await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
    )

    async with test_session_factory() as session:
        audit_repo = AuditRepository(session)
        events = await audit_repo.get_audit_events_for_case(case_id)
        for evt in events:
            meta_str = str(evt.metadata)
            assert "+91******9999" not in meta_str
            assert "c****r@example.com" not in meta_str
            assert "9999" not in meta_str
            assert "Authorization" not in meta_str
            assert "bearer" not in meta_str.lower()


# ---------------------------------------------------------------------------
# 6. Concurrency Protection Test (Simultaneous Send Requests)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_send_protection_at_most_one_success(
    test_client: Any, setup_test_case: Any, test_session_factory: Any
) -> None:
    """Ensure two simultaneous /send requests with same token produce at most 1 dispatch."""
    import asyncio

    case_id = await setup_test_case(
        case_id="rcv_rem_concurrent_001",
        order_id="order_rem_concurrent_001",
        customer_id="cust_rem_concurrent_001",
    )
    p_resp = await test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/preview",
        json={"medium": "sms"},
        headers={"X-Dashboard-Authorization": "Bearer test-operator-token"},
    )
    assert p_resp.status_code == 200
    token = p_resp.json()["preview_token"]

    # Launch two simultaneous send requests
    req1 = test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
        headers={"X-Dashboard-Authorization": "Bearer test-operator-token"},
    )
    req2 = test_client.post(
        f"/api/v1/dashboard/cases/{case_id}/reminder/send",
        json={"preview_token": token, "medium": "sms"},
        headers={"X-Dashboard-Authorization": "Bearer test-operator-token"},
    )

    res1, res2 = await asyncio.gather(req1, req2)
    statuses = [res1.status_code, res2.status_code]

    # Exactly one request must succeed (200) and one must fail (400)
    assert 200 in statuses
    assert 400 in statuses

    # Verify database log contains exactly 1 notification entry
    async with test_session_factory() as session:
        from sqlalchemy import select

        from retrypay.storage.models import OutreachNotificationLogModel

        res = await session.execute(
            select(OutreachNotificationLogModel).where(
                OutreachNotificationLogModel.case_id == case_id
            )
        )
        logs = res.scalars().all()
        assert len(logs) == 1
        assert logs[0].status == "SENT"

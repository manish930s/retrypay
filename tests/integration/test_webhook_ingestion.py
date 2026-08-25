"""Integration tests for Razorpay webhook ingestion, signature validation, and deduplication."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.api.app import create_app
from retrypay.api.dependencies import get_configured_session_factory
from retrypay.config import AppEnvironment, Settings, get_settings
from retrypay.domain.models import OrderStatus, PaymentStatus
from retrypay.storage.models import OrderModel, PaymentAttemptModel, WebhookEventModel
from tests.conftest import compute_signature, load_fixture


@pytest.mark.asyncio
async def test_ingest_valid_payment_failed(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure valid payment.failed webhook creates order and failed attempt."""
    payload_bytes = load_fixture("valid_payment_failed.json")
    signature = compute_signature(payload_bytes)

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_test_failed_001",
        "Content-Type": "application/json",
    }

    response = await test_client.post(
        "/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data["event_type"] == "payment.failed"
    assert data.get("outbox_job_id") is not None

    # Verify persistence in database
    async with test_session_factory() as session:
        # Check order
        order_res = await session.execute(
            select(OrderModel).where(OrderModel.order_id == "order_test_001")
        )
        order = order_res.scalar_one_or_none()
        assert order is not None
        assert order.status == OrderStatus.ATTEMPTED.value
        assert order.amount_paise == 299900

        # Check attempt
        attempt_res = await session.execute(
            select(PaymentAttemptModel).where(PaymentAttemptModel.payment_id == "pay_fail_001")
        )
        attempt = attempt_res.scalar_one_or_none()
        assert attempt is not None
        assert attempt.status == PaymentStatus.FAILED.value
        assert attempt.error_code == "BAD_REQUEST_PAYMENT_TIMED_OUT"

        # Check webhook event & verify raw_payload is NOT stored by default
        event_res = await session.execute(
            select(WebhookEventModel).where(
                WebhookEventModel.provider_event_id == "evt_test_failed_001"
            )
        )
        event = event_res.scalar_one_or_none()
        assert event is not None
        assert event.signature_verification_status == "valid"
        assert event.processing_status == "processed"
        assert event.raw_payload is None  # Minimized persistence by default


@pytest.mark.asyncio
async def test_ingest_valid_payment_captured(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure valid payment.captured webhook creates/updates order to PAID status."""
    payload_bytes = load_fixture("valid_payment_captured.json")
    signature = compute_signature(payload_bytes)

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_test_captured_001",
        "Content-Type": "application/json",
    }

    response = await test_client.post(
        "/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data["event_type"] == "payment.captured"
    assert data.get("outbox_job_id") is not None

    async with test_session_factory() as session:
        order_res = await session.execute(
            select(OrderModel).where(OrderModel.order_id == "order_test_001")
        )
        order = order_res.scalar_one_or_none()
        assert order is not None
        assert order.status == OrderStatus.PAID.value


@pytest.mark.asyncio
async def test_reject_invalid_signature(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure invalid signature returns HTTP 400 and leaves database unmodified."""
    payload_bytes = load_fixture("invalid_signature.json")
    bad_signature = "bad_signature_digest_12345"

    headers = {
        "X-Razorpay-Signature": bad_signature,
        "X-Razorpay-Event-Id": "evt_test_tampered_001",
        "Content-Type": "application/json",
    }

    response = await test_client.post(
        "/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers
    )
    assert response.status_code == 400
    assert "Invalid webhook signature" in response.json()["detail"]

    # Verify no order or payment attempt was created
    async with test_session_factory() as session:
        order_res = await session.execute(
            select(OrderModel).where(OrderModel.order_id == "order_tampered_001")
        )
        assert order_res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_duplicate_event_idempotency(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure duplicate webhook event ID delivery produces no duplicate side-effects."""
    payload_bytes = load_fixture("duplicate_payment_failed.json")
    signature = compute_signature(payload_bytes)

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_duplicate_001",
        "Content-Type": "application/json",
    }

    # First delivery: processed
    resp1 = await test_client.post(
        "/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "accepted"

    # Second delivery: duplicate ignored
    resp2 = await test_client.post(
        "/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate_ignored"

    # Ensure only 1 payment attempt exists in DB
    async with test_session_factory() as session:
        attempts_res = await session.execute(
            select(PaymentAttemptModel).where(PaymentAttemptModel.payment_id == "pay_fail_dup_001")
        )
        attempts = attempts_res.scalars().all()
        assert len(attempts) == 1


@pytest.mark.asyncio
async def test_unsupported_event_acknowledgement(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure unsupported event type is recorded as UNSUPPORTED and returns HTTP 200."""
    payload_bytes = load_fixture("unsupported_event.json")
    signature = compute_signature(payload_bytes)

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_unsupported_001",
        "Content-Type": "application/json",
    }

    response = await test_client.post(
        "/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unsupported_event_acknowledged"

    async with test_session_factory() as session:
        event_res = await session.execute(
            select(WebhookEventModel).where(
                WebhookEventModel.provider_event_id == "evt_unsupported_001"
            )
        )
        event = event_res.scalar_one_or_none()
        assert event is not None
        assert event.processing_status == "unsupported"


@pytest.mark.asyncio
async def test_malformed_json_rejection(
    test_client: AsyncClient,
) -> None:
    """Ensure malformed JSON payload returns HTTP 400."""
    payload_bytes = load_fixture("malformed_json.json")
    signature = compute_signature(payload_bytes)

    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_malformed_001",
        "Content-Type": "application/json",
    }

    response = await test_client.post(
        "/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers
    )
    assert response.status_code == 400
    assert "Malformed JSON" in response.json()["detail"]


@pytest.mark.asyncio
async def test_raw_payload_retention_when_enabled_in_test_env(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure raw webhook payload is persisted when test flag is enabled."""
    test_settings = Settings(
        RETRYPAY_ENV=AppEnvironment.TEST,
        LLM_ENABLED=False,
        RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=True,
        RAZORPAY_KEY_ID="rzp_test_fixture_key_id",
        RAZORPAY_KEY_SECRET="rzp_test_fixture_secret",
        RAZORPAY_WEBHOOK_SECRET="retrypay_test_webhook_secret_key_123",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )

    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_configured_session_factory] = lambda: test_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload_bytes = load_fixture("valid_payment_failed.json")
        signature = compute_signature(payload_bytes)

        headers = {
            "X-Razorpay-Signature": signature,
            "X-Razorpay-Event-Id": "evt_retain_raw_001",
            "Content-Type": "application/json",
        }

        response = await client.post(
            "/api/v1/webhooks/razorpay", content=payload_bytes, headers=headers
        )
        assert response.status_code == 200

        async with test_session_factory() as session:
            event_res = await session.execute(
                select(WebhookEventModel).where(
                    WebhookEventModel.provider_event_id == "evt_retain_raw_001"
                )
            )
            event = event_res.scalar_one_or_none()
            assert event is not None
            assert event.raw_payload is not None
            assert "payment.failed" in event.raw_payload

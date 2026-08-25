"""Scenario tests verifying deterministic policy outcomes and recovery case lifecycles."""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.api.app import create_app
from retrypay.api.dependencies import get_configured_session_factory, get_settings
from retrypay.config import AppEnvironment, Settings
from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
    RecoveryCaseState,
)
from retrypay.storage.models import RecoveryCaseModel
from retrypay.storage.repositories.customers import CustomerRepository
from tests.conftest import compute_signature, load_fixture


@pytest.mark.asyncio
async def test_scenario_opted_out_customer_closed_blocked(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scenario 2: Opted-out customer transitions directly to CLOSED_BLOCKED."""
    async with test_session_factory() as session:
        cust_repo = CustomerRepository(session)
        customer = Customer(
            customer_id="cust_order_test_001",
            masked_phone="+91******9999",
            masked_email="optout***@example.com",
        )
        await cust_repo.save_customer(customer)
        await cust_repo.save_consent(
            CustomerConsent(
                customer_id=customer.customer_id,
                channel=ContactChannel.WHATSAPP,
                status=ContactConsentStatus.OPTED_OUT,
            )
        )
        await session.commit()

    payload_bytes = load_fixture("valid_payment_failed.json")
    sig = compute_signature(payload_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_sc_optout_001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"

    async with test_session_factory() as session:
        res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = res.scalar_one_or_none()
        assert case is not None
        assert case.state == RecoveryCaseState.CLOSED_BLOCKED.value


@pytest.mark.asyncio
async def test_scenario_missing_consent_manual_review(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scenario 3: Customer with unknown/missing consent transitions to MANUAL_REVIEW."""
    payload_bytes = load_fixture("valid_payment_failed.json")
    sig = compute_signature(payload_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_sc_noconsent_001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"

    async with test_session_factory() as session:
        res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = res.scalar_one_or_none()
        assert case is not None
        assert case.state == RecoveryCaseState.MANUAL_REVIEW.value


@pytest.mark.asyncio
async def test_scenario_high_risk_decline_manual_review(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scenario 4: High-risk decline transitions to MANUAL_REVIEW."""
    test_settings = Settings(
        RETRYPAY_ENV=AppEnvironment.TEST,
        LLM_ENABLED=False,
        RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=False,
        RAZORPAY_KEY_ID="rzp_test_fixture_key_id",
        RAZORPAY_KEY_SECRET="rzp_test_fixture_secret",
        RAZORPAY_WEBHOOK_SECRET="retrypay_test_webhook_secret_key_123",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_configured_session_factory] = lambda: test_session_factory

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

    # Load and mutate fixture for high risk error code
    raw_dict = json.loads(load_fixture("valid_payment_failed.json").decode("utf-8"))
    raw_dict["payload"]["payment"]["entity"]["error_code"] = "CARD_SECURITY_VIOLATION"
    mutated_bytes = json.dumps(raw_dict).encode("utf-8")
    sig = compute_signature(mutated_bytes)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/webhooks/razorpay",
            content=mutated_bytes,
            headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_sc_risk_001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"

    async with test_session_factory() as session:
        res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = res.scalar_one_or_none()
        assert case is not None
        assert case.state == RecoveryCaseState.MANUAL_REVIEW.value

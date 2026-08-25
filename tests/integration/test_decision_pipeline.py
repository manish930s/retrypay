"""Integration tests for the advisory decision pipeline and trace persistence."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    CustomerConsent,
    PolicyDecisionType,
)
from retrypay.storage.models import (
    DecisionTraceModel,
    RecoveryCaseModel,
)
from retrypay.storage.repositories.customers import CustomerRepository
from tests.conftest import compute_signature, load_fixture


@pytest.mark.asyncio
async def test_eligible_policy_produces_persisted_advisory_decision_trace(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure ELIGIBLE policy result triggers decision pipeline and persists DecisionTrace."""
    # 1. Pre-seed synthetic customer with OPTED_IN consent and 2 prior purchases
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
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_trace_test_001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"

    # 3. Verify DecisionTraceModel in SQLite
    async with test_session_factory() as session:
        case_res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = case_res.scalar_one_or_none()
        assert case is not None

        trace_res = await session.execute(
            select(DecisionTraceModel).where(DecisionTraceModel.case_id == case.case_id)
        )
        trace = trace_res.scalar_one_or_none()
        assert trace is not None
        assert trace.policy_decision == PolicyDecisionType.ELIGIBLE.value
        assert trace.estimator_mode == "SIMULATION"
        assert trace.estimator_version == "sim-estimator-v1"
        assert trace.ros_score > 0
        assert trace.selected_action != ""
        assert len(trace.input_context_hash) == 64
        assert len(trace.estimator_output_hash) == 64


@pytest.mark.asyncio
async def test_blocked_policy_does_not_create_decision_trace(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure a BLOCKED policy result does NOT execute decisioning or create a decision trace."""
    # 1. Pre-seed customer with OPTED_OUT consent
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
                status=ContactConsentStatus.OPTED_OUT,
            )
        )
        await session.commit()

    # 2. Ingest payment.failed webhook
    payload_bytes = load_fixture("valid_payment_failed.json")
    sig = compute_signature(payload_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_blocked_trace_001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"

    # 3. Verify zero decision traces exist for this case
    async with test_session_factory() as session:
        case_res = await session.execute(
            select(RecoveryCaseModel).where(RecoveryCaseModel.order_id == "order_test_001")
        )
        case = case_res.scalar_one_or_none()
        assert case is not None

        trace_res = await session.execute(
            select(DecisionTraceModel).where(DecisionTraceModel.case_id == case.case_id)
        )
        traces = trace_res.scalars().all()
        assert len(traces) == 0


@pytest.mark.asyncio
async def test_manual_review_policy_does_not_create_decision_trace(
    test_client: AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure MANUAL_REVIEW policy result does not invoke advisory action selection or trace."""
    # 1. Ingest payment.failed without pre-seeded customer -> INSUFFICIENT_CONTEXT + missing consent
    payload_bytes = load_fixture("valid_payment_failed.json")
    sig = compute_signature(payload_bytes)
    resp = await test_client.post(
        "/api/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_no_cust_001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"

    # 2. Verify zero decision traces in database
    async with test_session_factory() as session:
        traces_res = await session.execute(select(DecisionTraceModel))
        assert len(traces_res.scalars().all()) == 0

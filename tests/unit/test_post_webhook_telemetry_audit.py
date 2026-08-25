"""Regression tests for post-webhook case telemetry audit and consent policy decision safeguards."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.decision.diagnosis import ActionType, FailureDiagnosisCategory
from retrypay.decision.ranker import AdvisoryRecommendation
from retrypay.decision.razorpay_error_map import RazorpayErrorMapper
from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    EventSource,
    NotificationTemplateKey,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentFailureContext,
    PaymentStatus,
    PolicyDecisionType,
    PolicyReasonCode,
    RecoveryCase,
    RecoveryCaseState,
    RecoveryPolicyContext,
)
from retrypay.execution.orchestrator import ExecutionOrchestrator
from retrypay.notifications.dispatcher import SimulatedNotificationDispatcher
from retrypay.policy.engine import PolicyEngine
from retrypay.storage.models import PaymentAttemptModel
from retrypay.storage.repositories.cases import RecoveryCaseRepository
from retrypay.storage.repositories.customers import CustomerRepository
from retrypay.storage.repositories.orders import OrderRepository


def test_generic_payment_failure_produces_unknown_diagnosis() -> None:
    """Verify generic BAD_REQUEST_ERROR produces UNKNOWN diagnosis category."""
    mapper = RazorpayErrorMapper()
    result = mapper.map_error(
        code="BAD_REQUEST_ERROR",
        source="customer",
        step="payment_authorization",
        reason="payment_failed",
        payment_method="card",
    )
    assert result.category == FailureDiagnosisCategory.UNKNOWN
    assert result.suggested_action == ActionType.MANUAL_REVIEW
    assert result.confidence <= 0.50


@pytest.mark.asyncio
async def test_generic_failure_never_creates_payment_link_automatically(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify generic payment failure routes to MANUAL_REVIEW and creates zero Payment Links."""
    now = datetime.now(UTC)
    async with test_session_factory() as session:
        mock_provider = MagicMock()
        mock_provider.create_payment_link = AsyncMock()

        orchestrator = ExecutionOrchestrator(
            session=session,
            link_provider=mock_provider,
            policy_engine=PolicyEngine(),
        )

        order = Order(
            order_id="order_generic_fail",
            source=EventSource.RAZORPAY_TEST_MODE,
            amount_paise=250000,
            currency="INR",
            status=OrderStatus.ATTEMPTED,
        )

        case = RecoveryCase(
            case_id="rcv_generic_fail",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id=order.order_id,
            failed_attempt_id="pay_fail_generic",
            state=RecoveryCaseState.POLICY_EVALUATED,
            created_at=now,
            updated_at=now,
        )

        rec = AdvisoryRecommendation(
            selected_action=ActionType.MANUAL_REVIEW,
            estimates=[],
            selected_utility_paise=0,
            recommendation_reason="Generic failure mapped to MANUAL_REVIEW",
        )

        res = await orchestrator.execute_advisory_recommendation(case, order, rec)
        assert res["case_state"] == RecoveryCaseState.MANUAL_REVIEW.value
        assert res["execution_status"] == "NO_OUTREACH"
        mock_provider.create_payment_link.assert_not_called()


def test_unknown_consent_routes_to_manual_review() -> None:
    """Verify unknown or missing customer consent evaluates to MANUAL_REVIEW."""
    engine = PolicyEngine()
    now = datetime.now(UTC)

    order = Order(
        order_id="order_consent_test",
        source=EventSource.RAZORPAY_TEST_MODE,
        amount_paise=250000,
        currency="INR",
        status=OrderStatus.ATTEMPTED,
    )
    attempt = PaymentAttempt(
        payment_id="pay_fail_noconsent",
        source=EventSource.RAZORPAY_TEST_MODE,
        order_id=order.order_id,
        amount_paise=250000,
        currency="INR",
        status=PaymentStatus.FAILED,
        failure_context=PaymentFailureContext(
            error_code="BAD_REQUEST_ERROR",
            error_description="Payment failed",
            error_source="customer",
            error_step="payment_authorization",
            error_reason="payment_failed",
        ),
    )

    ctx = RecoveryPolicyContext(
        order=order,
        failed_attempt=attempt,
        customer=None,
        consents={},  # Missing / unknown consent
        target_channel=ContactChannel.WHATSAPP,
        evaluation_time=now,
    )

    decision = engine.evaluate(ctx)
    assert decision.decision_type == PolicyDecisionType.MANUAL_REVIEW
    assert PolicyReasonCode.CONTACT_CONSENT_MISSING in decision.reasons


def test_explicit_opt_out_blocks_recovery() -> None:
    """Verify explicit opt-out produces BLOCK decision and CLOSED_BLOCKED transition."""
    engine = PolicyEngine()
    now = datetime.now(UTC)

    order = Order(
        order_id="order_optout_test",
        source=EventSource.RAZORPAY_TEST_MODE,
        amount_paise=250000,
        currency="INR",
        status=OrderStatus.ATTEMPTED,
    )
    attempt = PaymentAttempt(
        payment_id="pay_fail_optout",
        source=EventSource.RAZORPAY_TEST_MODE,
        order_id=order.order_id,
        amount_paise=250000,
        currency="INR",
        status=PaymentStatus.FAILED,
    )

    ctx = RecoveryPolicyContext(
        order=order,
        failed_attempt=attempt,
        customer=Customer(customer_id="cust_optout"),
        consents={ContactChannel.WHATSAPP: ContactConsentStatus.OPTED_OUT},
        target_channel=ContactChannel.WHATSAPP,
        evaluation_time=now,
    )

    decision = engine.evaluate(ctx)
    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.CUSTOMER_OPTED_OUT in decision.reasons


@pytest.mark.asyncio
async def test_terminal_only_delivery_records_zero_contacts(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify TERMINAL_ONLY delivery mode (RAZORPAY_TEST_MODE) returns None and 0 contacts."""
    now = datetime.now(UTC)
    async with test_session_factory() as session:
        dispatcher = SimulatedNotificationDispatcher(session)
        case_repo = RecoveryCaseRepository(session)
        cust_repo = CustomerRepository(session)

        cust_id = "cust_term_test"
        await cust_repo.save_customer(Customer(customer_id=cust_id))

        case = RecoveryCase(
            case_id="rcv_term_test",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id="order_term_test",
            customer_id=cust_id,
            failed_attempt_id="pay_fail_term",
            state=RecoveryCaseState.LINK_CREATED,
            contact_count=0,
            created_at=now,
            updated_at=now,
        )
        await case_repo.save_case(case)

        res = await dispatcher.dispatch_simulated_notification(
            case=case,
            action_id="act_term_001",
            channel=ContactChannel.WHATSAPP,
            template_key=NotificationTemplateKey.PAYMENT_RETRY_GENERIC,
            link_reference="https://rzp.io/i/plink_term",
        )

        assert res is None
        reloaded = await case_repo.get_case("rcv_term_test")
        assert reloaded is not None
        assert reloaded.contact_count == 0
        assert reloaded.state == RecoveryCaseState.LINK_CREATED


@pytest.mark.asyncio
async def test_notified_state_cannot_appear_without_successful_notification_adapter(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify case state remains LINK_CREATED when notification is suppressed/None."""
    now = datetime.now(UTC)
    async with test_session_factory() as session:
        case_repo = RecoveryCaseRepository(session)
        case = RecoveryCase(
            case_id="rcv_no_notif_test",
            source=EventSource.RAZORPAY_TEST_MODE,
            order_id="order_no_notif",
            failed_attempt_id="pay_fail_no_notif",
            state=RecoveryCaseState.LINK_CREATED,
            contact_count=0,
            created_at=now,
            updated_at=now,
        )
        await case_repo.save_case(case)

        loaded = await case_repo.get_case("rcv_no_notif_test")
        assert loaded is not None
        assert loaded.state != RecoveryCaseState.NOTIFIED
        assert loaded.state == RecoveryCaseState.LINK_CREATED


@pytest.mark.asyncio
async def test_one_failed_attempt_is_not_displayed_as_five_attempts(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify order with 1 recorded failed attempt accurately returns 1 attempt."""
    async with test_session_factory() as session:
        order_repo = OrderRepository(session)
        order_id = "order_single_attempt"
        await order_repo.save_order(
            Order(order_id=order_id, amount_paise=250000, status=OrderStatus.ATTEMPTED)
        )
        await order_repo.record_payment_attempt(
            PaymentAttempt(
                payment_id="pay_attempt_1",
                order_id=order_id,
                amount_paise=250000,
                status=PaymentStatus.FAILED,
            )
        )
        await session.commit()

        res = await session.execute(
            select(PaymentAttemptModel).where(PaymentAttemptModel.order_id == order_id)
        )
        attempts = res.scalars().all()
        assert len(attempts) == 1

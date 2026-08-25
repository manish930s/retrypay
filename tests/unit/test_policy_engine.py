"""Unit tests for the deterministic PolicyEngine, hard safeguards, and precedence rules."""

from datetime import UTC, datetime

from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentFailureContext,
    PaymentStatus,
    PolicyDecisionType,
    PolicyReasonCode,
    RecoveryPolicyContext,
)
from retrypay.policy.engine import PolicyEngine

# Standard daytime evaluation time: 14:30 IST (09:00 UTC)
DAYTIME_UTC = datetime(2026, 8, 25, 9, 0, 0, tzinfo=UTC)
# Standard quiet hours evaluation time: 23:30 IST (18:00 UTC)
QUIET_HOURS_UTC = datetime(2026, 8, 25, 18, 0, 0, tzinfo=UTC)


def create_sample_context(
    amount_paise: int = 50000,
    order_status: OrderStatus = OrderStatus.ATTEMPTED,
    error_code: str = "BAD_REQUEST_PAYMENT_TIMED_OUT",
    customer_present: bool = True,
    consent_status: ContactConsentStatus = ContactConsentStatus.OPTED_IN,
    prior_order_contacts: int = 0,
    customer_30d_contacts: int = 0,
    evaluation_time: datetime = DAYTIME_UTC,
) -> RecoveryPolicyContext:
    """Helper to construct a deterministic policy context."""
    order = Order(
        order_id="order_test_100",
        amount_paise=amount_paise if amount_paise > 0 else 1,
        status=order_status,
    )
    # If explicitly testing non-positive amount on order, use model_construct
    if amount_paise <= 0:
        order = Order.model_construct(
            order_id="order_test_100",
            amount_paise=amount_paise,
            currency="INR",
            status=order_status,
            created_at=DAYTIME_UTC,
            updated_at=DAYTIME_UTC,
        )

    attempt = PaymentAttempt(
        payment_id="pay_test_100",
        order_id=order.order_id,
        amount_paise=50000,
        status=PaymentStatus.FAILED,
        method="upi",
        failure_context=PaymentFailureContext(
            error_code=error_code,
            error_description="Test payment failure",
        ),
    )
    customer = (
        Customer(
            customer_id="cust_test_100",
            masked_phone="+91******1234",
            masked_email="u***@example.com",
        )
        if customer_present
        else None
    )
    consents = {ContactChannel.WHATSAPP: consent_status} if customer_present else {}

    return RecoveryPolicyContext(
        order=order,
        failed_attempt=attempt,
        customer=customer,
        consents=consents,
        target_channel=ContactChannel.WHATSAPP,
        prior_order_contact_count=prior_order_contacts,
        customer_30d_contact_count=customer_30d_contacts,
        evaluation_time=evaluation_time,
    )


def test_eligible_policy_evaluation() -> None:
    """Ensure a valid, consented, normal-risk failed payment passes policy as ELIGIBLE."""
    engine = PolicyEngine()
    ctx = create_sample_context()
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.ELIGIBLE
    assert PolicyReasonCode.ELIGIBLE_FOR_RECOVERY in decision.reasons
    assert len(decision.context_hash) == 64


def test_block_order_already_paid() -> None:
    """Rule 1: Paid order must be BLOCKED with ORDER_ALREADY_PAID."""
    engine = PolicyEngine()
    ctx = create_sample_context(order_status=OrderStatus.PAID)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.ORDER_ALREADY_PAID in decision.reasons


def test_block_order_cancelled() -> None:
    """Rule 1: CANCELLED order must be BLOCKED with ORDER_UNRECOVERABLE."""
    engine = PolicyEngine()
    ctx = create_sample_context(order_status=OrderStatus.CANCELLED)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.ORDER_UNRECOVERABLE in decision.reasons


def test_block_order_refunded() -> None:
    """Rule 1: REFUNDED order must be BLOCKED with ORDER_UNRECOVERABLE."""
    engine = PolicyEngine()
    ctx = create_sample_context(order_status=OrderStatus.REFUNDED)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.ORDER_UNRECOVERABLE in decision.reasons


def test_block_order_expired() -> None:
    """Rule 1: EXPIRED order must be BLOCKED with ORDER_UNRECOVERABLE."""
    engine = PolicyEngine()
    ctx = create_sample_context(order_status=OrderStatus.EXPIRED)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.ORDER_UNRECOVERABLE in decision.reasons


def test_block_order_non_positive_amount() -> None:
    """Rule 1: Non-positive amount must be BLOCKED with ORDER_UNRECOVERABLE."""
    engine = PolicyEngine()
    ctx_zero = create_sample_context(amount_paise=0)
    dec_zero = engine.evaluate(ctx_zero)
    assert dec_zero.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.ORDER_UNRECOVERABLE in dec_zero.reasons

    ctx_neg = create_sample_context(amount_paise=-500)
    dec_neg = engine.evaluate(ctx_neg)
    assert dec_neg.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.ORDER_UNRECOVERABLE in dec_neg.reasons


def test_block_unrecoverable_order_and_opted_out_customer() -> None:
    """Precedence test: Both ORDER_UNRECOVERABLE and CUSTOMER_OPTED_OUT are reported on BLOCK."""
    engine = PolicyEngine()
    ctx = create_sample_context(
        order_status=OrderStatus.CANCELLED,
        consent_status=ContactConsentStatus.OPTED_OUT,
    )
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.ORDER_UNRECOVERABLE in decision.reasons
    assert PolicyReasonCode.CUSTOMER_OPTED_OUT in decision.reasons


def test_block_customer_opted_out() -> None:
    """Rule 2: Opted-out customer must be BLOCKED with CUSTOMER_OPTED_OUT."""
    engine = PolicyEngine()
    ctx = create_sample_context(consent_status=ContactConsentStatus.OPTED_OUT)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.CUSTOMER_OPTED_OUT in decision.reasons


def test_manual_review_consent_missing() -> None:
    """Rule 2: Unknown consent must trigger MANUAL_REVIEW with CONTACT_CONSENT_MISSING."""
    engine = PolicyEngine()
    ctx = create_sample_context(consent_status=ContactConsentStatus.UNKNOWN)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.MANUAL_REVIEW
    assert PolicyReasonCode.CONTACT_CONSENT_MISSING in decision.reasons


def test_manual_review_order_contact_cap_exhausted() -> None:
    """Rule 3: Exhausted per-order contact cap (>=2) must be BLOCKED."""
    engine = PolicyEngine()
    ctx = create_sample_context(prior_order_contacts=2)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.ORDER_CONTACT_CAP_REACHED in decision.reasons


def test_block_customer_30d_contact_cap_exhausted() -> None:
    """Rule 3: Exhausted 30-day customer contact cap (>=3) must be BLOCKED."""
    engine = PolicyEngine()
    ctx = create_sample_context(customer_30d_contacts=3)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.CUSTOMER_CONTACT_CAP_REACHED in decision.reasons


def test_amount_threshold_boundaries() -> None:
    """Rule 4: Exact limit ₹10,000 is ELIGIBLE; ₹10,000.01 triggers MANUAL_REVIEW."""
    engine = PolicyEngine()

    # Exact threshold: 1_000_000 paise (₹10,000) -> ELIGIBLE
    ctx_exact = create_sample_context(amount_paise=1_000_000)
    dec_exact = engine.evaluate(ctx_exact)
    assert dec_exact.decision_type == PolicyDecisionType.ELIGIBLE

    # Exceeding threshold: 1_000_001 paise (₹10,000.01) -> MANUAL_REVIEW
    ctx_above = create_sample_context(amount_paise=1_000_001)
    dec_above = engine.evaluate(ctx_above)
    assert dec_above.decision_type == PolicyDecisionType.MANUAL_REVIEW
    assert PolicyReasonCode.AMOUNT_REQUIRES_REVIEW in dec_above.reasons


def test_manual_review_high_risk_decline() -> None:
    """Rule 5: High fraud risk / hard decline must trigger MANUAL_REVIEW."""
    engine = PolicyEngine()
    ctx = create_sample_context(error_code="CARD_SECURITY_VIOLATION")
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.MANUAL_REVIEW
    assert PolicyReasonCode.RISK_REQUIRES_REVIEW in decision.reasons


def test_manual_review_missing_customer_context() -> None:
    """Rule 6: Missing customer profile must trigger MANUAL_REVIEW and consent check."""
    engine = PolicyEngine()
    ctx = create_sample_context(customer_present=False)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.MANUAL_REVIEW
    assert PolicyReasonCode.INSUFFICIENT_CONTEXT in decision.reasons
    assert PolicyReasonCode.CONTACT_CONSENT_MISSING in decision.reasons


def test_defer_quiet_hours() -> None:
    """Rule 7: Quiet hours evaluation must return DEFER with next permitted time."""
    engine = PolicyEngine()
    ctx = create_sample_context(evaluation_time=QUIET_HOURS_UTC)
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.DEFER
    assert PolicyReasonCode.QUIET_HOURS in decision.reasons
    assert decision.deferred_until is not None


def test_policy_precedence_block_overrides_all() -> None:
    """Precedence test: BLOCK overrides MANUAL_REVIEW, DEFER, and ELIGIBLE."""
    engine = PolicyEngine()
    # Combines opt-out (BLOCK), high amount (MANUAL_REVIEW), and quiet hours (DEFER)
    ctx = create_sample_context(
        amount_paise=5_000_000,
        consent_status=ContactConsentStatus.OPTED_OUT,
        evaluation_time=QUIET_HOURS_UTC,
    )
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.BLOCK
    assert PolicyReasonCode.CUSTOMER_OPTED_OUT in decision.reasons
    assert PolicyReasonCode.AMOUNT_REQUIRES_REVIEW in decision.reasons
    assert PolicyReasonCode.QUIET_HOURS in decision.reasons


def test_policy_precedence_manual_review_overrides_defer() -> None:
    """Precedence test: MANUAL_REVIEW overrides DEFER."""
    engine = PolicyEngine()
    # Combines high risk (MANUAL_REVIEW) with quiet hours (DEFER)
    ctx = create_sample_context(
        error_code="SUSPECTED_FRAUD",
        evaluation_time=QUIET_HOURS_UTC,
    )
    decision = engine.evaluate(ctx)

    assert decision.decision_type == PolicyDecisionType.MANUAL_REVIEW
    assert PolicyReasonCode.RISK_REQUIRES_REVIEW in decision.reasons
    assert PolicyReasonCode.QUIET_HOURS in decision.reasons

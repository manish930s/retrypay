"""Deterministic policy evaluation engine enforcing hard recovery safeguards."""

from datetime import datetime

from retrypay.domain.models import (
    MerchantPolicyConfig,
    PolicyDecision,
    PolicyDecisionType,
    PolicyReasonCode,
    RecoveryPolicyContext,
)
from retrypay.policy.rules import (
    check_amount_threshold,
    check_contact_frequency_caps,
    check_context_sufficiency,
    check_customer_consent,
    check_order_terminal_state,
    check_risk_and_decline_type,
    compute_policy_context_hash,
    evaluate_quiet_hours,
)

BLOCK_REASONS = {
    PolicyReasonCode.ORDER_ALREADY_PAID,
    PolicyReasonCode.ORDER_UNRECOVERABLE,
    PolicyReasonCode.CUSTOMER_OPTED_OUT,
    PolicyReasonCode.ORDER_CONTACT_CAP_REACHED,
    PolicyReasonCode.CUSTOMER_CONTACT_CAP_REACHED,
}

MANUAL_REVIEW_REASONS = {
    PolicyReasonCode.CONTACT_CONSENT_MISSING,
    PolicyReasonCode.AMOUNT_REQUIRES_REVIEW,
    PolicyReasonCode.RISK_REQUIRES_REVIEW,
    PolicyReasonCode.INSUFFICIENT_CONTEXT,
}


class PolicyEngine:
    """Deterministic policy engine evaluating recovery eligibility without external effects."""

    def __init__(self, config: MerchantPolicyConfig | None = None) -> None:
        self._config = config or MerchantPolicyConfig()

    @property
    def config(self) -> MerchantPolicyConfig:
        """Active merchant policy configuration."""
        return self._config

    def evaluate(self, context: RecoveryPolicyContext) -> PolicyDecision:
        """Evaluate recovery eligibility against all hard policy gates and apply strict precedence.

        Precedence Hierarchy:
        1. Terminal order/payment blocks
        2. Customer consent & opt-out blocks
        3. Contact-frequency cap blocks
        4. High-risk & amount manual-review gates
        5. Missing-context manual-review gate
        6. Quiet-hours deferral gate
        7. Eligible

        BLOCK overrides MANUAL_REVIEW, DEFER, and ELIGIBLE.
        MANUAL_REVIEW overrides DEFER and ELIGIBLE.
        DEFER overrides ELIGIBLE.
        """
        all_reasons: list[PolicyReasonCode] = []

        # 1. Order Terminal State Rules
        all_reasons.extend(check_order_terminal_state(context))

        # 2. Consent & Opt-out Rules
        all_reasons.extend(check_customer_consent(context))

        # 3. Frequency Cap Rules
        all_reasons.extend(check_contact_frequency_caps(context, self._config))

        # 4. Amount Threshold Rule
        all_reasons.extend(check_amount_threshold(context, self._config))

        # 5. Risk & Hard Decline Rule
        all_reasons.extend(check_risk_and_decline_type(context))

        # 6. Context Sufficiency Rule
        all_reasons.extend(check_context_sufficiency(context))

        # 7. Quiet Hours Gate
        is_quiet, next_permitted_utc = evaluate_quiet_hours(context.evaluation_time, self._config)
        if is_quiet:
            all_reasons.append(PolicyReasonCode.QUIET_HOURS)

        # Precedence Resolution
        decision_type: PolicyDecisionType
        deferred_until: datetime | None = None

        if any(r in BLOCK_REASONS for r in all_reasons):
            decision_type = PolicyDecisionType.BLOCK
        elif any(r in MANUAL_REVIEW_REASONS for r in all_reasons):
            decision_type = PolicyDecisionType.MANUAL_REVIEW
        elif PolicyReasonCode.QUIET_HOURS in all_reasons:
            decision_type = PolicyDecisionType.DEFER
            deferred_until = next_permitted_utc
        else:
            decision_type = PolicyDecisionType.ELIGIBLE
            all_reasons.append(PolicyReasonCode.ELIGIBLE_FOR_RECOVERY)

        context_hash = compute_policy_context_hash(context)

        return PolicyDecision(
            decision_type=decision_type,
            reasons=all_reasons,
            policy_version=self._config.policy_version,
            evaluated_at=context.evaluation_time,
            deferred_until=deferred_until,
            context_hash=context_hash,
        )

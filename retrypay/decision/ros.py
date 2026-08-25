"""Deterministic Recovery Opportunity Score (ROS) calculation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from retrypay.decision.diagnosis import FailureDiagnosisCategory


class ROSInput(BaseModel):
    """Normalized inputs for deterministic ROS scoring."""

    model_config = ConfigDict(frozen=True)

    diagnosis_category: FailureDiagnosisCategory = Field(
        ..., description="Classified failure category"
    )
    attempt_count: int = Field(
        default=1, ge=1, description="Number of payment attempts for this order"
    )
    customer_successful_purchases: int = Field(
        default=0, ge=0, description="Customer prior completed purchase count"
    )
    is_high_risk: bool = Field(
        default=False, description="Whether error indicates high risk or hard decline"
    )
    failure_occurred_at: datetime = Field(..., description="UTC timestamp of the failed payment")
    evaluation_time: datetime = Field(..., description="UTC timestamp of the evaluation")
    has_alternate_payment_method: bool = Field(
        default=False, description="Whether customer has alternate instruments"
    )
    payment_method: str = Field(default="unknown", description="Original payment method")


class ROSResult(BaseModel):
    """Deterministic Recovery Opportunity Score output."""

    model_config = ConfigDict(frozen=True)

    score: int = Field(..., ge=0, le=100, description="Clamped integer score (0-100)")
    feature_contributions: dict[str, int] = Field(
        ..., description="Discrete score contributions by family"
    )
    scoring_version: str = Field(default="ros-v1.0", description="Scoring formula version")
    explanation_reasons: list[str] = Field(
        default_factory=list, description="Traceable explanation strings"
    )
    opportunity_band: str = Field(
        ..., description="HIGH_OPPORTUNITY | CONSERVATIVE_OPPORTUNITY | LOW_OPPORTUNITY"
    )


class ROSCalculator:
    """Deterministic scoring engine computing the Recovery Opportunity Score."""

    VERSION = "ros-v1.0"

    def calculate(self, input_data: ROSInput) -> ROSResult:
        """Calculate the deterministic ROS integer score clamped between 0 and 100."""
        contributions: dict[str, int] = {}
        reasons: list[str] = []

        # 1. Failure recoverability (max +30)
        recov_score = 0
        cat = input_data.diagnosis_category
        if cat == FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK:
            recov_score = 30
            reasons.append("Temporary bank downtime is highly recoverable (+30)")
        elif cat == FailureDiagnosisCategory.UPI_INTENT_INTERRUPTED:
            recov_score = 28
            reasons.append("Interrupted UPI intent is highly recoverable (+28)")
        elif cat == FailureDiagnosisCategory.AUTHENTICATION_INCOMPLETE:
            recov_score = 22
            reasons.append("Incomplete 2FA has strong recovery likelihood (+22)")
        elif cat == FailureDiagnosisCategory.SOFT_DECLINE:
            recov_score = 15
            reasons.append("Soft decline is moderately recoverable (+15)")
        elif cat == FailureDiagnosisCategory.CUSTOMER_CANCELLED:
            recov_score = 8
            reasons.append("Customer cancellation has low recovery likelihood (+8)")
        elif cat == FailureDiagnosisCategory.UNKNOWN:
            recov_score = 5
            reasons.append("Unknown failure has baseline recovery score (+5)")
        elif cat == FailureDiagnosisCategory.HARD_DECLINE_OR_RISK:
            recov_score = 0
            reasons.append("Hard decline or risk carries zero recoverability score (+0)")
        contributions["failure_recoverability"] = recov_score

        # 2. Purchase intent (max +20)
        intent_score = 0
        if input_data.attempt_count >= 2:
            intent_score = 20
            reasons.append(
                f"Multiple checkout attempts ({input_data.attempt_count}) show high intent (+20)"
            )
        elif input_data.attempt_count == 1:
            intent_score = 12
            reasons.append("Single checkout attempt baseline intent (+12)")
        contributions["purchase_intent"] = intent_score

        # 3. Prior merchant relationship (max +15)
        rel_score = 0
        purchases = input_data.customer_successful_purchases
        if purchases >= 3:
            rel_score = 15
            reasons.append(f"Established customer with {purchases} prior purchases (+15)")
        elif purchases in (1, 2):
            rel_score = 8
            reasons.append(f"Returning customer with {purchases} prior purchase(s) (+8)")
        else:
            rel_score = 0
            reasons.append("First-time customer (+0)")
        contributions["prior_merchant_relationship"] = rel_score

        # 4. Risk penalty (max -15)
        risk_penalty = 0
        if input_data.is_high_risk or cat == FailureDiagnosisCategory.HARD_DECLINE_OR_RISK:
            risk_penalty = -15
            reasons.append("High risk or hard decline penalty applied (-15)")
        contributions["risk_penalty"] = risk_penalty

        # 5. Freshness (max +10)
        elapsed_seconds = (
            input_data.evaluation_time - input_data.failure_occurred_at
        ).total_seconds()
        elapsed_minutes = max(0.0, elapsed_seconds / 60.0)
        freshness_score = 0
        if elapsed_minutes <= 10.0:
            freshness_score = 10
            reasons.append("Immediate failure (<10 min) has peak freshness (+10)")
        elif elapsed_minutes <= 60.0:
            freshness_score = 6
            reasons.append("Recent failure (11-60 min) has high freshness (+6)")
        elif elapsed_minutes <= 240.0:
            freshness_score = 3
            reasons.append("Moderate freshness (1-4 hours) (+3)")
        else:
            freshness_score = 0
            reasons.append("Stale failure (>4 hours) (+0)")
        contributions["freshness"] = freshness_score

        # 6. Recovery-route suitability (max +10)
        route_score = 0
        if (
            cat == FailureDiagnosisCategory.UPI_INTENT_INTERRUPTED
            and input_data.has_alternate_payment_method
        ):
            route_score = 10
            reasons.append("UPI intent failure with alternative payment route available (+10)")
        elif cat in (
            FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK,
            FailureDiagnosisCategory.AUTHENTICATION_INCOMPLETE,
        ):
            route_score = 7
            reasons.append("Retry path available for network/auth failure (+7)")
        elif (
            cat == FailureDiagnosisCategory.SOFT_DECLINE and input_data.has_alternate_payment_method
        ):
            route_score = 5
            reasons.append("Soft decline with alternative payment instrument (+5)")
        contributions["recovery_route_suitability"] = route_score

        # Raw total and clamping
        raw_total = (
            recov_score + intent_score + rel_score + risk_penalty + freshness_score + route_score
        )
        clamped_score = max(0, min(100, raw_total))

        # Determine advisory opportunity band
        if clamped_score >= 80:
            band = "HIGH_OPPORTUNITY"
        elif clamped_score >= 60:
            band = "CONSERVATIVE_OPPORTUNITY"
        else:
            band = "LOW_OPPORTUNITY"

        return ROSResult(
            score=clamped_score,
            feature_contributions=contributions,
            scoring_version=self.VERSION,
            explanation_reasons=reasons,
            opportunity_band=band,
        )

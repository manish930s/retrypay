"""Builder for policy-permitted advisory action candidates."""

from pydantic import BaseModel, ConfigDict, Field

from retrypay.decision.diagnosis import (
    ActionType,
    DiagnosisResult,
    FailureDiagnosisCategory,
)
from retrypay.decision.ros import ROSResult
from retrypay.domain.models import PolicyDecision, PolicyDecisionType


class CandidateActionResult(BaseModel):
    """Set of permitted candidate actions and rationale for the decision pipeline."""

    model_config = ConfigDict(frozen=True)

    candidates: list[ActionType] = Field(..., min_length=1, description="Allowed action candidates")
    reasons: list[str] = Field(
        default_factory=list, description="Reasoning for candidate inclusion"
    )


class ActionCandidateBuilder:
    """Constructs candidate action set constrained by policy, diagnosis category, and confidence."""

    def build_candidates(
        self,
        policy_decision: PolicyDecision,
        diagnosis_result: DiagnosisResult,
        ros_result: ROSResult,
    ) -> CandidateActionResult:
        """Construct permitted candidate actions from diagnosis and policy constraints.

        Invariants:
        1. Always includes ActionType.NO_ACTION as baseline.
        2. If policy was not ELIGIBLE, only NO_ACTION is permitted.
        3. If diagnosis has low confidence (<0.60) or category is hard_decline_or_risk / unknown,
           returns [NO_ACTION, MANUAL_REVIEW].
        4. Temporary bank/network failures offer DELAY_AND_SEND_RETRY_LINK and SEND_RETRY_LINK.
        5. UPI intent / soft declines offer hint action and SEND_RETRY_LINK.
        """
        candidates: list[ActionType] = [ActionType.NO_ACTION]
        reasons: list[str] = ["NO_ACTION baseline candidate is always included."]

        # If policy is not ELIGIBLE, no outreach action candidate can be generated
        if policy_decision.decision_type != PolicyDecisionType.ELIGIBLE:
            dt = policy_decision.decision_type.value
            reasons.append(f"Policy decision '{dt}' limits actions to NO_ACTION.")
            return CandidateActionResult(candidates=candidates, reasons=reasons)

        # Low confidence or high-risk diagnosis triggers manual review option
        if diagnosis_result.confidence < 0.60 or diagnosis_result.category in (
            FailureDiagnosisCategory.HARD_DECLINE_OR_RISK,
            FailureDiagnosisCategory.UNKNOWN,
        ):
            candidates.append(ActionType.MANUAL_REVIEW)
            reasons.append(
                f"Diagnosis category '{diagnosis_result.category.value}' or low confidence "
                f"({diagnosis_result.confidence:.2f}) adds MANUAL_REVIEW candidate."
            )
            return CandidateActionResult(candidates=candidates, reasons=reasons)

        cat = diagnosis_result.category
        if cat == FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK:
            candidates.append(ActionType.DELAY_AND_SEND_RETRY_LINK)
            candidates.append(ActionType.SEND_RETRY_LINK)
            reasons.append("Temporary bank/network issue allows delayed retry link or direct link.")

        elif cat in (
            FailureDiagnosisCategory.UPI_INTENT_INTERRUPTED,
            FailureDiagnosisCategory.SOFT_DECLINE,
        ):
            candidates.append(ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT)
            candidates.append(ActionType.SEND_RETRY_LINK)
            reasons.append(
                "UPI or soft decline allows retry link with alternative instrument hint."
            )

        elif cat in (
            FailureDiagnosisCategory.AUTHENTICATION_INCOMPLETE,
            FailureDiagnosisCategory.CUSTOMER_CANCELLED,
        ):
            candidates.append(ActionType.SEND_RETRY_LINK)
            reasons.append("Incomplete authentication or drop-off allows direct retry link.")

        return CandidateActionResult(candidates=candidates, reasons=reasons)

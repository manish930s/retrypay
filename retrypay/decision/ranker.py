"""Action utility ranker selecting the optimal advisory recovery action candidate."""

from pydantic import BaseModel, ConfigDict, Field

from retrypay.decision.diagnosis import ActionType
from retrypay.decision.estimator import ActionValueEstimate


class AdvisoryRecommendation(BaseModel):
    """Advisory action recommendation selected on maximum expected net utility."""

    model_config = ConfigDict(frozen=True)

    selected_action: ActionType = Field(..., description="Selected advisory candidate action")
    estimates: list[ActionValueEstimate] = Field(..., description="Candidate action estimates")
    selected_utility_paise: int = Field(
        ..., description="Estimated net utility of chosen action (paise)"
    )
    tie_break_applied: bool = Field(default=False, description="Whether tie-breaking was applied")
    recommendation_reason: str = Field(..., description="Explanation of why action was selected")


class ActionUtilityRanker:
    """Ranks action value estimates and selects the candidate with deterministic tie-breaking."""

    def rank(self, estimates: list[ActionValueEstimate]) -> AdvisoryRecommendation:
        """Select highest utility action according to deterministic rules.

        Tie-breaking hierarchy:
        1. Higher utility_paise
        2. Lower customer_harm_penalty_paise
        3. Lower variable_action_cost_paise
        4. NO_ACTION preferred
        5. Lexical ordering
        """
        if not estimates:
            raise ValueError("ActionUtilityRanker requires at least one ActionValueEstimate.")

        # Check if all non-NO_ACTION candidate utilities are non-positive (<= 0)
        non_baseline_positive = [
            e for e in estimates if e.action != ActionType.NO_ACTION and e.utility_paise > 0
        ]
        if not non_baseline_positive:
            no_action_est = next(
                (e for e in estimates if e.action == ActionType.NO_ACTION), estimates[0]
            )
            return AdvisoryRecommendation(
                selected_action=ActionType.NO_ACTION,
                estimates=estimates,
                selected_utility_paise=no_action_est.utility_paise,
                tie_break_applied=False,
                recommendation_reason=(
                    "All recovery actions have non-positive utility relative to NO_ACTION."
                ),
            )

        # Sort by primary and tie-breaking keys
        # Key: (-utility, customer_harm, variable_cost, is_not_no_action, action_enum_str)
        def sort_key(e: ActionValueEstimate) -> tuple[int, int, int, int, str]:
            return (
                -e.utility_paise,
                e.customer_harm_penalty_paise,
                e.variable_action_cost_paise,
                0 if e.action == ActionType.NO_ACTION else 1,
                e.action.value,
            )

        sorted_estimates = sorted(estimates, key=sort_key)
        best = sorted_estimates[0]

        # Check if top two tied on utility
        tie_applied = False
        if len(sorted_estimates) > 1 and sorted_estimates[1].utility_paise == best.utility_paise:
            tie_applied = True

        reason = (
            f"Action '{best.action.value}' selected with maximum estimated utility "
            f"of {best.utility_paise} paise."
        )
        if tie_applied:
            reason += " (Deterministic tie-breaking rule applied)."

        return AdvisoryRecommendation(
            selected_action=best.action,
            estimates=estimates,
            selected_utility_paise=best.utility_paise,
            tie_break_applied=tie_applied,
            recommendation_reason=reason,
        )

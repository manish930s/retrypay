"""Simulation-only RecoveryValueEstimator calculating net expected value and action utilities."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from retrypay.decision.diagnosis import ActionType, FailureDiagnosisCategory
from retrypay.decision.ros import ROSResult


class EstimatorMode(StrEnum):
    """Execution mode of the value estimator (restricted strictly to SIMULATION)."""

    SIMULATION = "SIMULATION"


class ObservableCaseFeatures(BaseModel):
    """Sanitized observable case features visible to the value estimator."""

    model_config = ConfigDict(frozen=True)

    order_amount_paise: int = Field(..., gt=0, description="Order value in integer paise")
    ros_score: int = Field(..., ge=0, le=100, description="Recovery Opportunity Score (0-100)")
    diagnosis_category: FailureDiagnosisCategory = Field(
        ..., description="Failure diagnosis category"
    )
    prior_contacts: int = Field(
        default=0, ge=0, description="Previous contacts count for this order"
    )


class SimulationDistributionParameters(BaseModel):
    """Configured simulation distribution parameters and fixed action costs (in paise)."""

    model_config = ConfigDict(frozen=True)

    variable_costs_paise: dict[ActionType, int] = Field(
        default_factory=lambda: {
            ActionType.NO_ACTION: 0,
            ActionType.SEND_RETRY_LINK: 250,  # ₹2.50 messaging cost
            ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT: 250,
            ActionType.DELAY_AND_SEND_RETRY_LINK: 250,
            ActionType.MANUAL_REVIEW: 500,  # ₹5.00 operator triage cost
        }
    )
    customer_harm_penalties_paise: dict[ActionType, int] = Field(
        default_factory=lambda: {
            ActionType.NO_ACTION: 0,
            ActionType.SEND_RETRY_LINK: 100,  # ₹1.00 friction cost
            ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT: 80,
            ActionType.DELAY_AND_SEND_RETRY_LINK: 50,  # Lower friction if delayed
            ActionType.MANUAL_REVIEW: 0,
        }
    )
    operational_costs_paise: dict[ActionType, int] = Field(
        default_factory=lambda: {
            ActionType.NO_ACTION: 0,
            ActionType.SEND_RETRY_LINK: 50,
            ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT: 50,
            ActionType.DELAY_AND_SEND_RETRY_LINK: 50,
            ActionType.MANUAL_REVIEW: 200,
        }
    )


class ActionValueEstimate(BaseModel):
    """Simulation-only estimated value, probabilities, and utility for a candidate action."""

    model_config = ConfigDict(frozen=True)

    baseline_action: ActionType = Field(
        default=ActionType.NO_ACTION, description="Baseline comparator"
    )
    action: ActionType = Field(..., description="Estimated candidate action")
    p_natural_recovery: float = Field(..., ge=0.0, le=1.0, description="P(recovery | NO_ACTION)")
    p_recovery_given_action: float = Field(..., ge=0.0, le=1.0, description="P(recovery | action)")
    incremental_probability: float = Field(
        ..., description="p_recovery_given_action - p_natural_recovery"
    )
    expected_incremental_gmv_paise: int = Field(
        ..., description="round(incremental_prob * order_amount)"
    )
    variable_action_cost_paise: int = Field(..., ge=0, description="Direct outreach cost in paise")
    customer_harm_penalty_paise: int = Field(
        ..., ge=0, description="Friction/spam penalty in paise"
    )
    operational_cost_paise: int = Field(..., ge=0, description="Operational overhead in paise")
    utility_paise: int = Field(..., description="Net expected value in integer paise")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0, description="Estimation confidence")
    estimator_version: str = Field(default="sim-estimator-v1", description="Estimator version")
    mode: EstimatorMode = Field(
        default=EstimatorMode.SIMULATION, description="Always SIMULATION in MVP"
    )


class EstimatorInput(BaseModel):
    """Input payload for the RecoveryValueEstimator."""

    model_config = ConfigDict(frozen=True)

    observable_features: ObservableCaseFeatures = Field(..., description="Case observable features")
    action_candidates: list[ActionType] = Field(
        ..., min_length=1, description="Policy-approved candidates"
    )
    ros_result: ROSResult = Field(..., description="Recovery Opportunity Score result")
    params: SimulationDistributionParameters = Field(
        default_factory=SimulationDistributionParameters,
        description="Simulation parameters and costs",
    )


class SimulationEstimator:
    """Simulation-only estimator calculating incremental recovery probabilities and action utility.

    Strict Boundary Invariants:
    - Never imports or accesses hidden potential outcomes.
    - Operates purely on observable features, ROS, and simulation parameters.
    - Strictly produces advisory SIMULATION labels.
    - NO_ACTION is always evaluated with 0.0 incremental probability and 0 utility.
    """

    VERSION = "sim-estimator-v1"

    def estimate(self, input_data: EstimatorInput) -> list[ActionValueEstimate]:
        """Compute ActionValueEstimate for every candidate action relative to NO_ACTION."""
        obs = input_data.observable_features
        ros_score = input_data.ros_result.score
        params = input_data.params

        # Base natural recovery probability derived from observable ROS
        ros_factor = ros_score / 100.0
        p_natural = max(0.01, min(0.30, 0.05 + 0.10 * ros_factor))

        estimates: list[ActionValueEstimate] = []

        for act in input_data.action_candidates:
            var_cost = params.variable_costs_paise.get(act, 0)
            harm_penalty = params.customer_harm_penalties_paise.get(act, 0)
            op_cost = params.operational_costs_paise.get(act, 0)

            if act == ActionType.NO_ACTION:
                # Invariant: NO_ACTION baseline has 0 incremental prob, 0 costs, 0 utility
                estimates.append(
                    ActionValueEstimate(
                        baseline_action=ActionType.NO_ACTION,
                        action=ActionType.NO_ACTION,
                        p_natural_recovery=round(p_natural, 4),
                        p_recovery_given_action=round(p_natural, 4),
                        incremental_probability=0.0,
                        expected_incremental_gmv_paise=0,
                        variable_action_cost_paise=0,
                        customer_harm_penalty_paise=0,
                        operational_cost_paise=0,
                        utility_paise=0,
                        confidence=1.0,
                        estimator_version=self.VERSION,
                        mode=EstimatorMode.SIMULATION,
                    )
                )
                continue

            # Calculate simulated lift based on candidate action suitability
            if act == ActionType.MANUAL_REVIEW:
                # Operator review has small positive uplift
                boost = 0.05 * ros_factor
            elif act == ActionType.DELAY_AND_SEND_RETRY_LINK:
                # Delayed retry yields higher boost for temporary downtime
                boost = 0.25 * ros_factor + (
                    0.08
                    if obs.diagnosis_category == FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK
                    else 0.02
                )
            elif act == ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT:
                # Alternative method hint yields higher boost for UPI/soft declines
                boost = 0.22 * ros_factor + (
                    0.08
                    if obs.diagnosis_category
                    in (
                        FailureDiagnosisCategory.UPI_INTENT_INTERRUPTED,
                        FailureDiagnosisCategory.SOFT_DECLINE,
                    )
                    else 0.02
                )
            else:  # SEND_RETRY_LINK
                boost = 0.18 * ros_factor

            p_action = min(0.95, p_natural + boost)
            incremental_prob = round(p_action - p_natural, 4)
            expected_gmv = round(incremental_prob * obs.order_amount_paise)
            utility = expected_gmv - var_cost - harm_penalty - op_cost

            estimates.append(
                ActionValueEstimate(
                    baseline_action=ActionType.NO_ACTION,
                    action=act,
                    p_natural_recovery=round(p_natural, 4),
                    p_recovery_given_action=round(p_action, 4),
                    incremental_probability=incremental_prob,
                    expected_incremental_gmv_paise=expected_gmv,
                    variable_action_cost_paise=var_cost,
                    customer_harm_penalty_paise=harm_penalty,
                    operational_cost_paise=op_cost,
                    utility_paise=utility,
                    confidence=0.85,
                    estimator_version=self.VERSION,
                    mode=EstimatorMode.SIMULATION,
                )
            )

        return estimates

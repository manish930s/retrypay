"""Unit tests for the simulation RecoveryValueEstimator, ActionUtilityRanker, and boundaries."""

import ast
from pathlib import Path

from retrypay.decision.candidates import ActionCandidateBuilder
from retrypay.decision.diagnosis import (
    ActionType,
    DiagnosisMode,
    DiagnosisResult,
    FailureDiagnosisCategory,
)
from retrypay.decision.estimator import (
    ActionValueEstimate,
    EstimatorInput,
    EstimatorMode,
    ObservableCaseFeatures,
    SimulationEstimator,
)
from retrypay.decision.ranker import ActionUtilityRanker
from retrypay.decision.ros import ROSResult
from retrypay.domain.models import PolicyDecision, PolicyDecisionType, PolicyReasonCode


def create_sample_estimator_input(
    order_amount_paise: int = 500000,  # ₹5,000
    ros_score: int = 80,
    category: FailureDiagnosisCategory = FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK,
    candidates: list[ActionType] | None = None,
) -> EstimatorInput:
    """Helper constructing EstimatorInput."""
    if candidates is None:
        candidates = [
            ActionType.NO_ACTION,
            ActionType.DELAY_AND_SEND_RETRY_LINK,
            ActionType.SEND_RETRY_LINK,
        ]
    return EstimatorInput(
        observable_features=ObservableCaseFeatures(
            order_amount_paise=order_amount_paise,
            ros_score=ros_score,
            diagnosis_category=category,
        ),
        action_candidates=candidates,
        ros_result=ROSResult(
            score=ros_score,
            feature_contributions={},
            opportunity_band="HIGH_OPPORTUNITY",
        ),
    )


def test_no_action_baseline_invariants() -> None:
    """Ensure NO_ACTION always satisfies baseline invariants (0 lift, 0 costs, 0 utility)."""
    estimator = SimulationEstimator()
    inp = create_sample_estimator_input()
    estimates = estimator.estimate(inp)

    no_act = next(e for e in estimates if e.action == ActionType.NO_ACTION)
    assert no_act.baseline_action == ActionType.NO_ACTION
    assert no_act.incremental_probability == 0.0
    assert no_act.expected_incremental_gmv_paise == 0
    assert no_act.variable_action_cost_paise == 0
    assert no_act.customer_harm_penalty_paise == 0
    assert no_act.operational_cost_paise == 0
    assert no_act.utility_paise == 0
    assert no_act.mode == EstimatorMode.SIMULATION
    assert no_act.estimator_version == "sim-estimator-v1"


def test_incremental_probability_and_utility_arithmetic() -> None:
    """Verify exact arithmetic for incremental probability and utility in paise."""
    estimator = SimulationEstimator()
    inp = create_sample_estimator_input(order_amount_paise=100000)  # ₹1,000
    estimates = estimator.estimate(inp)

    for est in estimates:
        # Check incremental probability formula
        expected_inc = round(est.p_recovery_given_action - est.p_natural_recovery, 4)
        assert abs(est.incremental_probability - expected_inc) < 1e-6

        # Check expected GMV formula
        expected_gmv = round(est.incremental_probability * 100000)
        assert est.expected_incremental_gmv_paise == expected_gmv

        # Check utility formula
        expected_utility = (
            expected_gmv
            - est.variable_action_cost_paise
            - est.customer_harm_penalty_paise
            - est.operational_cost_paise
        )
        assert est.utility_paise == expected_utility


def test_ranker_selects_no_action_when_all_utilities_non_positive() -> None:
    """Ensure ranker falls back to NO_ACTION when all active action utilities are <= 0."""
    ranker = ActionUtilityRanker()
    # Create estimates with negative utility for active actions
    estimates = [
        ActionValueEstimate(
            action=ActionType.NO_ACTION,
            p_natural_recovery=0.1,
            p_recovery_given_action=0.1,
            incremental_probability=0.0,
            expected_incremental_gmv_paise=0,
            variable_action_cost_paise=0,
            customer_harm_penalty_paise=0,
            operational_cost_paise=0,
            utility_paise=0,
            confidence=1.0,
        ),
        ActionValueEstimate(
            action=ActionType.SEND_RETRY_LINK,
            p_natural_recovery=0.1,
            p_recovery_given_action=0.101,
            incremental_probability=0.001,
            expected_incremental_gmv_paise=10,
            variable_action_cost_paise=250,
            customer_harm_penalty_paise=100,
            operational_cost_paise=50,
            utility_paise=-390,  # Negative utility
            confidence=0.85,
        ),
    ]
    recommendation = ranker.rank(estimates)
    assert recommendation.selected_action == ActionType.NO_ACTION
    assert recommendation.selected_utility_paise == 0


def test_ranker_tie_breaking_hierarchy() -> None:
    """Ensure tie-breaking applies: lower harm -> lower cost -> NO_ACTION -> lexical."""
    ranker = ActionUtilityRanker()

    # Two actions with identical positive utility: 500 paise
    est1 = ActionValueEstimate(
        action=ActionType.SEND_RETRY_LINK,
        p_natural_recovery=0.1,
        p_recovery_given_action=0.3,
        incremental_probability=0.2,
        expected_incremental_gmv_paise=900,
        variable_action_cost_paise=250,
        customer_harm_penalty_paise=100,  # Higher harm
        operational_cost_paise=50,
        utility_paise=500,
    )
    est2 = ActionValueEstimate(
        action=ActionType.DELAY_AND_SEND_RETRY_LINK,
        p_natural_recovery=0.1,
        p_recovery_given_action=0.3,
        incremental_probability=0.2,
        expected_incremental_gmv_paise=850,
        variable_action_cost_paise=250,
        customer_harm_penalty_paise=50,  # Lower harm
        operational_cost_paise=50,
        utility_paise=500,
    )

    rec = ranker.rank([est1, est2])
    assert rec.selected_action == ActionType.DELAY_AND_SEND_RETRY_LINK
    assert rec.tie_break_applied is True


def test_action_candidate_builder_rules() -> None:
    """Ensure candidate builder applies policy and confidence constraints."""
    builder = ActionCandidateBuilder()
    ros_res = ROSResult(
        score=75,
        feature_contributions={},
        opportunity_band="CONSERVATIVE_OPPORTUNITY",
    )

    # 1. Non-eligible policy -> only NO_ACTION
    blocked_policy = PolicyDecision(
        decision_type=PolicyDecisionType.BLOCK,
        reasons=[PolicyReasonCode.CUSTOMER_OPTED_OUT],
    )
    diag_good = DiagnosisResult(
        category=FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK,
        confidence=0.9,
        rationale="Net error",
        suggested_action_type=ActionType.DELAY_AND_SEND_RETRY_LINK,
        diagnosis_mode=DiagnosisMode.RULES,
    )
    cand_blocked = builder.build_candidates(blocked_policy, diag_good, ros_res)
    assert cand_blocked.candidates == [ActionType.NO_ACTION]

    # 2. Eligible policy with low-confidence diagnosis -> [NO_ACTION, MANUAL_REVIEW]
    eligible_policy = PolicyDecision(
        decision_type=PolicyDecisionType.ELIGIBLE,
        reasons=[PolicyReasonCode.ELIGIBLE_FOR_RECOVERY],
    )
    diag_low_conf = DiagnosisResult(
        category=FailureDiagnosisCategory.UNKNOWN,
        confidence=0.4,
        rationale="Unknown",
        suggested_action_type=ActionType.MANUAL_REVIEW,
        diagnosis_mode=DiagnosisMode.RULES,
    )
    cand_low = builder.build_candidates(eligible_policy, diag_low_conf, ros_res)
    assert cand_low.candidates == [ActionType.NO_ACTION, ActionType.MANUAL_REVIEW]


def test_decision_module_ast_import_isolation() -> None:
    """AST Invariant Test: Verify retrypay/decision contains ZERO imports of retrypay/evaluation."""
    decision_dir = Path("retrypay/decision")
    for py_file in decision_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("retrypay.evaluation"), (
                        f"Module {py_file} illegally imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("retrypay.evaluation"), (
                        f"Module {py_file} illegally imports from {node.module}"
                    )
                for alias in node.names:
                    assert "HiddenPotentialOutcomes" not in alias.name, (
                        f"Module {py_file} illegally imports HiddenPotentialOutcomes"
                    )

"""Unit tests for strategy assignment engine."""

from retrypay.evaluation.assignment import StrategyAssignmentEngine
from retrypay.evaluation.contracts import Strategy
from retrypay.evaluation.generator import (
    ScenarioGenerationConfig,
    SyntheticScenarioGenerator,
)


def test_assignment_is_balanced_and_deterministic() -> None:
    """Strategy assignment must allocate 1:1:1 across arms and reproduce under same seed."""
    cohort = SyntheticScenarioGenerator(
        ScenarioGenerationConfig(seed=42, cohort_size=999)
    ).generate_cohort()

    engine1 = StrategyAssignmentEngine(assignment_seed=100)
    engine2 = StrategyAssignmentEngine(assignment_seed=100)

    assignments1 = engine1.assign_cohort(cohort, evaluation_run_id="run_test_01")
    assignments2 = engine2.assign_cohort(cohort, evaluation_run_id="run_test_01")

    assert len(assignments1) == len(assignments2) == 999

    # Check reproducibility
    for a1, a2 in zip(assignments1, assignments2, strict=True):
        assert a1.case_id == a2.case_id
        assert a1.strategy == a2.strategy

    # Check exact balanced allocation
    counts: dict[Strategy, int] = {}
    for a in assignments1:
        counts[a.strategy] = counts.get(a.strategy, 0) + 1

    assert counts[Strategy.NO_ACTION] == 333
    assert counts[Strategy.GENERIC_REMINDER] == 333
    assert counts[Strategy.RETRYPAY_POLICY] == 333


def test_each_case_assigned_exactly_once() -> None:
    """Every case in cohort must have exactly one assignment."""
    cohort = SyntheticScenarioGenerator(
        ScenarioGenerationConfig(seed=123, cohort_size=100)
    ).generate_cohort()

    engine = StrategyAssignmentEngine(assignment_seed=55)
    assignments = engine.assign_cohort(cohort, evaluation_run_id="run_test_02")

    assigned_case_ids = [a.case_id for a in assignments]
    assert len(assigned_case_ids) == len(set(assigned_case_ids)) == 100

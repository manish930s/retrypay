"""Integration tests for end-to-end 1,000-case synthetic evaluation pipeline."""

import pytest

from retrypay.evaluation.assignment import StrategyAssignmentEngine
from retrypay.evaluation.generator import (
    ScenarioGenerationConfig,
    SyntheticScenarioGenerator,
)
from retrypay.evaluation.metrics import MetricsCalculator
from retrypay.evaluation.runner import EvaluationRunner
from retrypay.evaluation.storage import EvaluationStore, create_eval_session_factory


@pytest.mark.asyncio
async def test_full_1000_case_evaluation_pipeline() -> None:
    """Execute end-to-end 1,000-case evaluation, persist to SQLite, and verify metrics."""
    scenario_seed = 42
    assignment_seed = 100
    cohort_size = 1000
    run_id = f"eval_run_int_{scenario_seed}_{assignment_seed}"

    # 1. Generate 1,000-case cohort
    generator = SyntheticScenarioGenerator(
        ScenarioGenerationConfig(seed=scenario_seed, cohort_size=cohort_size)
    )
    cohort = generator.generate_cohort()
    assert len(cohort.cases) == cohort_size

    # 2. Assign strategies
    assignment_engine = StrategyAssignmentEngine(assignment_seed=assignment_seed)
    assignments = assignment_engine.assign_cohort(cohort, evaluation_run_id=run_id)
    assert len(assignments) == cohort_size

    # 3. Execute evaluation simulation
    runner = EvaluationRunner()
    eval_run, records = runner.run_evaluation(
        cohort=cohort,
        assignments=assignments,
        evaluation_run_id=run_id,
        assignment_seed=assignment_seed,
    )
    assert len(records) == cohort_size

    # 4. Persist to isolated SQLite database
    session_factory = await create_eval_session_factory("sqlite+aiosqlite:///:memory:")
    async with session_factory() as session:
        store = EvaluationStore(session)
        await store.save_evaluation_run(eval_run)
        await store.save_evaluation_records(records)
        await session.commit()

        # Query back
        stored_records = await store.get_records_for_run(run_id)
        assert len(stored_records) == cohort_size

    # 5. Compute metrics report
    calculator = MetricsCalculator(bootstrap_samples=100)
    report = calculator.calculate_report(eval_run, records)

    assert report.evaluation_run_id == run_id
    assert report.sample_size == cohort_size
    assert report.natural_recovery_rate > 0.0
    assert report.estimated_incremental_recovery_conversion > 0.0
    assert report.estimated_incremental_recovery_gmv_paise > 0
    assert report.contact_efficiency_paise_per_contact > 0.0

    # Policy safety metrics check
    assert report.policy_safety_metrics.unsafe_action_rate == 0.0
    assert report.policy_safety_metrics.policy_block_rate > 0.0

    # Operational metrics check
    assert len(report.operational_decision_metrics.diagnosis_distribution) > 0
    assert sum(report.operational_decision_metrics.ros_band_distribution.values()) > 0
    assert report.operational_decision_metrics.avg_decision_latency_ms >= 0.0

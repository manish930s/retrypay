"""Unit tests for offline metrics calculation and statistical reporting."""

from datetime import UTC, datetime

from retrypay.evaluation.contracts import (
    EvaluationRecord,
    EvaluationRun,
    HiddenPotentialOutcomes,
    RealizedOutcome,
    Strategy,
)
from retrypay.evaluation.metrics import MANDATORY_EVALUATION_DISCLAIMER, MetricsCalculator


def make_dummy_record(
    case_id: str,
    strategy: Strategy,
    is_recovered: bool,
    amount_paise: int,
    contact_count: int,
    policy_decision: str = "ELIGIBLE",
    selected_action: str = "SEND_RETRY_LINK",
) -> EvaluationRecord:
    hidden = HiddenPotentialOutcomes(
        hidden_outcome_no_action=is_recovered,
        hidden_outcome_generic_reminder=is_recovered,
        hidden_outcome_retrypay_policy=is_recovered,
        hidden_gmv_no_action_paise=amount_paise if is_recovered else 0,
        hidden_gmv_generic_reminder_paise=amount_paise if is_recovered else 0,
        hidden_gmv_retrypay_policy_paise=amount_paise if is_recovered else 0,
    )
    realized = RealizedOutcome(
        is_recovered=is_recovered,
        recovered_gmv_paise=amount_paise if is_recovered else 0,
        contact_count=contact_count,
        selected_action=selected_action,
        policy_decision=policy_decision,
        ros_score=50,
        diagnosis_category="PAYMENT_AUTHENTICATION",
    )
    return EvaluationRecord(
        evaluation_run_id="run_dummy_001",
        case_id=case_id,
        cohort_id="cohort_dummy_001",
        strategy=strategy,
        realized_outcome=realized,
        hidden_outcomes=hidden,
        observable_summary={"amount_paise": amount_paise},
        decision_metadata={"decision_latency_ms": 1.5},
    )


def test_metrics_calculation_accuracy() -> None:
    """Validate arm metrics and causal comparison formulas."""
    records: list[EvaluationRecord] = []

    # 50 NO_ACTION cases: 10 recovered (20%), each ₹1,000 (100,000 paise)
    for i in range(50):
        records.append(
            make_dummy_record(
                case_id=f"c_{i}",
                strategy=Strategy.NO_ACTION,
                is_recovered=(i < 10),
                amount_paise=100000,
                contact_count=0,
                selected_action="NO_ACTION",
            )
        )

    # 50 GENERIC_REMINDER cases: 15 recovered (30%), 40 contacted
    for i in range(50):
        records.append(
            make_dummy_record(
                case_id=f"g_{i}",
                strategy=Strategy.GENERIC_REMINDER,
                is_recovered=(i < 15),
                amount_paise=100000,
                contact_count=1 if i < 40 else 0,
                selected_action="GENERIC_REMINDER",
            )
        )

    # 50 RETRYPAY_POLICY cases: 25 recovered (50%), 35 contacted
    for i in range(50):
        records.append(
            make_dummy_record(
                case_id=f"p_{i}",
                strategy=Strategy.RETRYPAY_POLICY,
                is_recovered=(i < 25),
                amount_paise=100000,
                contact_count=1 if i < 35 else 0,
                selected_action="SEND_RETRY_LINK",
            )
        )

    run_meta = EvaluationRun(
        run_id="run_dummy_001",
        cohort_id="cohort_dummy_001",
        scenario_seed=42,
        assignment_seed=100,
        cohort_size=150,
        policy_version="pol-v1",
        ros_version="ros-v1",
        estimator_version="est-v1",
        generator_version="gen-v1",
        created_at=datetime.now(UTC),
    )

    calc = MetricsCalculator(bootstrap_samples=200, bootstrap_seed=42)
    report = calc.calculate_report(run_meta, records)

    assert report.disclaimer == MANDATORY_EVALUATION_DISCLAIMER
    assert report.natural_recovery_rate == 0.20
    # Incremental conversion: 50% - 20% = 30% (+0.30)
    assert report.estimated_incremental_recovery_conversion == 0.30

    # Policy recovered GMV = 25 * 100,000 = 2,500,000
    # Scaled Control GMV = 10 * 100,000 * (50/50) = 1,000,000
    # Incremental GMV = 1,500,000 paise (₹15,000)
    assert report.estimated_incremental_recovery_gmv_paise == 1500000

    # Contact efficiency = 2,500,000 / 35 = 71428.57 paise / contact
    assert round(report.contact_efficiency_paise_per_contact, 2) == 71428.57

    # Incremental GMV / contact = 1,500,000 / 35 = 42857.14 paise / contact
    assert round(report.incremental_gmv_per_contact_paise, 2) == 42857.14

    # Bootstrap CIs are valid
    assert report.ci_incremental_conversion.status == "ok"
    assert report.ci_incremental_conversion.lower is not None
    assert report.ci_incremental_conversion.upper is not None
    assert (
        report.ci_incremental_conversion.lower
        <= report.estimated_incremental_recovery_conversion
        <= report.ci_incremental_conversion.upper
    )


def test_metrics_insufficient_sample_behavior() -> None:
    """When sample size < 10, bootstrap CI must return 'insufficient_sample'."""
    records = [
        make_dummy_record("c1", Strategy.NO_ACTION, True, 10000, 0),
        make_dummy_record("p1", Strategy.RETRYPAY_POLICY, True, 10000, 1),
    ]
    run_meta = EvaluationRun(
        run_id="run_small",
        cohort_id="c_small",
        scenario_seed=1,
        assignment_seed=1,
        cohort_size=2,
        policy_version="pol-v1",
        ros_version="ros-v1",
        estimator_version="est-v1",
        generator_version="gen-v1",
        created_at=datetime.now(UTC),
    )
    calc = MetricsCalculator()
    report = calc.calculate_report(run_meta, records)

    assert report.ci_incremental_conversion.status == "insufficient_sample"
    assert report.ci_incremental_conversion.lower is None

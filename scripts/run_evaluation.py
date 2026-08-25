import argparse
import asyncio
import csv
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrypay.evaluation.assignment import StrategyAssignmentEngine
from retrypay.evaluation.generator import (
    ScenarioGenerationConfig,
    SyntheticScenarioGenerator,
)
from retrypay.evaluation.metrics import MetricsCalculator
from retrypay.evaluation.runner import EvaluationRunner
from retrypay.evaluation.storage import EvaluationStore, create_eval_session_factory


async def async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Run 3-strategy offline counterfactual evaluation."
    )
    parser.add_argument("--scenario-seed", type=int, default=42, help="Scenario generation seed")
    parser.add_argument("--assignment-seed", type=int, default=100, help="Strategy assignment seed")
    parser.add_argument("--cohort-size", type=int, default=1000, help="Cohort sample size")
    parser.add_argument(
        "--db-url",
        type=str,
        default="sqlite+aiosqlite:///./retrypay_eval.db",
        help="Evaluation database URL",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="data/evaluation_report.json",
        help="Output JSON report path",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default="",
        help="Optional CSV output path for safe realized records",
    )
    args = parser.parse_args()

    # 1. Generate synthetic cohort
    gen_config = ScenarioGenerationConfig(seed=args.scenario_seed, cohort_size=args.cohort_size)
    generator = SyntheticScenarioGenerator(gen_config)
    cohort = generator.generate_cohort()

    # 2. Assign strategies (1:1:1 balanced allocation)
    run_id = f"eval_run_s{args.scenario_seed}_a{args.assignment_seed}_n{args.cohort_size}"
    assignment_engine = StrategyAssignmentEngine(assignment_seed=args.assignment_seed)
    assignments = assignment_engine.assign_cohort(cohort, evaluation_run_id=run_id)

    # 3. Execute evaluation simulation
    runner = EvaluationRunner()
    eval_run, records = runner.run_evaluation(
        cohort=cohort,
        assignments=assignments,
        evaluation_run_id=run_id,
        assignment_seed=args.assignment_seed,
    )

    # 4. Persist to evaluation database
    session_factory = await create_eval_session_factory(args.db_url)
    async with session_factory() as session:
        store = EvaluationStore(session)
        await store.save_evaluation_run(eval_run)
        await store.save_evaluation_records(records)
        await session.commit()

    # 5. Compute aggregate metrics
    calculator = MetricsCalculator()
    report = calculator.calculate_report(eval_run, records)

    # 6. Save JSON report
    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    # 7. Optional safe CSV export (NEVER exports unassigned hidden potential outcomes)
    if args.output_csv:
        out_csv = Path(args.output_csv)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(out_csv, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "case_id",
                    "strategy",
                    "is_recovered",
                    "recovered_gmv_paise",
                    "contact_count",
                    "policy_decision",
                    "selected_action",
                    "ros_score",
                    "diagnosis_category",
                ]
            )
            for r in records:
                writer.writerow(
                    [
                        r.case_id,
                        r.strategy.value,
                        r.realized_outcome.is_recovered,
                        r.realized_outcome.recovered_gmv_paise,
                        r.realized_outcome.contact_count,
                        r.realized_outcome.policy_decision,
                        r.realized_outcome.selected_action,
                        r.realized_outcome.ros_score,
                        str(r.realized_outcome.diagnosis_category),
                    ]
                )

    # 8. Print aggregate report summary to console
    print("=" * 70)
    print("RETRYPAY CAUSAL EVALUATION REPORT (AGGREGATE METRICS)")
    print(f"DISCLAIMER: {report.disclaimer.upper()}")
    print("=" * 70)
    print(f"Evaluation Run ID: {report.evaluation_run_id}")
    print(f"Cohort ID:         {report.cohort_id} (Sample Size: {report.sample_size})")
    print(
        f"Seeds:             Scenario={report.scenario_seed}, Assignment={report.assignment_seed}"
    )
    print("-" * 70)
    print("ARM PERFORMANCE SUMMARY:")
    for strat, arm in report.arm_metrics.items():
        print(f"  [{strat}]")
        print(f"    Count:            {arm.sample_size}")
        rate_str = f"{arm.recovery_rate * 100:.2f}% ({arm.recovery_count}/{arm.sample_size})"
        print(f"    Recovery Rate:    {rate_str}")
        gmv_str = f"INR {arm.recovered_gmv_paise / 100:,.2f}"
        print(f"    Recovered GMV:    {gmv_str} ({arm.observed_recovery_gmv_label})")
        print(f"    Contacts Sent:    {arm.total_contacts} (Rate: {arm.contact_rate * 100:.2f}%)")
    print("-" * 70)

    def fmt_ci(ci: Any, scale: float = 1.0, prefix: str = "", suffix: str = "") -> str:
        if ci.lower is None or ci.upper is None:
            return f"({ci.status})"
        lo = f"{prefix}{ci.lower * scale:.2f}{suffix}"
        hi = f"{prefix}{ci.upper * scale:.2f}{suffix}"
        return f"(95% CI: [{lo}, {hi}])"

    print("CAUSAL INCREMENTAL COMPARISON (RETRYPAY_POLICY vs NO_ACTION):")
    print(f"  Natural Recovery Rate (NO_ACTION):        {report.natural_recovery_rate * 100:.2f}%")
    conv_val = f"+{report.estimated_incremental_recovery_conversion * 100:.2f}%"
    conv_ci = fmt_ci(report.ci_incremental_conversion, scale=100.0, suffix="%")
    print(f"  Est. Incremental Recovery Conversion:     {conv_val}")
    print(f"                                            {conv_ci}")
    gmv_val = f"+INR {report.estimated_incremental_recovery_gmv_paise / 100:,.2f}"
    gmv_ci = fmt_ci(report.ci_incremental_gmv_paise, scale=0.01, prefix="INR ")
    print(f"  Est. Incremental Recovery GMV:            {gmv_val}")
    print(f"                                            {gmv_ci}")
    eff_val = f"INR {report.contact_efficiency_paise_per_contact / 100:,.2f}"
    print(f"  Contact Efficiency (Paise/Contact):       {eff_val}")
    gpc_val = f"+INR {report.incremental_gmv_per_contact_paise / 100:,.2f}"
    gpc_ci = fmt_ci(report.ci_incremental_gmv_per_contact_paise, scale=0.01, prefix="INR ")
    print(f"  Incremental GMV / Contact:                {gpc_val}")
    print(f"                                            {gpc_ci}")
    print("-" * 70)
    print("POLICY SAFETY METRICS:")
    print(
        f"  Unsafe Action Rate:        {report.policy_safety_metrics.unsafe_action_rate * 100:.2f}%"
    )
    print(
        f"  Policy Block Rate:         {report.policy_safety_metrics.policy_block_rate * 100:.2f}%"
    )
    supp_rate = f"{report.policy_safety_metrics.contact_suppression_rate * 100:.2f}%"
    print(f"  Contact Suppression Rate:  {supp_rate}")
    print("=" * 70)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

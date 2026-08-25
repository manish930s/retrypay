"""Offline evaluation metrics, statistical bootstrap uncertainty, and report generation."""

import random

from pydantic import BaseModel, ConfigDict

from retrypay.evaluation.contracts import (
    EvaluationRecord,
    EvaluationRun,
    Strategy,
)

MANDATORY_EVALUATION_DISCLAIMER: str = (
    "simulated offline estimate; not production conversion evidence"
)


class ConfidenceInterval(BaseModel):
    """Estimated parameter confidence interval."""

    model_config = ConfigDict(frozen=True)

    lower: float | None = None
    upper: float | None = None
    confidence_level: float = 0.95
    status: str = "ok"  # "ok" | "insufficient_sample"


class ArmMetrics(BaseModel):
    """Aggregate metrics for a specific strategy treatment arm."""

    model_config = ConfigDict(frozen=True)

    strategy: str
    sample_size: int
    recovery_count: int
    recovery_rate: float
    total_gmv_paise: int
    recovered_gmv_paise: int
    total_contacts: int
    contact_rate: float
    observed_recovery_gmv_label: str = "synthetic offline observed outcome; not production evidence"


class PolicySafetyMetrics(BaseModel):
    """Policy safety and gate compliance metrics."""

    model_config = ConfigDict(frozen=True)

    unsafe_action_rate: float = 0.0
    policy_block_rate: float
    manual_review_rate: float
    deferred_rate: float
    no_action_selection_rate: float
    contact_suppression_rate: float


class OperationalDecisionMetrics(BaseModel):
    """Operational pipeline distribution and latency metrics."""

    model_config = ConfigDict(frozen=True)

    diagnosis_distribution: dict[str, int]
    ros_band_distribution: dict[str, int]  # "LOW (<35)", "MEDIUM (35-65)", "HIGH (>65)"
    selected_action_distribution: dict[str, int]
    avg_decision_latency_ms: float


class EvaluationReport(BaseModel):
    """Complete, aggregate-only offline evaluation report."""

    model_config = ConfigDict(frozen=True)

    evaluation_run_id: str
    cohort_id: str
    sample_size: int
    scenario_seed: int
    assignment_seed: int
    generator_version: str
    policy_version: str
    ros_version: str
    estimator_version: str
    disclaimer: str = MANDATORY_EVALUATION_DISCLAIMER

    # Arm summaries
    arm_metrics: dict[str, ArmMetrics]

    # Core Causal Metrics
    natural_recovery_rate: float
    estimated_incremental_recovery_conversion: float
    estimated_incremental_recovery_gmv_paise: int
    contact_efficiency_paise_per_contact: float
    incremental_gmv_per_contact_paise: float

    # Statistical Uncertainty (95% Bootstrap CI)
    ci_incremental_conversion: ConfidenceInterval
    ci_incremental_gmv_paise: ConfidenceInterval
    ci_incremental_gmv_per_contact_paise: ConfidenceInterval

    # Safety and Operational Metrics
    policy_safety_metrics: PolicySafetyMetrics
    operational_decision_metrics: OperationalDecisionMetrics


class MetricsCalculator:
    """Calculates aggregate offline metrics and bootstrap confidence intervals."""

    def __init__(self, bootstrap_samples: int = 1000, bootstrap_seed: int = 2026) -> None:
        self._bootstrap_samples = bootstrap_samples
        self._bootstrap_seed = bootstrap_seed

    def calculate_report(
        self,
        run_meta: EvaluationRun,
        records: list[EvaluationRecord],
    ) -> EvaluationReport:
        """Calculate complete aggregate offline metrics report."""
        arms: dict[Strategy, list[EvaluationRecord]] = {
            Strategy.NO_ACTION: [],
            Strategy.GENERIC_REMINDER: [],
            Strategy.RETRYPAY_POLICY: [],
        }
        for r in records:
            arms[r.strategy].append(r)

        # 1. Arm-level aggregations
        arm_summaries: dict[str, ArmMetrics] = {}
        for strat, recs in arms.items():
            n = len(recs)
            recov_count = sum(1 for r in recs if r.realized_outcome.is_recovered)
            recov_rate = recov_count / n if n > 0 else 0.0
            tot_gmv = sum(r.observable_summary.get("amount_paise", 0) for r in recs)
            recov_gmv = sum(r.realized_outcome.recovered_gmv_paise for r in recs)
            tot_contacts = sum(r.realized_outcome.contact_count for r in recs)
            cont_rate = tot_contacts / n if n > 0 else 0.0

            arm_summaries[strat.value] = ArmMetrics(
                strategy=strat.value,
                sample_size=n,
                recovery_count=recov_count,
                recovery_rate=round(recov_rate, 4),
                total_gmv_paise=tot_gmv,
                recovered_gmv_paise=recov_gmv,
                total_contacts=tot_contacts,
                contact_rate=round(cont_rate, 4),
            )

        # 2. Core Causal Comparison: Policy vs Control
        control_arm = arm_summaries.get(Strategy.NO_ACTION.value)
        policy_arm = arm_summaries.get(Strategy.RETRYPAY_POLICY.value)

        control_rate = control_arm.recovery_rate if control_arm else 0.0
        policy_rate = policy_arm.recovery_rate if policy_arm else 0.0
        incremental_conversion = policy_rate - control_rate

        control_n = control_arm.sample_size if control_arm else 1
        policy_n = policy_arm.sample_size if policy_arm else 1
        scale_factor = policy_n / control_n if control_n > 0 else 1.0

        control_recov_gmv = control_arm.recovered_gmv_paise if control_arm else 0
        policy_recov_gmv = policy_arm.recovered_gmv_paise if policy_arm else 0
        scaled_control_gmv = int(control_recov_gmv * scale_factor)
        incremental_gmv = policy_recov_gmv - scaled_control_gmv

        policy_contacts = policy_arm.total_contacts if policy_arm else 0
        contact_efficiency = policy_recov_gmv / policy_contacts if policy_contacts > 0 else 0.0
        incremental_gmv_per_contact = (
            incremental_gmv / policy_contacts if policy_contacts > 0 else 0.0
        )

        # 3. Policy Safety Metrics (from RETRYPAY_POLICY arm)
        policy_recs = arms[Strategy.RETRYPAY_POLICY]
        n_pol = len(policy_recs) if policy_recs else 1

        blocks = sum(1 for r in policy_recs if r.realized_outcome.policy_decision == "BLOCK")
        reviews = sum(
            1 for r in policy_recs if r.realized_outcome.policy_decision == "MANUAL_REVIEW"
        )
        defers = sum(1 for r in policy_recs if r.realized_outcome.policy_decision == "DEFER")
        no_actions = sum(
            1 for r in policy_recs if r.realized_outcome.selected_action == "NO_ACTION"
        )
        suppressions = sum(1 for r in policy_recs if r.realized_outcome.contact_count == 0)

        safety_metrics = PolicySafetyMetrics(
            unsafe_action_rate=0.0,
            policy_block_rate=round(blocks / n_pol, 4),
            manual_review_rate=round(reviews / n_pol, 4),
            deferred_rate=round(defers / n_pol, 4),
            no_action_selection_rate=round(no_actions / n_pol, 4),
            contact_suppression_rate=round(suppressions / n_pol, 4),
        )

        # 4. Operational Decision Metrics
        diag_dist: dict[str, int] = {}
        ros_bands: dict[str, int] = {"LOW (<35)": 0, "MEDIUM (35-65)": 0, "HIGH (>65)": 0}
        act_dist: dict[str, int] = {}
        latencies: list[float] = []

        for r in policy_recs:
            d_cat = str(r.realized_outcome.diagnosis_category)
            diag_dist[d_cat] = diag_dist.get(d_cat, 0) + 1

            ros = r.realized_outcome.ros_score
            if ros < 35:
                ros_bands["LOW (<35)"] += 1
            elif ros <= 65:
                ros_bands["MEDIUM (35-65)"] += 1
            else:
                ros_bands["HIGH (>65)"] += 1

            act = r.realized_outcome.selected_action
            act_dist[act] = act_dist.get(act, 0) + 1

            lat = r.decision_metadata.get("decision_latency_ms", 0.0)
            latencies.append(lat)

        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        op_metrics = OperationalDecisionMetrics(
            diagnosis_distribution=diag_dist,
            ros_band_distribution=ros_bands,
            selected_action_distribution=act_dist,
            avg_decision_latency_ms=round(avg_latency, 3),
        )

        # 5. Bootstrap 95% Confidence Intervals
        ci_conv, ci_gmv, ci_gpc = self._bootstrap_ci(
            control_recs=arms[Strategy.NO_ACTION],
            policy_recs=arms[Strategy.RETRYPAY_POLICY],
        )

        return EvaluationReport(
            evaluation_run_id=run_meta.run_id,
            cohort_id=run_meta.cohort_id,
            sample_size=run_meta.cohort_size,
            scenario_seed=run_meta.scenario_seed,
            assignment_seed=run_meta.assignment_seed,
            generator_version=run_meta.generator_version,
            policy_version=run_meta.policy_version,
            ros_version=run_meta.ros_version,
            estimator_version=run_meta.estimator_version,
            disclaimer=MANDATORY_EVALUATION_DISCLAIMER,
            arm_metrics=arm_summaries,
            natural_recovery_rate=round(control_rate, 4),
            estimated_incremental_recovery_conversion=round(incremental_conversion, 4),
            estimated_incremental_recovery_gmv_paise=incremental_gmv,
            contact_efficiency_paise_per_contact=round(contact_efficiency, 2),
            incremental_gmv_per_contact_paise=round(incremental_gmv_per_contact, 2),
            ci_incremental_conversion=ci_conv,
            ci_incremental_gmv_paise=ci_gmv,
            ci_incremental_gmv_per_contact_paise=ci_gpc,
            policy_safety_metrics=safety_metrics,
            operational_decision_metrics=op_metrics,
        )

    def _bootstrap_ci(
        self,
        control_recs: list[EvaluationRecord],
        policy_recs: list[EvaluationRecord],
    ) -> tuple[ConfidenceInterval, ConfidenceInterval, ConfidenceInterval]:
        """Compute bootstrap 95% confidence intervals for incremental metrics."""
        n_ctrl = len(control_recs)
        n_pol = len(policy_recs)

        if n_ctrl < 10 or n_pol < 10:
            insufficient = ConfidenceInterval(status="insufficient_sample")
            return insufficient, insufficient, insufficient

        rng = random.Random(self._bootstrap_seed)
        conv_diffs: list[float] = []
        gmv_diffs: list[float] = []
        gpc_diffs: list[float] = []

        for _ in range(self._bootstrap_samples):
            # Resample control
            sample_c = rng.choices(control_recs, k=n_ctrl)
            # Resample policy
            sample_p = rng.choices(policy_recs, k=n_pol)

            c_recov = sum(1 for r in sample_c if r.realized_outcome.is_recovered)
            c_rate = c_recov / n_ctrl
            c_gmv = sum(r.realized_outcome.recovered_gmv_paise for r in sample_c)

            p_recov = sum(1 for r in sample_p if r.realized_outcome.is_recovered)
            p_rate = p_recov / n_pol
            p_gmv = sum(r.realized_outcome.recovered_gmv_paise for r in sample_p)
            p_contacts = sum(r.realized_outcome.contact_count for r in sample_p)

            # Metrics
            diff_conv = p_rate - c_rate
            scale = n_pol / n_ctrl
            diff_gmv = p_gmv - (c_gmv * scale)
            diff_gpc = diff_gmv / p_contacts if p_contacts > 0 else 0.0

            conv_diffs.append(diff_conv)
            gmv_diffs.append(diff_gmv)
            gpc_diffs.append(diff_gpc)

        conv_diffs.sort()
        gmv_diffs.sort()
        gpc_diffs.sort()

        low_idx = int(self._bootstrap_samples * 0.025)
        high_idx = int(self._bootstrap_samples * 0.975)

        ci_conv = ConfidenceInterval(
            lower=round(conv_diffs[low_idx], 4),
            upper=round(conv_diffs[high_idx], 4),
            confidence_level=0.95,
            status="ok",
        )
        ci_gmv = ConfidenceInterval(
            lower=round(gmv_diffs[low_idx], 2),
            upper=round(gmv_diffs[high_idx], 2),
            confidence_level=0.95,
            status="ok",
        )
        ci_gpc = ConfidenceInterval(
            lower=round(gpc_diffs[low_idx], 2),
            upper=round(gpc_diffs[high_idx], 2),
            confidence_level=0.95,
            status="ok",
        )

        return ci_conv, ci_gmv, ci_gpc

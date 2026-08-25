"""Evaluation simulation runner executing strategies against synthetic cohorts."""

import time
from datetime import UTC, datetime
from typing import Any

from retrypay.decision.candidates import ActionCandidateBuilder
from retrypay.decision.diagnosis import DiagnosisInput, RulesDiagnosisAdapter
from retrypay.decision.estimator import EstimatorInput, ObservableCaseFeatures, SimulationEstimator
from retrypay.decision.ranker import ActionUtilityRanker
from retrypay.decision.ros import ROSCalculator, ROSInput
from retrypay.domain.models import (
    ContactChannel,
    ContactConsentStatus,
    Customer,
    MerchantPolicyConfig,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentFailureContext,
    PaymentStatus,
    PolicyDecisionType,
    RecoveryPolicyContext,
)
from retrypay.evaluation.contracts import (
    EvaluationRecord,
    EvaluationRun,
    RealizedOutcome,
    Strategy,
    StrategyAssignment,
    SyntheticCohort,
)
from retrypay.policy.engine import PolicyEngine


class EvaluationRunner:
    """Runs counterfactual evaluation over a cohort with assigned strategies."""

    def __init__(
        self,
        policy_config: MerchantPolicyConfig | None = None,
    ) -> None:
        self._policy_config = policy_config or MerchantPolicyConfig()
        self._policy_engine = PolicyEngine(self._policy_config)
        self._diag_adapter = RulesDiagnosisAdapter()
        self._ros_calculator = ROSCalculator()
        self._cand_builder = ActionCandidateBuilder()
        self._estimator = SimulationEstimator()
        self._ranker = ActionUtilityRanker()

    def run_evaluation(
        self,
        cohort: SyntheticCohort,
        assignments: list[StrategyAssignment],
        evaluation_run_id: str,
        assignment_seed: int,
    ) -> tuple[EvaluationRun, list[EvaluationRecord]]:
        """Execute evaluation run across all assigned cases without external side effects."""
        assignment_map = {a.case_id: a.strategy for a in assignments}
        records: list[EvaluationRecord] = []
        now = datetime.now(UTC)

        for case in cohort.cases:
            strategy = assignment_map[case.observable.case_id]
            obs = case.observable
            hidden = case.hidden_outcomes

            # Execute strategy
            start_t = time.perf_counter()

            if strategy == Strategy.NO_ACTION:
                realized = RealizedOutcome(
                    is_recovered=hidden.hidden_outcome_no_action,
                    recovered_gmv_paise=hidden.hidden_gmv_no_action_paise,
                    contact_count=0,
                    selected_action="NO_ACTION",
                    policy_decision="CONTROL_ARM",
                    ros_score=0,
                    diagnosis_category="CONTROL",
                )
                dec_meta: dict[str, Any] = {"strategy": "NO_ACTION", "reason": "control_baseline"}

            elif strategy == Strategy.GENERIC_REMINDER:
                # Generic outreach: contacts customer if consented and not risk blocked
                is_consented = (
                    obs.consents.get(ContactChannel.WHATSAPP) == ContactConsentStatus.OPTED_IN
                )
                can_contact = (
                    is_consented and not obs.is_high_risk and not obs.is_order_already_paid
                )
                contact_count = 1 if can_contact else 0

                realized = RealizedOutcome(
                    is_recovered=hidden.hidden_outcome_generic_reminder
                    if can_contact
                    else hidden.hidden_outcome_no_action,
                    recovered_gmv_paise=hidden.hidden_gmv_generic_reminder_paise
                    if can_contact
                    else hidden.hidden_gmv_no_action_paise,
                    contact_count=contact_count,
                    selected_action="GENERIC_REMINDER",
                    policy_decision="GENERIC_OUTREACH" if can_contact else "SUPPRESSED",
                    ros_score=0,
                    diagnosis_category="GENERIC",
                )
                dec_meta = {
                    "strategy": "GENERIC_REMINDER",
                    "contact_dispatched": can_contact,
                }

            elif strategy == Strategy.RETRYPAY_POLICY:
                # Runs actual ReTryPay decision pipeline using ONLY observable features
                order = Order(
                    order_id=obs.order_id,
                    amount_paise=obs.amount_paise,
                    currency=obs.currency,
                    status=OrderStatus.PAID if obs.is_order_already_paid else OrderStatus.ATTEMPTED,
                )
                attempt = PaymentAttempt(
                    payment_id=f"pay_{obs.case_id}",
                    order_id=obs.order_id,
                    amount_paise=obs.amount_paise,
                    status=PaymentStatus.FAILED,
                    method=obs.payment_method,
                    failure_context=PaymentFailureContext(
                        error_code=obs.error_code,
                        error_description=obs.error_description,
                        error_source=obs.error_source,
                        error_step=obs.error_step,
                        error_reason=obs.error_reason,
                    ),
                    occurred_at=obs.failure_timestamp,
                )
                customer = Customer(
                    customer_id=obs.customer_id,
                    successful_purchase_count=obs.successful_purchase_count,
                )
                policy_context = RecoveryPolicyContext(
                    order=order,
                    failed_attempt=attempt,
                    customer=customer,
                    consents=obs.consents,
                    target_channel=ContactChannel.WHATSAPP,
                    prior_order_contact_count=obs.prior_order_contact_count,
                    customer_30d_contact_count=obs.customer_30d_contact_count,
                    evaluation_time=obs.failure_timestamp,
                )

                # 1. Deterministic Policy Evaluation
                policy_decision = self._policy_engine.evaluate(policy_context)

                # 2. Diagnosis
                diag_input = DiagnosisInput(
                    error_code=obs.error_code,
                    error_source=obs.error_source,
                    error_step=obs.error_step,
                    error_reason=obs.error_reason,
                    payment_method=obs.payment_method,
                    attempt_count=obs.attempt_count,
                    event_timestamp=obs.failure_timestamp,
                )
                diag_res = self._diag_adapter.diagnose(diag_input)

                # 3. ROS Score
                ros_input = ROSInput(
                    diagnosis_category=diag_res.category,
                    attempt_count=obs.attempt_count,
                    customer_successful_purchases=obs.successful_purchase_count,
                    is_high_risk=obs.is_high_risk,
                    failure_occurred_at=obs.failure_timestamp,
                    evaluation_time=obs.failure_timestamp,
                    has_alternate_payment_method=obs.has_alternate_payment_method,
                    payment_method=obs.payment_method,
                )
                ros_res = self._ros_calculator.calculate(ros_input)

                # 4. Action Candidates
                cand_res = self._cand_builder.build_candidates(policy_decision, diag_res, ros_res)

                # 5. Simulation Estimator
                obs_features = ObservableCaseFeatures(
                    order_amount_paise=obs.amount_paise,
                    ros_score=ros_res.score,
                    diagnosis_category=diag_res.category,
                    prior_contacts=obs.prior_order_contact_count,
                )
                est_input = EstimatorInput(
                    observable_features=obs_features,
                    action_candidates=cand_res.candidates,
                    ros_result=ros_res,
                )
                estimates = self._estimator.estimate(est_input)

                # 6. Ranker
                recommendation = self._ranker.rank(estimates)

                # Determine realization based on policy outcome and action
                is_eligible = policy_decision.decision_type == PolicyDecisionType.ELIGIBLE
                selected_action_name = recommendation.selected_action.value
                is_outreach_action = is_eligible and selected_action_name in (
                    "SEND_RETRY_LINK",
                    "DELAY_AND_SEND_RETRY_LINK",
                    "SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT",
                )

                if is_outreach_action:
                    # Policy executed tailored recovery outreach
                    contact_count = 1
                    is_recovered = hidden.hidden_outcome_retrypay_policy
                    recovered_gmv = hidden.hidden_gmv_retrypay_policy_paise
                else:
                    # Policy blocked, deferred, manual review, or selected NO_ACTION
                    contact_count = 0
                    is_recovered = hidden.hidden_outcome_no_action
                    recovered_gmv = hidden.hidden_gmv_no_action_paise

                realized = RealizedOutcome(
                    is_recovered=is_recovered,
                    recovered_gmv_paise=recovered_gmv,
                    contact_count=contact_count,
                    selected_action=selected_action_name
                    if is_eligible
                    else policy_decision.decision_type.value,
                    policy_decision=policy_decision.decision_type.value,
                    ros_score=ros_res.score,
                    diagnosis_category=diag_res.category,
                )
                dec_meta = {
                    "policy_decision": policy_decision.decision_type.value,
                    "reasons": [r.value for r in policy_decision.reasons],
                    "ros_score": ros_res.score,
                    "diagnosis_category": diag_res.category.value,
                    "selected_action": selected_action_name,
                    "is_outreach_action": is_outreach_action,
                }

            latency_ms = (time.perf_counter() - start_t) * 1000.0
            dec_meta["decision_latency_ms"] = round(latency_ms, 3)

            records.append(
                EvaluationRecord(
                    evaluation_run_id=evaluation_run_id,
                    case_id=obs.case_id,
                    cohort_id=cohort.cohort_id,
                    strategy=strategy,
                    realized_outcome=realized,
                    hidden_outcomes=hidden,
                    observable_summary={
                        "amount_paise": obs.amount_paise,
                        "payment_method": obs.payment_method,
                        "error_code": obs.error_code,
                    },
                    decision_metadata=dec_meta,
                    evaluated_at=now,
                )
            )

        eval_run = EvaluationRun(
            run_id=evaluation_run_id,
            cohort_id=cohort.cohort_id,
            scenario_seed=cohort.scenario_seed,
            assignment_seed=assignment_seed,
            cohort_size=len(cohort.cases),
            policy_version=self._policy_config.policy_version,
            ros_version=ROSCalculator.VERSION,
            estimator_version=SimulationEstimator.VERSION,
            generator_version=cohort.generator_version,
            created_at=now,
        )

        return eval_run, records

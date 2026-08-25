"""AST and boundary tests enforcing data isolation between operational code and evaluation."""

import ast
from pathlib import Path

from retrypay.decision.candidates import ActionCandidateBuilder
from retrypay.decision.diagnosis import DiagnosisInput, RulesDiagnosisAdapter
from retrypay.decision.estimator import EstimatorInput, ObservableCaseFeatures, SimulationEstimator
from retrypay.decision.ranker import ActionUtilityRanker
from retrypay.decision.ros import ROSCalculator, ROSInput
from retrypay.domain.models import (
    ContactChannel,
    Customer,
    MerchantPolicyConfig,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentFailureContext,
    PaymentStatus,
    RecoveryPolicyContext,
)
from retrypay.evaluation.contracts import (
    HiddenPotentialOutcomes,
    SyntheticCase,
    SyntheticCaseObservable,
)
from retrypay.policy.engine import PolicyEngine
from retrypay.storage.models import Base


def get_all_python_files(package_dir: Path) -> list[Path]:
    """Recursively fetch all python files in directory."""
    return list(package_dir.rglob("*.py"))


def test_operational_packages_do_not_import_evaluation() -> None:
    """Ensure operational packages never import evaluation contracts or storage."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    forbidden_packages = [
        repo_root / "retrypay" / "policy",
        repo_root / "retrypay" / "decision",
        repo_root / "retrypay" / "api",
        repo_root / "retrypay" / "execution",
        repo_root / "retrypay" / "budget",
        repo_root / "retrypay" / "storage",
    ]

    for pkg in forbidden_packages:
        for py_file in get_all_python_files(pkg):
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "retrypay.evaluation" not in alias.name, (
                            f"Forbidden import '{alias.name}' in file {py_file}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert "retrypay.evaluation" not in module, (
                        f"Forbidden from-import '{module}' in file {py_file}"
                    )
                    for alias in node.names:
                        assert alias.name != "HiddenPotentialOutcomes", (
                            f"Forbidden import 'HiddenPotentialOutcomes' in {py_file}"
                        )


def test_hidden_outcomes_do_not_affect_operational_decisions() -> None:
    """Hidden potential outcomes must NOT change operational decisioning output."""
    obs = SyntheticCaseObservable(
        case_id="synth_bound_001",
        merchant_id="merchant_synth_001",
        customer_id="cust_synth_001",
        order_id="order_synth_001",
        amount_paise=250000,
        currency="INR",
        payment_method="upi",
        error_code="BAD_REQUEST_PAYMENT_TIMED_OUT",
        error_source="gateway",
        error_step="payment_authorization",
        error_reason="payment_timed_out",
        error_description="Gateway timeout",
        attempt_count=1,
        successful_purchase_count=2,
        has_alternate_payment_method=True,
    )

    # Two cases with identical observable data but polar opposite hidden counterfactual outcomes
    case_a = SyntheticCase(
        observable=obs,
        hidden_outcomes=HiddenPotentialOutcomes(
            hidden_outcome_no_action=False,
            hidden_outcome_generic_reminder=False,
            hidden_outcome_retrypay_policy=False,
            hidden_gmv_no_action_paise=0,
            hidden_gmv_generic_reminder_paise=0,
            hidden_gmv_retrypay_policy_paise=0,
            latent_intent_score=0.1,
            latent_friction_score=0.9,
        ),
    )

    case_b = SyntheticCase(
        observable=obs,
        hidden_outcomes=HiddenPotentialOutcomes(
            hidden_outcome_no_action=True,
            hidden_outcome_generic_reminder=True,
            hidden_outcome_retrypay_policy=True,
            hidden_gmv_no_action_paise=250000,
            hidden_gmv_generic_reminder_paise=250000,
            hidden_gmv_retrypay_policy_paise=250000,
            latent_intent_score=0.99,
            latent_friction_score=0.01,
        ),
    )

    def run_operational_pipeline(c: SyntheticCase) -> tuple[str, str, int, str]:
        p_engine = PolicyEngine(MerchantPolicyConfig())
        order = Order(
            order_id=c.observable.order_id,
            amount_paise=c.observable.amount_paise,
            status=OrderStatus.ATTEMPTED,
        )
        attempt = PaymentAttempt(
            payment_id="pay_001",
            order_id=c.observable.order_id,
            amount_paise=c.observable.amount_paise,
            status=PaymentStatus.FAILED,
            method=c.observable.payment_method,
            failure_context=PaymentFailureContext(
                error_code=c.observable.error_code,
                error_description=c.observable.error_description,
            ),
        )
        customer = Customer(
            customer_id=c.observable.customer_id,
            successful_purchase_count=c.observable.successful_purchase_count,
        )
        pol_ctx = RecoveryPolicyContext(
            order=order,
            failed_attempt=attempt,
            customer=customer,
            consents=c.observable.consents,
            target_channel=ContactChannel.WHATSAPP,
        )
        pol_dec = p_engine.evaluate(pol_ctx)

        diag_res = RulesDiagnosisAdapter().diagnose(
            DiagnosisInput(
                error_code=c.observable.error_code,
                error_source=c.observable.error_source,
                error_step=c.observable.error_step,
                error_reason=c.observable.error_reason,
                payment_method=c.observable.payment_method,
                attempt_count=c.observable.attempt_count,
                event_timestamp=c.observable.failure_timestamp,
            )
        )

        ros_res = ROSCalculator().calculate(
            ROSInput(
                diagnosis_category=diag_res.category,
                attempt_count=c.observable.attempt_count,
                customer_successful_purchases=c.observable.successful_purchase_count,
                is_high_risk=c.observable.is_high_risk,
                failure_occurred_at=c.observable.failure_timestamp,
                evaluation_time=c.observable.failure_timestamp,
                has_alternate_payment_method=c.observable.has_alternate_payment_method,
                payment_method=c.observable.payment_method,
            )
        )

        cands = ActionCandidateBuilder().build_candidates(pol_dec, diag_res, ros_res)
        obs_feat = ObservableCaseFeatures(
            order_amount_paise=c.observable.amount_paise,
            ros_score=ros_res.score,
            diagnosis_category=diag_res.category,
            prior_contacts=c.observable.prior_order_contact_count,
        )
        estimates = SimulationEstimator().estimate(
            EstimatorInput(
                observable_features=obs_feat,
                action_candidates=cands.candidates,
                ros_result=ros_res,
            )
        )
        rec = ActionUtilityRanker().rank(estimates)
        return (
            pol_dec.decision_type.value,
            diag_res.category.value,
            ros_res.score,
            rec.selected_action.value,
        )

    res_a = run_operational_pipeline(case_a)
    res_b = run_operational_pipeline(case_b)

    assert res_a == res_b, (
        "Decision pipeline output differed despite identical observable features!"
    )


def test_operational_tables_do_not_contain_hidden_outcomes() -> None:
    """Ensure operational database schema has zero hidden outcome columns."""
    for table_name, table in Base.metadata.tables.items():
        for column in table.columns:
            assert "hidden" not in column.name.lower(), (
                f"Operational table '{table_name}' contains illegal column '{column.name}'"
            )
            assert "counterfactual" not in column.name.lower(), (
                f"Operational table '{table_name}' contains illegal column '{column.name}'"
            )

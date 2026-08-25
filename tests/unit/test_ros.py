"""Unit tests for the deterministic Recovery Opportunity Score (ROSCalculator)."""

from datetime import UTC, datetime, timedelta

from retrypay.decision.diagnosis import FailureDiagnosisCategory
from retrypay.decision.ros import ROSCalculator, ROSInput

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


def test_ros_exact_feature_contributions() -> None:
    """Ensure exact feature family contributions match specification."""
    calc = ROSCalculator()
    inp = ROSInput(
        diagnosis_category=FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK,  # +30
        attempt_count=2,  # +20
        customer_successful_purchases=3,  # +15
        is_high_risk=False,  # 0
        failure_occurred_at=NOW - timedelta(minutes=5),  # +10
        evaluation_time=NOW,
        has_alternate_payment_method=False,  # +7 for network/auth
    )
    result = calc.calculate(inp)

    assert result.feature_contributions["failure_recoverability"] == 30
    assert result.feature_contributions["purchase_intent"] == 20
    assert result.feature_contributions["prior_merchant_relationship"] == 15
    assert result.feature_contributions["risk_penalty"] == 0
    assert result.feature_contributions["freshness"] == 10
    assert result.feature_contributions["recovery_route_suitability"] == 7
    assert result.score == 82
    assert result.opportunity_band == "HIGH_OPPORTUNITY"


def test_ros_score_clamping() -> None:
    """Ensure score clamps cleanly at 0 and 100."""
    calc = ROSCalculator()

    # Max possible score
    inp_max = ROSInput(
        diagnosis_category=FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK,  # +30
        attempt_count=3,  # +20
        customer_successful_purchases=5,  # +15
        is_high_risk=False,  # 0
        failure_occurred_at=NOW - timedelta(minutes=2),  # +10
        evaluation_time=NOW,
        has_alternate_payment_method=True,  # +7
    )
    res_max = calc.calculate(inp_max)
    assert 0 <= res_max.score <= 100

    # High risk with zero other contributions -> clamped at 0
    inp_min = ROSInput(
        diagnosis_category=FailureDiagnosisCategory.HARD_DECLINE_OR_RISK,  # 0
        attempt_count=1,  # 12
        customer_successful_purchases=0,  # 0
        is_high_risk=True,  # -15
        failure_occurred_at=NOW - timedelta(minutes=300),  # 0
        evaluation_time=NOW,
        has_alternate_payment_method=False,  # 0
    )
    res_min = calc.calculate(inp_min)
    # Raw = 0 + 12 + 0 - 15 + 0 + 0 = -3 -> Clamped to 0
    assert res_min.score == 0
    assert res_min.opportunity_band == "LOW_OPPORTUNITY"


def test_ros_freshness_boundaries() -> None:
    """Ensure freshness points drop at 10, 60, and 240 minute thresholds."""
    calc = ROSCalculator()

    def get_freshness_score(mins: float) -> int:
        res = calc.calculate(
            ROSInput(
                diagnosis_category=FailureDiagnosisCategory.SOFT_DECLINE,
                attempt_count=1,
                customer_successful_purchases=0,
                failure_occurred_at=NOW - timedelta(minutes=mins),
                evaluation_time=NOW,
            )
        )
        return res.feature_contributions["freshness"]

    assert get_freshness_score(5.0) == 10  # <= 10 min
    assert get_freshness_score(10.0) == 10  # Exact boundary
    assert get_freshness_score(15.0) == 6  # 11-60 min
    assert get_freshness_score(60.0) == 6  # Exact boundary
    assert get_freshness_score(90.0) == 3  # 61-240 min
    assert get_freshness_score(240.0) == 3  # Exact boundary
    assert get_freshness_score(241.0) == 0  # > 240 min


def test_ros_purchase_history_boundaries() -> None:
    """Ensure prior purchase relationship points match 0, 1-2, and 3+."""
    calc = ROSCalculator()

    def get_history_score(purchases: int) -> int:
        res = calc.calculate(
            ROSInput(
                diagnosis_category=FailureDiagnosisCategory.SOFT_DECLINE,
                attempt_count=1,
                customer_successful_purchases=purchases,
                failure_occurred_at=NOW,
                evaluation_time=NOW,
            )
        )
        return res.feature_contributions["prior_merchant_relationship"]

    assert get_history_score(0) == 0
    assert get_history_score(1) == 8
    assert get_history_score(2) == 8
    assert get_history_score(3) == 15
    assert get_history_score(10) == 15


def test_ros_route_suitability_rules() -> None:
    """Ensure recovery route suitability rules apply correctly."""
    calc = ROSCalculator()

    # Interrupted UPI with alternative method -> +10
    res_upi = calc.calculate(
        ROSInput(
            diagnosis_category=FailureDiagnosisCategory.UPI_INTENT_INTERRUPTED,
            failure_occurred_at=NOW,
            evaluation_time=NOW,
            has_alternate_payment_method=True,
        )
    )
    assert res_upi.feature_contributions["recovery_route_suitability"] == 10

    # Soft decline with alternate method -> +5
    res_soft = calc.calculate(
        ROSInput(
            diagnosis_category=FailureDiagnosisCategory.SOFT_DECLINE,
            failure_occurred_at=NOW,
            evaluation_time=NOW,
            has_alternate_payment_method=True,
        )
    )
    assert res_soft.feature_contributions["recovery_route_suitability"] == 5


def test_ros_deterministic_reproducibility() -> None:
    """Ensure identical inputs produce identical ROS results."""
    calc = ROSCalculator()
    inp = ROSInput(
        diagnosis_category=FailureDiagnosisCategory.AUTHENTICATION_INCOMPLETE,
        attempt_count=2,
        customer_successful_purchases=2,
        failure_occurred_at=NOW - timedelta(minutes=20),
        evaluation_time=NOW,
        has_alternate_payment_method=True,
    )
    res1 = calc.calculate(inp)
    res2 = calc.calculate(inp)

    assert res1.score == res2.score
    assert res1.feature_contributions == res2.feature_contributions
    assert res1.opportunity_band == res2.opportunity_band

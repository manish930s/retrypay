"""Unit tests for synthetic scenario cohort generator."""

from retrypay.evaluation.generator import (
    ScenarioGenerationConfig,
    SyntheticScenarioGenerator,
)


def test_generator_seed_reproducibility() -> None:
    """Same seed must produce 100% identical cohort."""
    config1 = ScenarioGenerationConfig(seed=42, cohort_size=100)
    config2 = ScenarioGenerationConfig(seed=42, cohort_size=100)

    cohort1 = SyntheticScenarioGenerator(config1).generate_cohort()
    cohort2 = SyntheticScenarioGenerator(config2).generate_cohort()

    assert cohort1.cohort_id == cohort2.cohort_id
    assert len(cohort1.cases) == len(cohort2.cases) == 100

    for c1, c2 in zip(cohort1.cases, cohort2.cases, strict=True):
        assert c1.observable == c2.observable
        assert c1.hidden_outcomes == c2.hidden_outcomes


def test_generator_different_seed_produces_different_cohort() -> None:
    """Different seed must produce different cases."""
    config1 = ScenarioGenerationConfig(seed=42, cohort_size=50)
    config2 = ScenarioGenerationConfig(seed=99, cohort_size=50)

    cohort1 = SyntheticScenarioGenerator(config1).generate_cohort()
    cohort2 = SyntheticScenarioGenerator(config2).generate_cohort()

    assert cohort1.cohort_id != cohort2.cohort_id
    # Amounts should vary
    amounts1 = [c.observable.amount_paise for c in cohort1.cases]
    amounts2 = [c.observable.amount_paise for c in cohort2.cases]
    assert amounts1 != amounts2


def test_generator_distribution_feature_mixture() -> None:
    """1,000 cases cohort must contain expected mixture of archetypes and edge cases."""
    config = ScenarioGenerationConfig(seed=42, cohort_size=1000)
    cohort = SyntheticScenarioGenerator(config).generate_cohort()

    assert len(cohort.cases) == 1000

    error_codes = {c.observable.error_code for c in cohort.cases}
    assert "BAD_REQUEST_PAYMENT_TIMED_OUT" in error_codes
    assert "GATEWAY_ERROR" in error_codes
    assert "AUTHENTICATION_FAILED" in error_codes
    assert "BAD_REQUEST_PAYMENT_DECLINED" in error_codes
    assert "SUSPECTED_FRAUD" in error_codes
    assert "CARD_REPORTED_LOST" in error_codes

    # Check edge conditions
    high_risk_count = sum(1 for c in cohort.cases if c.observable.is_high_risk)
    high_value_count = sum(1 for c in cohort.cases if c.observable.amount_paise > 1_000_000)
    quiet_hours_count = sum(1 for c in cohort.cases if c.observable.is_quiet_hours)
    already_paid_count = sum(1 for c in cohort.cases if c.observable.is_order_already_paid)

    assert high_risk_count > 0, "No high-risk cases generated"
    assert high_value_count > 0, "No high-value cases generated"
    assert quiet_hours_count > 0, "No quiet-hours cases generated"
    assert already_paid_count > 0, "No already-paid cases generated"


def test_generator_synthetic_data_safety() -> None:
    """Synthetic cases must contain purely fictional IDs and no live credentials."""
    config = ScenarioGenerationConfig(seed=42, cohort_size=100)
    cohort = SyntheticScenarioGenerator(config).generate_cohort()

    for c in cohort.cases:
        assert c.observable.case_id.startswith("synth_case_")
        assert c.observable.customer_id.startswith("cust_synth_")
        assert c.observable.order_id.startswith("order_synth_")
        assert "live" not in c.observable.case_id

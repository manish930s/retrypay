"""Synthetic scenario generator producing reproducible cohorts with potential outcomes."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from retrypay.domain.models import ContactChannel, ContactConsentStatus
from retrypay.evaluation.contracts import (
    HiddenPotentialOutcomes,
    SyntheticCase,
    SyntheticCaseObservable,
    SyntheticCohort,
)


class ScenarioGenerationConfig(BaseModel):
    """Configuration for reproducible synthetic scenario cohort generation."""

    model_config = ConfigDict(frozen=True)

    seed: int = Field(default=42, description="Random generator seed for exact reproducibility")
    cohort_size: int = Field(default=1000, ge=1, le=50000, description="Number of synthetic cases")
    generator_version: str = Field(
        default="synth-gen-v1.0", description="Generator algorithm version"
    )
    base_timestamp: datetime = Field(
        default_factory=lambda: datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC),
        description="Base simulation time anchor",
    )


# Error Archetypes and their failure codes
FAILURE_ARCHETYPES: Final[list[dict[str, Any]]] = [
    {
        "category": "NETWORK_TIMEOUT",
        "weight": 0.25,
        "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
        "error_source": "gateway",
        "error_step": "payment_authorization",
        "error_reason": "payment_timed_out",
        "error_description": "Payment authorization timed out from bank gateway",
        "method": "upi",
        "base_natural_p": 0.20,
        "generic_lift": 0.10,
        "policy_lift": 0.28,
        "is_risk": False,
    },
    {
        "category": "UPI_TECHNICAL_ERROR",
        "weight": 0.20,
        "error_code": "GATEWAY_ERROR",
        "error_source": "gateway",
        "error_step": "payment_authorization",
        "error_reason": "upi_collect_timeout",
        "error_description": "UPI PSP collect request timed out",
        "method": "upi",
        "base_natural_p": 0.18,
        "generic_lift": 0.08,
        "policy_lift": 0.25,
        "is_risk": False,
    },
    {
        "category": "AUTHENTICATION_FAILED",
        "weight": 0.15,
        "error_code": "AUTHENTICATION_FAILED",
        "error_source": "bank",
        "error_step": "payment_authentication",
        "error_reason": "otp_expired",
        "error_description": "Customer OTP expired or incorrect 3DS authentication",
        "method": "card",
        "base_natural_p": 0.12,
        "generic_lift": 0.12,
        "policy_lift": 0.26,
        "is_risk": False,
    },
    {
        "category": "INSUFFICIENT_FUNDS",
        "weight": 0.15,
        "error_code": "BAD_REQUEST_PAYMENT_DECLINED",
        "error_source": "bank",
        "error_step": "payment_authorization",
        "error_reason": "insufficient_balance",
        "error_description": "Account balance insufficient for transaction",
        "method": "upi",
        "base_natural_p": 0.06,
        "generic_lift": 0.04,
        "policy_lift": 0.22,  # Boost from alternate payment method suggestion
        "is_risk": False,
    },
    {
        "category": "USER_DROPPED_OFF",
        "weight": 0.10,
        "error_code": "BAD_REQUEST_PAYMENT_CANCELLED_BY_USER",
        "error_source": "customer",
        "error_step": "payment_authorization",
        "error_reason": "user_cancelled",
        "error_description": "Customer cancelled the checkout transaction",
        "method": "card",
        "base_natural_p": 0.08,
        "generic_lift": 0.10,
        "policy_lift": 0.18,
        "is_risk": False,
    },
    {
        "category": "HARD_DECLINE_FRAUD",
        "weight": 0.05,
        "error_code": "SUSPECTED_FRAUD",
        "error_source": "bank",
        "error_step": "payment_risk_check",
        "error_reason": "suspected_fraud_block",
        "error_description": "Transaction flagged for risk or suspected fraud",
        "method": "card",
        "base_natural_p": 0.00,
        "generic_lift": 0.00,
        "policy_lift": 0.00,  # Strict zero recovery and policy block
        "is_risk": True,
    },
    {
        "category": "CARD_LOST_STOLEN",
        "weight": 0.05,
        "error_code": "CARD_REPORTED_LOST",
        "error_source": "bank",
        "error_step": "payment_authorization",
        "error_reason": "card_stolen",
        "error_description": "Card reported lost or stolen",
        "method": "card",
        "base_natural_p": 0.00,
        "generic_lift": 0.00,
        "policy_lift": 0.00,
        "is_risk": True,
    },
    {
        "category": "UNKNOWN_ERROR",
        "weight": 0.05,
        "error_code": "UNKNOWN_ERROR",
        "error_source": "gateway",
        "error_step": "payment_authorization",
        "error_reason": "unknown_reason",
        "error_description": "Generic unspecified failure",
        "method": "netbanking",
        "base_natural_p": 0.10,
        "generic_lift": 0.05,
        "policy_lift": 0.14,
        "is_risk": False,
    },
]


class SyntheticScenarioGenerator:
    """Generates deterministic cohorts of synthetic checkout payment failures."""

    def __init__(self, config: ScenarioGenerationConfig | None = None) -> None:
        self._config = config or ScenarioGenerationConfig()

    def generate_cohort(self) -> SyntheticCohort:
        """Generate a complete synthetic cohort deterministically using the configured seed."""
        rng = random.Random(self._config.seed)
        cases: list[SyntheticCase] = []

        cohort_id = f"cohort_{self._config.seed}_{self._config.cohort_size}"
        archetypes = FAILURE_ARCHETYPES
        weights = [a["weight"] for a in archetypes]

        for i in range(self._config.cohort_size):
            case_id = f"synth_case_{self._config.seed}_{i + 1:04d}"
            customer_id = f"cust_synth_{self._config.seed}_{i + 1:04d}"
            order_id = f"order_synth_{self._config.seed}_{i + 1:04d}"

            # Pick archetype
            arch = rng.choices(archetypes, weights=weights, k=1)[0]

            # Generate order amount (paise): typical range ₹150 to ₹15,000
            # 5% are high-value (> ₹10,000)
            is_high_value = rng.random() < 0.05
            if is_high_value:
                amount_paise = rng.randint(1_050_000, 2_500_000)  # ₹10,500 - ₹25,000
            else:
                amount_paise = rng.randint(15_000, 950_000)  # ₹150 - ₹9,500

            # Purchase history (ROS feature)
            successful_purchases = rng.choices(
                [0, 1, 2, 3, 5, 10], weights=[0.4, 0.25, 0.15, 0.1, 0.05, 0.05]
            )[0]

            # Customer channel consent
            consent_roll = rng.random()
            if consent_roll < 0.85:
                consents = {ContactChannel.WHATSAPP: ContactConsentStatus.OPTED_IN}
            elif consent_roll < 0.95:
                consents = {ContactChannel.WHATSAPP: ContactConsentStatus.OPTED_OUT}
            else:
                consents = {ContactChannel.WHATSAPP: ContactConsentStatus.UNKNOWN}

            # Prior contacts (cap tracking)
            prior_order_contacts = rng.choices([0, 1, 2], weights=[0.85, 0.12, 0.03])[0]
            customer_30d_contacts = (
                prior_order_contacts
                + rng.choices([0, 1, 2, 3], weights=[0.75, 0.15, 0.07, 0.03])[0]
            )

            # Edge conditions
            is_order_already_paid = rng.random() < 0.03
            is_quiet_hours = rng.random() < 0.04
            is_risk = arch["is_risk"] or (rng.random() < 0.02)
            has_alternate = rng.random() < 0.85

            failure_time = self._config.base_timestamp + timedelta(
                minutes=i * 2, seconds=rng.randint(0, 59)
            )

            observable = SyntheticCaseObservable(
                case_id=case_id,
                merchant_id="merchant_synth_001",
                customer_id=customer_id,
                order_id=order_id,
                amount_paise=amount_paise,
                currency="INR",
                payment_method=arch["method"],
                error_code=arch["error_code"],
                error_source=arch["error_source"],
                error_step=arch["error_step"],
                error_reason=arch["error_reason"],
                error_description=arch["error_description"],
                attempt_count=rng.randint(1, 3),
                failure_timestamp=failure_time,
                successful_purchase_count=successful_purchases,
                consents=consents,
                prior_order_contact_count=prior_order_contacts,
                customer_30d_contact_count=customer_30d_contacts,
                is_high_risk=is_risk,
                has_alternate_payment_method=has_alternate,
                is_order_already_paid=is_order_already_paid,
                is_quiet_hours=is_quiet_hours,
            )

            # Potential Outcomes simulation
            # Latent parameters
            latent_intent = rng.uniform(0.1, 0.9)
            latent_friction = rng.uniform(0.1, 0.9)

            base_p = arch["base_natural_p"] * (0.8 + 0.4 * latent_intent)
            generic_p = min(0.95, base_p + arch["generic_lift"] * (1.1 - 0.2 * latent_friction))
            policy_p = min(0.98, base_p + arch["policy_lift"] * (1.2 - 0.2 * latent_friction))

            # Policy / consent / risk override rules for potential outcomes:
            # If customer opted out or risk block, intervention gives zero incremental lift
            is_opted_out = consents.get(ContactChannel.WHATSAPP) == ContactConsentStatus.OPTED_OUT
            if is_risk:
                base_p = 0.0
                generic_p = 0.0
                policy_p = 0.0
            if is_opted_out:
                generic_p = base_p
                policy_p = base_p
            if is_order_already_paid:
                base_p = 1.0
                generic_p = 1.0
                policy_p = 1.0

            # Deterministic outcome realization thresholds based on latent customer roll
            outcome_roll = rng.random()
            out_no_action = outcome_roll < base_p
            out_generic = outcome_roll < generic_p
            out_policy = outcome_roll < policy_p

            hidden = HiddenPotentialOutcomes(
                hidden_outcome_no_action=out_no_action,
                hidden_outcome_generic_reminder=out_generic,
                hidden_outcome_retrypay_policy=out_policy,
                hidden_gmv_no_action_paise=amount_paise if out_no_action else 0,
                hidden_gmv_generic_reminder_paise=amount_paise if out_generic else 0,
                hidden_gmv_retrypay_policy_paise=amount_paise if out_policy else 0,
                latent_intent_score=latent_intent,
                latent_friction_score=latent_friction,
            )

            cases.append(SyntheticCase(observable=observable, hidden_outcomes=hidden))

        return SyntheticCohort(
            cohort_id=cohort_id,
            scenario_seed=self._config.seed,
            cohort_size=len(cases),
            generator_version=self._config.generator_version,
            created_at=self._config.base_timestamp,
            cases=cases,
        )

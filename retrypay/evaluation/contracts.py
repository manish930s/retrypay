"""Evaluation-only domain contracts, strategy definitions, and hidden potential outcomes.

STRICT ACCESS BOUNDARY:
This module must only be imported by retrypay/evaluation/ and evaluation tests.
Operational modules (policy, decision, api, execution, budget, storage) must NEVER
import this module or access HiddenPotentialOutcomes.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from retrypay.decision.diagnosis import FailureDiagnosisCategory
from retrypay.domain.models import ContactChannel, ContactConsentStatus


class Strategy(StrEnum):
    """Synthetic counterfactual strategy treatment arms."""

    NO_ACTION = "NO_ACTION"
    GENERIC_REMINDER = "GENERIC_REMINDER"
    RETRYPAY_POLICY = "RETRYPAY_POLICY"


class HiddenPotentialOutcomes(BaseModel):
    """Counterfactual potential outcomes across all three strategy arms for a single synthetic case.

    STRICT BOUNDARY: Visible only to evaluation subsystem. Never exposed to operational decisioning.
    """

    model_config = ConfigDict(frozen=True)

    hidden_outcome_no_action: bool = Field(
        ..., description="True if customer naturally recovers without any intervention"
    )
    hidden_outcome_generic_reminder: bool = Field(
        ..., description="True if customer recovers when sent a generic reminder"
    )
    hidden_outcome_retrypay_policy: bool = Field(
        ..., description="True if customer recovers under ReTryPay tailored policy outreach"
    )
    hidden_gmv_no_action_paise: int = Field(
        ..., ge=0, description="Recovered GMV in paise under NO_ACTION arm"
    )
    hidden_gmv_generic_reminder_paise: int = Field(
        ..., ge=0, description="Recovered GMV in paise under GENERIC_REMINDER arm"
    )
    hidden_gmv_retrypay_policy_paise: int = Field(
        ..., ge=0, description="Recovered GMV in paise under RETRYPAY_POLICY arm"
    )
    latent_intent_score: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Unobserved customer purchase intent"
    )
    latent_friction_score: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Unobserved checkout friction level"
    )


class SyntheticCaseObservable(BaseModel):
    """Public observable features of a synthetic payment failure case visible to decisioning."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(..., description="Synthetic case identifier, e.g. synth_case_001")
    merchant_id: str = Field(default="merchant_synth_001", description="Synthetic merchant ID")
    customer_id: str = Field(..., description="Synthetic customer identifier, e.g. cust_synth_001")
    order_id: str = Field(..., description="Synthetic order identifier, e.g. order_synth_001")
    amount_paise: int = Field(..., gt=0, description="Order total in paise")
    currency: str = Field(default="INR", description="Currency code")
    payment_method: str = Field(..., description="Payment method: upi, card, netbanking, wallet")
    error_code: str = Field(..., description="Razorpay error code")
    error_source: str = Field(default="gateway", description="Error source")
    error_step: str = Field(default="payment_authorization", description="Error step")
    error_reason: str = Field(default="payment_failed", description="Error reason")
    error_description: str = Field(
        default="Payment attempt failed", description="Error description"
    )
    attempt_count: int = Field(default=1, ge=1, description="Number of attempts for this order")
    failure_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Failure timestamp"
    )
    successful_purchase_count: int = Field(
        default=0, ge=0, description="Prior successful purchase count"
    )
    consents: dict[ContactChannel, ContactConsentStatus] = Field(
        default_factory=dict, description="Channel consent status mapping"
    )
    prior_order_contact_count: int = Field(default=0, ge=0, description="Prior order contacts")
    customer_30d_contact_count: int = Field(default=0, ge=0, description="30-day contacts")
    is_high_risk: bool = Field(
        default=False, description="Whether merchant or card is flagged high risk"
    )
    has_alternate_payment_method: bool = Field(
        default=True, description="Whether alternate payment method is available"
    )
    is_order_already_paid: bool = Field(
        default=False, description="Whether order was already paid prior to case"
    )
    is_quiet_hours: bool = Field(
        default=False, description="Whether failure occurred during merchant quiet hours"
    )


class SyntheticCase(BaseModel):
    """Full synthetic evaluation case combining observable data and hidden potential outcomes."""

    model_config = ConfigDict(frozen=True)

    observable: SyntheticCaseObservable
    hidden_outcomes: HiddenPotentialOutcomes


class SyntheticCohort(BaseModel):
    """A collection of synthetic cases generated from a specific seed."""

    model_config = ConfigDict(frozen=True)

    cohort_id: str
    scenario_seed: int
    cohort_size: int
    generator_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cases: list[SyntheticCase]


class StrategyAssignment(BaseModel):
    """Deterministic assignment of a single strategy to a synthetic case."""

    model_config = ConfigDict(frozen=True)

    evaluation_run_id: str
    case_id: str
    cohort_id: str
    strategy: Strategy
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RealizedOutcome(BaseModel):
    """Observed result for the assigned strategy arm."""

    model_config = ConfigDict(frozen=True)

    is_recovered: bool
    recovered_gmv_paise: int
    contact_count: int
    selected_action: str
    policy_decision: str
    ros_score: int
    diagnosis_category: FailureDiagnosisCategory | str


class EvaluationRecord(BaseModel):
    """Persisted record combining case, assigned strategy, realized outcome, and hidden outcomes."""

    model_config = ConfigDict(frozen=True)

    evaluation_run_id: str
    case_id: str
    cohort_id: str
    strategy: Strategy
    realized_outcome: RealizedOutcome
    hidden_outcomes: HiddenPotentialOutcomes
    observable_summary: dict[str, Any]
    decision_metadata: dict[str, Any]
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvaluationRun(BaseModel):
    """Metadata for an evaluation execution run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    cohort_id: str
    scenario_seed: int
    assignment_seed: int
    cohort_size: int
    policy_version: str
    ros_version: str
    estimator_version: str
    generator_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

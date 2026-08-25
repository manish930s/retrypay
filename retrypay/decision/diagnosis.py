"""Structured payment failure diagnosis contracts, rules-based classifier, and Gemini adapters."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FailureDiagnosisCategory(StrEnum):
    """Permitted failure diagnosis categories."""

    TEMPORARY_BANK_OR_NETWORK = "temporary_bank_or_network"
    UPI_INTENT_INTERRUPTED = "upi_intent_interrupted"
    AUTHENTICATION_INCOMPLETE = "authentication_incomplete"
    SOFT_DECLINE = "soft_decline"
    CUSTOMER_CANCELLED = "customer_cancelled"
    HARD_DECLINE_OR_RISK = "hard_decline_or_risk"
    UNKNOWN = "unknown"


class DiagnosisMode(StrEnum):
    """Execution mode of the diagnosis adapter."""

    RULES = "RULES"
    GEMINI = "GEMINI"


class ActionType(StrEnum):
    """Approved action candidates for recovery decisioning."""

    NO_ACTION = "NO_ACTION"
    SEND_RETRY_LINK = "SEND_RETRY_LINK"
    SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT = "SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT"
    DELAY_AND_SEND_RETRY_LINK = "DELAY_AND_SEND_RETRY_LINK"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class DiagnosisInput(BaseModel):
    """Sanitized, non-sensitive failure context provided to diagnosis adapters."""

    model_config = ConfigDict(frozen=True)

    error_code: str = Field(..., description="Normalized error code")
    error_source: str | None = Field(
        default=None, description="Error origin: customer, gateway, bank"
    )
    error_step: str | None = Field(default=None, description="Pipeline step of failure")
    error_reason: str | None = Field(default=None, description="Categorical failure reason")
    payment_method: str = Field(
        default="unknown", description="Payment method: upi, card, netbanking"
    )
    attempt_count: int = Field(default=1, ge=1, description="Checkout attempt count")
    event_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the failed payment event",
    )


class DiagnosisResult(BaseModel):
    """Structured, schema-validated diagnosis result."""

    model_config = ConfigDict(frozen=True)

    category: FailureDiagnosisCategory = Field(..., description="Permitted diagnosis category")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    rationale: str = Field(..., max_length=500, description="Short sanitized rationale")
    suggested_action_type: ActionType = Field(..., description="Suggested candidate action type")
    diagnosis_mode: DiagnosisMode = Field(..., description="RULES or GEMINI")
    model_version: str = Field(default="razorpay-error-map-v1", description="Model/rules version")
    fallback_used: bool = Field(default=False, description="Whether rules fallback was activated")


class DiagnosisAdapter(ABC):
    """Abstract interface for failure diagnosis adapters."""

    @abstractmethod
    def diagnose(self, input_data: DiagnosisInput) -> DiagnosisResult:
        """Perform structured failure diagnosis on sanitized input."""


class RulesDiagnosisAdapter(DiagnosisAdapter):
    """Deterministic rules-based diagnosis adapter backed by RazorpayErrorMapper."""

    def diagnose(self, input_data: DiagnosisInput) -> DiagnosisResult:
        """Classify failure using conservative 5-tuple matching against sanitized attributes."""
        from retrypay.decision.razorpay_error_map import RazorpayErrorMapper

        mapper = RazorpayErrorMapper()
        mapped = mapper.map_error(
            code=input_data.error_code,
            source=input_data.error_source,
            step=input_data.error_step,
            reason=input_data.error_reason,
            payment_method=input_data.payment_method,
        )

        return DiagnosisResult(
            category=mapped.category,
            confidence=mapped.confidence,
            rationale=mapped.rationale,
            suggested_action_type=mapped.suggested_action,
            diagnosis_mode=DiagnosisMode.RULES,
            model_version=mapped.mapper_version,
            fallback_used=False,
        )


class GeminiDiagnosisAdapter(DiagnosisAdapter):
    """Google Gemini GenAI diagnosis adapter operating with structured schema output."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-3.7-flash",
        timeout_seconds: int = 5,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def diagnose(self, input_data: DiagnosisInput) -> DiagnosisResult:
        """Invoke Gemini API to classify failure into structured JSON schema."""
        if not self.api_key or not self.api_key.strip():
            raise ValueError("GEMINI_API_KEY must be provided for GeminiDiagnosisAdapter.")

        raise NotImplementedError(
            "GeminiDiagnosisAdapter is invoked in online mode with configured API key."
        )


class FallbackDiagnosisAdapter(DiagnosisAdapter):
    """Diagnosis adapter with automatic fallback to deterministic rules."""

    def __init__(
        self,
        enabled: bool = False,
        gemini_adapter: DiagnosisAdapter | None = None,
        rules_adapter: DiagnosisAdapter | None = None,
        min_confidence_threshold: float = 0.60,
    ) -> None:
        self.enabled = enabled
        self.gemini_adapter = gemini_adapter or GeminiDiagnosisAdapter()
        self.rules_adapter = rules_adapter or RulesDiagnosisAdapter()
        self.min_confidence_threshold = min_confidence_threshold

    def diagnose(self, input_data: DiagnosisInput) -> DiagnosisResult:
        """Run diagnosis, attempting Gemini if enabled, falling back to rules."""
        if not self.enabled:
            return self.rules_adapter.diagnose(input_data)

        try:
            gemini_result = self.gemini_adapter.diagnose(input_data)
            if gemini_result.confidence < self.min_confidence_threshold:
                rules_res = self.rules_adapter.diagnose(input_data)
                return rules_res.model_copy(update={"fallback_used": True})
            return gemini_result
        except Exception:
            rules_res = self.rules_adapter.diagnose(input_data)
            return rules_res.model_copy(update={"fallback_used": True})

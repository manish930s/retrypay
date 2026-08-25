"""Conservative versioned error mapper for sanitized Razorpay error tuples."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from retrypay.decision.diagnosis import ActionType, FailureDiagnosisCategory

MAPPER_VERSION: Final[str] = "razorpay-error-map-v1"


class FixtureType(StrEnum):
    """Classification of test fixture data origin."""

    DOCUMENTED_PROVIDER_PATTERN = "DOCUMENTED_PROVIDER_PATTERN"
    SYNTHETIC_TEST_PATTERN = "SYNTHETIC_TEST_PATTERN"


@dataclass(frozen=True)
class ErrorMappingResult:
    """Result of conservative error tuple matching."""

    category: FailureDiagnosisCategory
    confidence: float
    rationale: str
    suggested_action: ActionType
    mapper_version: str = MAPPER_VERSION


class RazorpayErrorMapper:
    """Versioned conservative error mapper evaluating 5-tuple context.

    Invariants:
    1. Never classifies from error code alone.
    2. Missing mandatory tuple fields (source, step, reason) yield unknown classification.
    3. Inconsistent or conflicting tuple fields yield unknown classification.
    4. Unmapped tuples classify as unknown with MANUAL_REVIEW suggested action.
    5. The mapper produces technical diagnosis recommendations only; it cannot alter policy.
    """

    VERSION: Final[str] = MAPPER_VERSION

    def map_error(
        self,
        code: str | None,
        source: str | None,
        step: str | None,
        reason: str | None,
        payment_method: str | None,
    ) -> ErrorMappingResult:
        """Map sanitized provider error tuple into internal diagnostic taxonomy."""
        # Check for presence of mandatory tuple fields
        if not code or not source or not step or not reason:
            return ErrorMappingResult(
                category=FailureDiagnosisCategory.UNKNOWN,
                confidence=0.30,
                rationale="Missing mandatory error tuple fields (code, source, step, or reason).",
                suggested_action=ActionType.MANUAL_REVIEW,
            )

        c = code.lower().strip()
        s = source.lower().strip()
        st = step.lower().strip()
        r = reason.lower().strip()
        m = (payment_method or "unknown").lower().strip()

        # Check for logical field conflicts
        if m == "card" and "upi" in c:
            return self._unknown_conflict("Payment method is card but error code is UPI-specific.")
        if s == "bank" and r in ("payment_cancelled_by_user", "user_dropped_off"):
            return self._unknown_conflict("Source is bank but reason indicates user cancellation.")
        if s == "customer" and r in ("bank_system_error", "gateway_error"):
            return self._unknown_conflict(
                "Source is customer but reason indicates bank/gateway failure."
            )

        # Check for generic uninformative error tuples
        if (
            c in ("bad_request_error", "bad_request", "error", "payment_failed_error")
            and r in ("payment_failed", "bad_request_error", "payment failed", "error")
        ) or (c == "bad_request_error" and r == "payment_failed"):
            return ErrorMappingResult(
                category=FailureDiagnosisCategory.UNKNOWN,
                confidence=0.30,
                rationale="Generic BAD_REQUEST_ERROR without specific root cause indicator.",
                suggested_action=ActionType.MANUAL_REVIEW,
            )

        # 1. Hard Decline / Risk Pattern
        if (
            s in ("gateway", "bank", "risk")
            and st in ("payment_authorization", "risk_check", "payment_initiation")
            and r
            in (
                "card_security_violation",
                "suspected_fraud",
                "hard_decline",
                "risk_check_failed",
                "stolen_card",
                "restricted_card",
                "transaction_not_permitted_to_cardholder",
            )
        ):
            return ErrorMappingResult(
                category=FailureDiagnosisCategory.HARD_DECLINE_OR_RISK,
                confidence=1.00,
                rationale="Card or account declined due to security, risk, or bank hard block.",
                suggested_action=ActionType.MANUAL_REVIEW,
            )

        # 2. Customer Cancelled / Drop-off Pattern
        if (
            s == "customer"
            and st in ("payment_authorization", "payment_authentication", "payment_initiation")
            and r
            in (
                "payment_cancelled_by_user",
                "user_dropped_off",
                "transaction_cancelled",
                "customer_cancelled",
            )
        ):
            return ErrorMappingResult(
                category=FailureDiagnosisCategory.CUSTOMER_CANCELLED,
                confidence=0.90,
                rationale="Customer abandoned or explicitly cancelled the checkout flow.",
                suggested_action=ActionType.SEND_RETRY_LINK,
            )

        # 3. UPI Intent Interrupted Pattern
        if (
            m == "upi"
            and s in ("customer", "gateway", "bank")
            and st in ("payment_authorization", "payment_initiation")
            and (
                r
                in (
                    "upi_payment_timed_out",
                    "payment_timed_out",
                    "collect_request_rejected",
                    "vpa_not_found",
                    "upi_transaction_failed",
                    "upi_app_not_responding",
                    "bad_request_payment_timed_out",
                    "payment_failed",
                )
                or "timeout" in c
                or "timed_out" in c
                or "upi" in c
            )
        ):
            return ErrorMappingResult(
                category=FailureDiagnosisCategory.UPI_INTENT_INTERRUPTED,
                confidence=0.88,
                rationale="UPI intent handoff or collect request expired before user confirmation.",
                suggested_action=ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT,
            )

        # 4. Authentication Incomplete Pattern
        if (
            s in ("customer", "bank", "gateway")
            and st in ("payment_authentication", "payment_authorization")
            and r
            in (
                "otp_timed_out",
                "invalid_otp",
                "3ds_authentication_failed",
                "authentication_failed",
                "otp_incorrect",
            )
        ):
            return ErrorMappingResult(
                category=FailureDiagnosisCategory.AUTHENTICATION_INCOMPLETE,
                confidence=0.85,
                rationale="Two-factor 3DS/OTP authentication incomplete or expired.",
                suggested_action=ActionType.SEND_RETRY_LINK,
            )

        # 5. Temporary Bank / Network Downtime Pattern
        if (
            s in ("gateway", "bank")
            and st in ("payment_authorization", "payment_initiation")
            and (
                r
                in (
                    "bad_request_payment_timed_out",
                    "gateway_error",
                    "bank_system_error",
                    "network_error",
                    "payment_timed_out",
                    "bank_unavailable",
                    "timeout",
                )
                or "timeout" in c
                or "gateway" in c
                or "system" in c
            )
        ):
            return ErrorMappingResult(
                category=FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK,
                confidence=0.92,
                rationale="Temporary issuing bank downtime or payment gateway network timeout.",
                suggested_action=ActionType.DELAY_AND_SEND_RETRY_LINK,
            )

        # 6. Soft Decline Pattern
        if (
            s in ("bank", "customer")
            and st == "payment_authorization"
            and r
            in (
                "insufficient_funds",
                "limit_exceeded",
                "card_expired_or_incorrect",
                "insufficient_balance",
            )
        ):
            return ErrorMappingResult(
                category=FailureDiagnosisCategory.SOFT_DECLINE,
                confidence=0.85,
                rationale="Card or account limit reached; recoverable via alternative instrument.",
                suggested_action=ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT,
            )

        # Default unmapped tuple -> unknown
        return ErrorMappingResult(
            category=FailureDiagnosisCategory.UNKNOWN,
            confidence=0.30,
            rationale=f"Unmapped error tuple: ({c}, {s}, {st}, {r}, {m}).",
            suggested_action=ActionType.MANUAL_REVIEW,
        )

    def _unknown_conflict(self, explanation: str) -> ErrorMappingResult:
        return ErrorMappingResult(
            category=FailureDiagnosisCategory.UNKNOWN,
            confidence=0.20,
            rationale=f"Conflicting error tuple fields: {explanation}",
            suggested_action=ActionType.MANUAL_REVIEW,
        )

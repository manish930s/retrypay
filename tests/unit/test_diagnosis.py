"""Unit tests for structured failure diagnosis, 5-tuple error mapper, and fallback adapter."""

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from retrypay.decision.diagnosis import (
    ActionType,
    DiagnosisAdapter,
    DiagnosisInput,
    DiagnosisMode,
    DiagnosisResult,
    FailureDiagnosisCategory,
    FallbackDiagnosisAdapter,
    RulesDiagnosisAdapter,
)
from retrypay.decision.razorpay_error_map import (
    MAPPER_VERSION,
    FixtureType,
    RazorpayErrorMapper,
)


def test_rules_diagnosis_all_categories_with_5_tuples() -> None:
    """Ensure all permitted categories are classified using 5-tuple error signatures."""
    adapter = RulesDiagnosisAdapter()

    # 1. Hard decline / risk (DOCUMENTED_PROVIDER_PATTERN)
    res_risk = adapter.diagnose(
        DiagnosisInput(
            error_code="CARD_SECURITY_VIOLATION",
            error_source="bank",
            error_step="payment_authorization",
            error_reason="card_security_violation",
            payment_method="card",
        )
    )
    assert res_risk.category == FailureDiagnosisCategory.HARD_DECLINE_OR_RISK
    assert res_risk.suggested_action_type == ActionType.MANUAL_REVIEW
    assert res_risk.confidence == 1.0
    assert res_risk.model_version == MAPPER_VERSION

    # 2. Customer cancelled (DOCUMENTED_PROVIDER_PATTERN)
    res_cancel = adapter.diagnose(
        DiagnosisInput(
            error_code="BAD_REQUEST_ERROR",
            error_source="customer",
            error_step="payment_authorization",
            error_reason="payment_cancelled_by_user",
            payment_method="card",
        )
    )
    assert res_cancel.category == FailureDiagnosisCategory.CUSTOMER_CANCELLED
    assert res_cancel.suggested_action_type == ActionType.SEND_RETRY_LINK

    # 3. UPI intent interrupted (DOCUMENTED_PROVIDER_PATTERN)
    res_upi = adapter.diagnose(
        DiagnosisInput(
            error_code="BAD_REQUEST_PAYMENT_TIMED_OUT",
            error_source="gateway",
            error_step="payment_authorization",
            error_reason="upi_payment_timed_out",
            payment_method="upi",
        )
    )
    assert res_upi.category == FailureDiagnosisCategory.UPI_INTENT_INTERRUPTED
    assert res_upi.suggested_action_type == ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT

    # 4. Authentication incomplete (DOCUMENTED_PROVIDER_PATTERN)
    res_auth = adapter.diagnose(
        DiagnosisInput(
            error_code="GATEWAY_ERROR",
            error_source="customer",
            error_step="payment_authentication",
            error_reason="otp_timed_out",
            payment_method="card",
        )
    )
    assert res_auth.category == FailureDiagnosisCategory.AUTHENTICATION_INCOMPLETE
    assert res_auth.suggested_action_type == ActionType.SEND_RETRY_LINK

    # 5. Temporary bank/network (DOCUMENTED_PROVIDER_PATTERN)
    res_net = adapter.diagnose(
        DiagnosisInput(
            error_code="BAD_REQUEST_PAYMENT_TIMED_OUT",
            error_source="gateway",
            error_step="payment_authorization",
            error_reason="bad_request_payment_timed_out",
            payment_method="netbanking",
        )
    )
    assert res_net.category == FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK
    assert res_net.suggested_action_type == ActionType.DELAY_AND_SEND_RETRY_LINK

    # 6. Soft decline (DOCUMENTED_PROVIDER_PATTERN)
    res_soft = adapter.diagnose(
        DiagnosisInput(
            error_code="BAD_REQUEST_ERROR",
            error_source="bank",
            error_step="payment_authorization",
            error_reason="insufficient_funds",
            payment_method="card",
        )
    )
    assert res_soft.category == FailureDiagnosisCategory.SOFT_DECLINE
    assert res_soft.suggested_action_type == ActionType.SEND_RETRY_LINK_WITH_ALTERNATIVE_METHOD_HINT


def test_same_error_code_with_different_context_produces_different_classifications() -> None:
    """Ensure the mapper does NOT classify from code alone."""
    mapper = RazorpayErrorMapper()

    # Same code 'BAD_REQUEST_ERROR' -> customer cancellation
    res_user = mapper.map_error(
        code="BAD_REQUEST_ERROR",
        source="customer",
        step="payment_authorization",
        reason="payment_cancelled_by_user",
        payment_method="upi",
    )
    assert res_user.category == FailureDiagnosisCategory.CUSTOMER_CANCELLED

    # Same code 'BAD_REQUEST_ERROR' -> soft decline
    res_funds = mapper.map_error(
        code="BAD_REQUEST_ERROR",
        source="bank",
        step="payment_authorization",
        reason="insufficient_funds",
        payment_method="card",
    )
    assert res_funds.category == FailureDiagnosisCategory.SOFT_DECLINE


def test_missing_tuple_fields_yield_unknown() -> None:
    """Ensure missing source, step, or reason fields yield conservative UNKNOWN classification."""
    mapper = RazorpayErrorMapper()

    # Missing source and step
    res_missing = mapper.map_error(
        code="BAD_REQUEST_PAYMENT_TIMED_OUT",
        source=None,
        step=None,
        reason=None,
        payment_method="card",
    )
    assert res_missing.category == FailureDiagnosisCategory.UNKNOWN
    assert res_missing.confidence == 0.30
    assert res_missing.suggested_action == ActionType.MANUAL_REVIEW


def test_conflicting_tuple_fields_yield_unknown() -> None:
    """Ensure conflicting error tuple fields classify as UNKNOWN."""
    mapper = RazorpayErrorMapper()

    # Conflict: Payment method is card, but code is upi_payment_timed_out
    res_conflict = mapper.map_error(
        code="UPI_PAYMENT_TIMED_OUT",
        source="customer",
        step="payment_authorization",
        reason="upi_payment_timed_out",
        payment_method="card",
    )
    assert res_conflict.category == FailureDiagnosisCategory.UNKNOWN
    assert "Conflicting" in res_conflict.rationale


def test_unmapped_tuple_yields_unknown() -> None:
    """Ensure unmapped error tuple classifies as UNKNOWN."""
    mapper = RazorpayErrorMapper()
    res_unmapped = mapper.map_error(
        code="CUSTOM_UNRECOGNIZED_CODE",
        source="custom_source",
        step="custom_step",
        reason="custom_reason",
        payment_method="custom_method",
    )
    assert res_unmapped.category == FailureDiagnosisCategory.UNKNOWN
    assert res_unmapped.suggested_action == ActionType.MANUAL_REVIEW


def test_fixture_classification_tags() -> None:
    """Ensure test fixtures can be clearly labeled as documented or synthetic."""
    doc_fixture = {
        "fixture_type": FixtureType.DOCUMENTED_PROVIDER_PATTERN,
        "code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
    }
    synth_fixture = {
        "fixture_type": FixtureType.SYNTHETIC_TEST_PATTERN,
        "code": "SYNTHETIC_TEST_FAILURE_CODE",
    }
    assert doc_fixture["fixture_type"] == "DOCUMENTED_PROVIDER_PATTERN"
    assert synth_fixture["fixture_type"] == "SYNTHETIC_TEST_PATTERN"


def test_diagnosis_pydantic_schema_validation() -> None:
    """Ensure invalid categories or out-of-bound confidence are rejected by Pydantic."""
    with pytest.raises(ValidationError):
        DiagnosisResult(
            category="invalid_category",  # type: ignore[arg-type]
            confidence=0.8,
            rationale="Test",
            suggested_action_type=ActionType.SEND_RETRY_LINK,
            diagnosis_mode=DiagnosisMode.RULES,
        )

    with pytest.raises(ValidationError):
        DiagnosisResult(
            category=FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK,
            confidence=1.5,  # Must be <= 1.0
            rationale="Test",
            suggested_action_type=ActionType.SEND_RETRY_LINK,
            diagnosis_mode=DiagnosisMode.RULES,
        )


def test_fallback_diagnosis_on_gemini_error() -> None:
    """Ensure FallbackDiagnosisAdapter activates rules and sets fallback_used=True on error."""
    mock_gemini = MagicMock(spec=DiagnosisAdapter)
    mock_gemini.diagnose.side_effect = TimeoutError("Gemini API timeout")

    adapter = FallbackDiagnosisAdapter(enabled=True, gemini_adapter=mock_gemini)
    inp = DiagnosisInput(
        error_code="BAD_REQUEST_PAYMENT_TIMED_OUT",
        error_source="gateway",
        error_step="payment_authorization",
        error_reason="bad_request_payment_timed_out",
        payment_method="card",
    )
    result = adapter.diagnose(inp)

    assert result.category == FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK
    assert result.fallback_used is True
    assert result.diagnosis_mode == DiagnosisMode.RULES
    assert result.model_version == MAPPER_VERSION


def test_fallback_diagnosis_on_low_confidence() -> None:
    """Ensure FallbackDiagnosisAdapter falls back when Gemini returns confidence below threshold."""
    mock_gemini = MagicMock(spec=DiagnosisAdapter)
    mock_gemini.diagnose.return_value = DiagnosisResult(
        category=FailureDiagnosisCategory.UNKNOWN,
        confidence=0.40,  # Below 0.60 threshold
        rationale="Uncertain classification",
        suggested_action_type=ActionType.MANUAL_REVIEW,
        diagnosis_mode=DiagnosisMode.GEMINI,
        fallback_used=False,
    )

    adapter = FallbackDiagnosisAdapter(
        enabled=True,
        gemini_adapter=mock_gemini,
        min_confidence_threshold=0.60,
    )
    inp = DiagnosisInput(
        error_code="BAD_REQUEST_PAYMENT_TIMED_OUT",
        error_source="gateway",
        error_step="payment_authorization",
        error_reason="bad_request_payment_timed_out",
        payment_method="card",
    )
    result = adapter.diagnose(inp)

    assert result.category == FailureDiagnosisCategory.TEMPORARY_BANK_OR_NETWORK
    assert result.fallback_used is True


def test_diagnosis_does_not_contain_customer_message_or_unauthorized_action() -> None:
    """Ensure DiagnosisResult has only approved actions and no customer-facing message."""
    adapter = RulesDiagnosisAdapter()
    result = adapter.diagnose(
        DiagnosisInput(
            error_code="BAD_REQUEST_ERROR",
            error_source="bank",
            error_step="payment_authorization",
            error_reason="insufficient_funds",
            payment_method="card",
        )
    )

    assert isinstance(result.suggested_action_type, ActionType)
    # Assert rationale is short technical note, not customer messaging
    assert not any(
        phrase in result.rationale.lower()
        for phrase in ["dear customer", "click here", "pay now", "your payment of"]
    )

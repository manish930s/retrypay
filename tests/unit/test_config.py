"""Unit tests for configuration validation and security constraints."""

import pytest
from pydantic import ValidationError

from retrypay.config import AppEnvironment, Settings


def test_default_settings_are_safe() -> None:
    """Ensure default configuration is safe: test environment, LLM disabled, test key."""
    settings = Settings(RETRYPAY_ENV=AppEnvironment.TEST)
    assert settings.RETRYPAY_ENV == AppEnvironment.TEST
    assert settings.LLM_ENABLED is False
    assert settings.LLM_MODEL == "gemini-3.7-flash"
    assert settings.LLM_PROVIDER == "gemini"
    assert settings.LLM_TIMEOUT_SECONDS == 5
    assert settings.RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD is False
    assert settings.RAZORPAY_KEY_ID.startswith("rzp_test_")


def test_reject_live_razorpay_key() -> None:
    """Ensure any Razorpay key starting with rzp_live_ is strictly rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(RAZORPAY_KEY_ID="rzp_live_secretkey12345")
    assert "Razorpay live keys" in str(exc_info.value)


def test_accept_test_razorpay_key() -> None:
    """Ensure keys starting with rzp_test_ are accepted."""
    settings = Settings(RAZORPAY_KEY_ID="rzp_test_myvalidkey")
    assert settings.RAZORPAY_KEY_ID == "rzp_test_myvalidkey"


def test_reject_raw_webhook_retention_outside_test_env() -> None:
    """Ensure raw webhook body retention cannot be enabled in non-test environments."""
    with pytest.raises(ValidationError) as exc_info_demo:
        Settings(
            RETRYPAY_ENV=AppEnvironment.DEMO,
            RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=True,
        )
    assert "RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD can only be true when RETRYPAY_ENV=test" in str(
        exc_info_demo.value
    )


def test_allow_raw_webhook_retention_in_test_env() -> None:
    """Ensure raw webhook payload retention is permitted in test environment only."""
    settings = Settings(
        RETRYPAY_ENV=AppEnvironment.TEST,
        RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=True,
    )
    assert settings.RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD is True


def test_reject_unsupported_environment() -> None:
    """Ensure invalid RETRYPAY_ENV strings are rejected."""
    with pytest.raises(ValidationError):
        Settings(RETRYPAY_ENV="production")  # type: ignore[arg-type]


def test_llm_disabled_mode_does_not_require_gemini_api_key() -> None:
    """Ensure LLM_ENABLED=False works cleanly without GEMINI_API_KEY."""
    settings = Settings(
        LLM_ENABLED=False,
        GEMINI_API_KEY=None,
    )
    assert settings.LLM_ENABLED is False
    assert settings.GEMINI_API_KEY is None


def test_llm_enabled_mode_requires_gemini_api_key() -> None:
    """Ensure LLM_ENABLED=True raises validation error if GEMINI_API_KEY is missing or empty."""
    with pytest.raises(ValidationError) as exc_info_none:
        Settings(
            LLM_ENABLED=True,
            LLM_PROVIDER="gemini",
            GEMINI_API_KEY=None,
        )
    assert "GEMINI_API_KEY must be provided" in str(exc_info_none.value)

    with pytest.raises(ValidationError) as exc_info_empty:
        Settings(
            LLM_ENABLED=True,
            LLM_PROVIDER="gemini",
            GEMINI_API_KEY="",
        )
    assert "GEMINI_API_KEY must be provided" in str(exc_info_empty.value)


def test_llm_enabled_mode_with_valid_gemini_key() -> None:
    """Ensure LLM_ENABLED=True succeeds when a valid GEMINI_API_KEY is provided."""
    settings = Settings(
        LLM_ENABLED=True,
        LLM_PROVIDER="gemini",
        GEMINI_API_KEY="test-valid-gemini-key",
    )
    assert settings.LLM_ENABLED is True
    assert settings.GEMINI_API_KEY == "test-valid-gemini-key"

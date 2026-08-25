"""Unit tests verifying Razorpay Test Mode configuration safety and constraints."""

import pytest
from pydantic import ValidationError

from retrypay.config import AppEnvironment, Settings


def test_valid_test_mode_config() -> None:
    """Valid Test Mode configuration initializes cleanly."""
    s = Settings(
        RETRYPAY_ENV=AppEnvironment.TEST,
        RAZORPAY_KEY_ID="rzp_test_mock123",
        RAZORPAY_KEY_SECRET="mock_secret",
        RAZORPAY_WEBHOOK_SECRET="whsec_mock",
        RAZORPAY_PROVIDER_ENABLED=False,
        RAZORPAY_TEST_MODE_ONLY=True,
    )
    assert s.RAZORPAY_KEY_ID == "rzp_test_mock123"
    assert s.RAZORPAY_TEST_MODE_ONLY is True
    assert s.RAZORPAY_PROVIDER_ENABLED is False


def test_reject_live_key_on_startup() -> None:
    """Startup must fail if RAZORPAY_KEY_ID starts with rzp_live_."""
    with pytest.raises(ValidationError, match="CRITICAL SECURITY VIOLATION"):
        Settings(
            RETRYPAY_ENV=AppEnvironment.DEMO,
            RAZORPAY_KEY_ID="rzp_live_secretkey123",
            RAZORPAY_KEY_SECRET="mock_secret",
            RAZORPAY_WEBHOOK_SECRET="whsec_mock",
            RAZORPAY_PROVIDER_ENABLED=False,
            RAZORPAY_TEST_MODE_ONLY=True,
        )


def test_reject_test_mode_only_false() -> None:
    """Startup must fail if RAZORPAY_TEST_MODE_ONLY is set to False."""
    with pytest.raises(ValidationError, match="CRITICAL SAFETY VIOLATION"):
        Settings(
            RETRYPAY_ENV=AppEnvironment.DEMO,
            RAZORPAY_KEY_ID="rzp_test_mock123",
            RAZORPAY_KEY_SECRET="mock_secret",
            RAZORPAY_WEBHOOK_SECRET="whsec_mock",
            RAZORPAY_PROVIDER_ENABLED=False,
            RAZORPAY_TEST_MODE_ONLY=False,
        )


def test_reject_provider_enabled_with_non_test_key() -> None:
    """Startup must fail if provider is enabled but key does not start with rzp_test_."""
    with pytest.raises(ValidationError, match="must begin with 'rzp_test_'"):
        Settings(
            RETRYPAY_ENV=AppEnvironment.DEMO,
            RAZORPAY_KEY_ID="custom_key_123",
            RAZORPAY_KEY_SECRET="mock_secret",
            RAZORPAY_WEBHOOK_SECRET="whsec_mock",
            RAZORPAY_PROVIDER_ENABLED=True,
            RAZORPAY_TEST_MODE_ONLY=True,
        )


def test_reject_retain_raw_payload_outside_test_env() -> None:
    """RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=True must fail in demo or prod environments."""
    with pytest.raises(ValidationError, match="must never be retained in other environments"):
        Settings(
            RETRYPAY_ENV=AppEnvironment.DEMO,
            RAZORPAY_KEY_ID="rzp_test_mock123",
            RAZORPAY_KEY_SECRET="mock_secret",
            RAZORPAY_WEBHOOK_SECRET="whsec_mock",
            RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=True,
        )

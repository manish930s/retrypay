"""Unit tests for FakePaymentLinkProvider and RazorpayPaymentLinkProvider safeguards."""

from datetime import UTC, datetime, timedelta

import pytest

from retrypay.adapters.razorpay.payment_links import (
    CreatePaymentLinkRequest,
    FakePaymentLinkProvider,
    PaymentLinkDefinitiveFailureError,
    PaymentLinkUnknownResultError,
    RazorpayPaymentLinkProvider,
)
from retrypay.config import AppEnvironment, Settings

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


def create_sample_link_request() -> CreatePaymentLinkRequest:
    """Helper constructing CreatePaymentLinkRequest."""
    return CreatePaymentLinkRequest(
        order_id="order_test_100",
        amount_paise=50000,
        currency="INR",
        case_id="rcv_test_100",
        action_id="act_test_100",
        policy_version="recovery-v1.3",
        reference_id="ref_test_case_100",
        expire_by=NOW + timedelta(hours=24),
        description="ReTryPay recovery link",
        notes={"recovery_case_id": "rcv_test_100"},
    )


@pytest.mark.asyncio
async def test_fake_payment_link_provider_success() -> None:
    """Ensure FakePaymentLinkProvider processes requests deterministically."""
    provider = FakePaymentLinkProvider(mode="success", custom_link_id="plink_custom_123")
    req = create_sample_link_request()
    res = await provider.create_payment_link(req)

    assert res.provider_link_id == "plink_custom_123"
    assert res.reference_id == req.reference_id
    assert res.amount_paise == req.amount_paise
    assert "https://rzp.io/i/fake_" in res.short_url
    assert len(provider.created_requests) == 1


@pytest.mark.asyncio
async def test_fake_payment_link_provider_definitive_failure() -> None:
    """Ensure FakePaymentLinkProvider simulates definitive provider rejection."""
    provider = FakePaymentLinkProvider(mode="definitive_failure")
    req = create_sample_link_request()

    with pytest.raises(PaymentLinkDefinitiveFailureError):
        await provider.create_payment_link(req)


@pytest.mark.asyncio
async def test_fake_payment_link_provider_unknown_timeout() -> None:
    """Ensure FakePaymentLinkProvider simulates transport/timeout unknown outcome."""
    provider = FakePaymentLinkProvider(mode="unknown_timeout")
    req = create_sample_link_request()

    with pytest.raises(PaymentLinkUnknownResultError):
        await provider.create_payment_link(req)


def test_razorpay_payment_link_provider_rejects_live_keys() -> None:
    """Ensure RazorpayPaymentLinkProvider strictly rejects live mode keys."""
    with pytest.raises(ValueError) as exc_info:
        Settings(RAZORPAY_KEY_ID="rzp_live_secret12345")
    assert "Razorpay live keys" in str(exc_info.value)

    # Even if constructed directly with live key in non-validated dictionary
    bad_settings = Settings.model_construct(
        RETRYPAY_ENV=AppEnvironment.TEST,
        RAZORPAY_KEY_ID="rzp_live_bypass_attempt",
    )
    with pytest.raises(ValueError) as exc_info_init:
        RazorpayPaymentLinkProvider(settings=bad_settings)
    assert "Live Razorpay keys cannot be used" in str(exc_info_init.value)

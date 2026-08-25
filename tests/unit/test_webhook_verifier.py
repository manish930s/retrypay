"""Unit tests for the Razorpay HMAC-SHA256 WebhookVerifier."""

import hashlib
import hmac

import pytest

from retrypay.adapters.razorpay.verifier import WebhookVerifier


def test_reject_empty_secret() -> None:
    """Ensure WebhookVerifier raises ValueError on empty secret."""
    with pytest.raises(ValueError):
        WebhookVerifier("")

    with pytest.raises(ValueError):
        WebhookVerifier("   ")


def test_valid_signature_verification() -> None:
    """Ensure valid HMAC-SHA256 signature is accepted."""
    secret = "test_webhook_secret_key_123"
    verifier = WebhookVerifier(secret)

    payload = b'{"event":"payment.failed","payload":{"payment":{"entity":{"id":"pay_123"}}}}'
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    result = verifier.verify(payload, expected_sig)
    assert result.is_valid is True
    assert result.reason == "ok"
    assert result.payload_sha256 == hashlib.sha256(payload).hexdigest()


def test_invalid_signature_rejection() -> None:
    """Ensure invalid signature is rejected with signature_mismatch reason."""
    secret = "test_webhook_secret_key_123"
    verifier = WebhookVerifier(secret)

    payload = b'{"event":"payment.failed"}'
    invalid_sig = "a" * 64

    result = verifier.verify(payload, invalid_sig)
    assert result.is_valid is False
    assert result.reason == "signature_mismatch"


def test_missing_and_empty_signature_rejection() -> None:
    """Ensure missing, empty, or whitespace signatures are rejected."""
    secret = "test_webhook_secret_key_123"
    verifier = WebhookVerifier(secret)

    payload = b'{"event":"payment.failed"}'

    # None
    result_none = verifier.verify(payload, None)
    assert result_none.is_valid is False
    assert result_none.reason == "missing_signature"

    # Empty string
    result_empty = verifier.verify(payload, "")
    assert result_empty.is_valid is False
    assert result_empty.reason == "missing_signature"

    # Whitespace
    result_ws = verifier.verify(payload, "   ")
    assert result_ws.is_valid is False
    assert result_ws.reason == "missing_signature"


def test_empty_raw_body_verification() -> None:
    """Ensure verifier operates on empty raw bytes correctly."""
    secret = "test_webhook_secret_key_123"
    verifier = WebhookVerifier(secret)

    empty_payload = b""
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        msg=empty_payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    result = verifier.verify(empty_payload, expected_sig)
    assert result.is_valid is True
    assert result.payload_sha256 == hashlib.sha256(b"").hexdigest()

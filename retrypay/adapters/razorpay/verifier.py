"""Razorpay webhook signature verifier implementing constant-time HMAC-SHA256 comparison."""

import hashlib
import hmac

from retrypay.domain.events import WebhookVerificationResult


class WebhookVerifier:
    """Cryptographic signature verifier for Razorpay webhooks."""

    def __init__(self, webhook_secret: str) -> None:
        if not webhook_secret or not webhook_secret.strip():
            raise ValueError("Webhook secret must not be empty.")
        self._secret_bytes = webhook_secret.encode("utf-8")

    def verify(
        self,
        raw_body: bytes,
        received_signature: str | None,
    ) -> WebhookVerificationResult:
        """Verify the raw webhook payload against the received X-Razorpay-Signature header.

        Performs constant-time HMAC comparison (hmac.compare_digest) to prevent timing attacks.
        Calculates SHA-256 digest of payload for auditing without retaining raw bytes.
        """
        payload_sha256 = hashlib.sha256(raw_body).hexdigest()

        if not received_signature or not received_signature.strip():
            return WebhookVerificationResult(
                is_valid=False,
                reason="missing_signature",
                payload_sha256=payload_sha256,
            )

        # Compute expected HMAC-SHA256 hex digest
        expected_signature = hmac.new(
            self._secret_bytes,
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        # Constant-time comparison
        is_match = hmac.compare_digest(expected_signature, received_signature.strip())

        if not is_match:
            return WebhookVerificationResult(
                is_valid=False,
                reason="signature_mismatch",
                payload_sha256=payload_sha256,
            )

        return WebhookVerificationResult(
            is_valid=True,
            reason="ok",
            payload_sha256=payload_sha256,
        )

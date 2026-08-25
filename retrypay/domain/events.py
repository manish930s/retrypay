"""Domain models for webhook events, signature verification results, and normalized payloads."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from retrypay.domain.models import PaymentFailureContext, PaymentStatus


class PaymentEventType(StrEnum):
    """Supported and tracked payment and payment link webhook event types."""

    PAYMENT_FAILED = "payment.failed"
    PAYMENT_CAPTURED = "payment.captured"
    ORDER_PAID = "order.paid"
    PAYMENT_LINK_PAID = "payment_link.paid"
    PAYMENT_LINK_EXPIRED = "payment_link.expired"
    PAYMENT_LINK_CANCELLED = "payment_link.cancelled"
    PAYMENT_LINK_PARTIALLY_PAID = "payment_link.partially_paid"
    UNSUPPORTED = "unsupported"


class EventProcessingStatus(StrEnum):
    """Processing lifecycle status of an ingested webhook event."""

    RECEIVED = "received"
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class WebhookVerificationResult(BaseModel):
    """Result of cryptographic HMAC-SHA256 signature verification."""

    model_config = ConfigDict(frozen=True)

    is_valid: bool = Field(..., description="Whether signature matches expected HMAC-SHA256")
    reason: str = Field(default="ok", description="Verification explanation or failure reason")
    payload_sha256: str = Field(
        ..., description="Hex digest of SHA-256 hash of raw request payload"
    )


class NormalizedWebhookPayload(BaseModel):
    """Normalized, non-sensitive payment, order, and link data extracted from a webhook."""

    model_config = ConfigDict(frozen=True)

    event_type: PaymentEventType = Field(..., description="Normalized event type")
    provider_event_id: str = Field(..., description="Unique event identifier from Razorpay")
    order_id: str | None = Field(default=None, description="Razorpay order ID, e.g. order_xxx")
    payment_id: str | None = Field(default=None, description="Razorpay payment ID, e.g. pay_xxx")
    provider_link_id: str | None = Field(
        default=None, description="Razorpay Payment Link ID, e.g. plink_xxx"
    )
    reference_id: str | None = Field(default=None, description="Merchant reference ID")
    link_status: str | None = Field(default=None, description="Payment Link status")
    amount_paise: int = Field(..., gt=0, description="Amount in integer paise")
    currency: str = Field(default="INR", description="Currency code")
    payment_status: PaymentStatus | None = Field(
        default=None, description="Payment status if event contains a payment entity"
    )
    method: str = Field(
        default="unknown", description="Payment method: upi, card, netbanking, etc."
    )
    failure_context: PaymentFailureContext | None = Field(
        default=None, description="Failure details if event is payment.failed"
    )
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event creation timestamp (UTC)",
    )


class WebhookEvent(BaseModel):
    """Immutable domain representation of an ingested provider webhook event."""

    model_config = ConfigDict(frozen=True)

    provider_event_id: str = Field(..., description="Razorpay event ID, e.g. event_xxx")
    event_type: PaymentEventType = Field(..., description="Categorized event type")
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when webhook was received at API endpoint (UTC)",
    )
    signature_verification_status: str = Field(
        ..., description="Verification status: valid | invalid | skipped"
    )
    payload_sha256: str = Field(..., description="SHA-256 digest of the raw request payload")
    normalized_payload: NormalizedWebhookPayload | None = Field(
        default=None, description="Normalized event fields if parsed successfully"
    )
    processing_status: EventProcessingStatus = Field(
        default=EventProcessingStatus.RECEIVED, description="Current processing status"
    )
    source: str = Field(default="LOCAL_SIMULATION", description="Event source classification")
    error_reason: str | None = Field(
        default=None, description="Explanation if verification, parsing, or processing failed"
    )

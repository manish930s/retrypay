"""Provider-neutral Payment Link adapters, Fake adapter, and Test Mode adapter."""

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from retrypay.config import AppEnvironment, Settings, get_settings
from retrypay.domain.models import (
    NotificationResult,
    NotificationStatus,
    PaymentLinkStatus,
)


class PaymentLinkProviderError(Exception):
    """Base exception for payment link provider errors."""


class PaymentLinkDefinitiveFailureError(PaymentLinkProviderError):
    """Raised when the provider returns a definitive, permanent rejection."""


class PaymentLinkUnknownResultError(PaymentLinkProviderError):
    """Raised when provider response is unknown due to network timeout or connection reset."""


class CreatePaymentLinkRequest(BaseModel):
    """Provider-neutral parameters for creating a Test Mode Payment Link."""

    model_config = ConfigDict(frozen=True)

    order_id: str = Field(..., description="Original order ID")
    amount_paise: int = Field(..., gt=0, description="Order total in paise")
    currency: str = Field(default="INR", min_length=3, max_length=3, description="ISO currency")
    case_id: str = Field(..., description="Recovery case ID")
    action_id: str = Field(..., description="Recovery action ID")
    policy_version: str = Field(default="recovery-v1.3", description="Active policy version")
    reference_id: str = Field(
        ..., max_length=40, description="Unique merchant reference ID (max 40 chars)"
    )
    expire_by: datetime = Field(..., description="UTC expiration timestamp")
    description: str = Field(
        default="Payment recovery link", description="Non-sensitive payment link description"
    )
    notes: dict[str, str] = Field(
        default_factory=dict, description="Non-sensitive internal reference notes"
    )


class CreatePaymentLinkResult(BaseModel):
    """Standardized response from Payment Link creation."""

    model_config = ConfigDict(frozen=True)

    provider_link_id: str = Field(..., description="Provider payment link ID (e.g. plink_xxx)")
    reference_id: str = Field(..., description="Merchant reference ID")
    short_url: str = Field(..., description="Provider short payment URL")
    status: PaymentLinkStatus = Field(
        default=PaymentLinkStatus.CREATED, description="Initial link status"
    )
    amount_paise: int = Field(..., gt=0, description="Amount in integer paise")
    currency: str = Field(default="INR", description="ISO currency")
    expire_by: datetime = Field(..., description="Expiration timestamp (UTC)")
    provider_created_at: datetime = Field(..., description="Provider creation timestamp (UTC)")


class PaymentLinkProvider(ABC):
    """Abstract provider interface for Payment Link generation."""

    @abstractmethod
    async def create_payment_link(
        self, request: CreatePaymentLinkRequest
    ) -> CreatePaymentLinkResult:
        """Create a Payment Link asynchronously."""

    @abstractmethod
    async def fetch_payment_link_by_reference_id(
        self, reference_id: str
    ) -> CreatePaymentLinkResult | None:
        """Fetch an existing Payment Link by reference_id for reconciliation."""

    @abstractmethod
    async def send_notification(self, provider_link_id: str, medium: str) -> NotificationResult:
        """Resend/notify a Payment Link via SMS or Email using approved provider APIs."""


class FakePaymentLinkProvider(PaymentLinkProvider):
    """Deterministic, offline Fake Payment Link Provider for automated tests."""

    def __init__(
        self,
        mode: str = "success",  # "success" | "definitive_failure" | "unknown_timeout"
        custom_link_id: str | None = None,
    ) -> None:
        self.mode = mode
        self.custom_link_id = custom_link_id
        self.created_requests: list[CreatePaymentLinkRequest] = []
        self.sent_notifications: list[dict[str, str]] = []

    async def create_payment_link(
        self, request: CreatePaymentLinkRequest
    ) -> CreatePaymentLinkResult:
        """Process fake creation request deterministically without network calls."""
        self.created_requests.append(request)

        if self.mode == "definitive_failure":
            raise PaymentLinkDefinitiveFailureError(
                "Provider rejected payment link: invalid parameters."
            )

        if self.mode == "unknown_timeout":
            raise PaymentLinkUnknownResultError("Provider connection timed out; outcome unknown.")

        link_id = self.custom_link_id or f"plink_fake_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        return CreatePaymentLinkResult(
            provider_link_id=link_id,
            reference_id=request.reference_id,
            short_url=f"https://rzp.io/i/fake_{link_id[-8:]}",
            status=PaymentLinkStatus.CREATED,
            amount_paise=request.amount_paise,
            currency=request.currency,
            expire_by=request.expire_by,
            provider_created_at=now,
        )

    async def fetch_payment_link_by_reference_id(
        self, reference_id: str
    ) -> CreatePaymentLinkResult | None:
        """Return matching fake link if created."""
        for req in self.created_requests:
            if req.reference_id == reference_id:
                link_id = self.custom_link_id or f"plink_fake_{uuid.uuid4().hex[:12]}"
                now = datetime.now(UTC)
                return CreatePaymentLinkResult(
                    provider_link_id=link_id,
                    reference_id=reference_id,
                    short_url=f"https://rzp.io/i/fake_{link_id[-8:]}",
                    status=PaymentLinkStatus.CREATED,
                    amount_paise=req.amount_paise,
                    currency=req.currency,
                    expire_by=req.expire_by,
                    provider_created_at=now,
                )
        return None

    async def send_notification(self, provider_link_id: str, medium: str) -> NotificationResult:
        """Process fake notification dispatch deterministically."""
        self.sent_notifications.append({"provider_link_id": provider_link_id, "medium": medium})

        if self.mode == "definitive_failure":
            return NotificationResult(
                status=NotificationStatus.FAILED,
                error_code="PROVIDER_REJECTED",
                error_message="Provider rejected reminder dispatch request.",
            )
        if self.mode == "unknown_timeout":
            raise PaymentLinkUnknownResultError(
                "Provider notification dispatch connection timed out."
            )

        notif_id = f"notif_fake_{uuid.uuid4().hex[:12]}"
        return NotificationResult(
            status=NotificationStatus.ACCEPTED,
            provider_notification_id=notif_id,
            request_id=f"req_{uuid.uuid4().hex[:10]}",
        )


class RazorpayPaymentLinkProvider(PaymentLinkProvider):
    """Official Razorpay Test Mode Payment Link adapter."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

        # Strict safety check: Never permit execution in production or with live keys
        if self.settings.RETRYPAY_ENV not in (AppEnvironment.TEST, AppEnvironment.DEMO):
            raise ValueError(
                "RazorpayPaymentLinkProvider is only available in 'test' or 'demo' environments."
            )
        if self.settings.RAZORPAY_KEY_ID.startswith("rzp_live_"):
            raise ValueError(
                "CRITICAL SECURITY VIOLATION: Live Razorpay keys cannot be used with Payment Links."
            )
        if not self.settings.RAZORPAY_PROVIDER_ENABLED:
            raise PaymentLinkDefinitiveFailureError(
                "Razorpay external provider calls are disabled (RAZORPAY_PROVIDER_ENABLED=false)."
            )

    async def create_payment_link(
        self, request: CreatePaymentLinkRequest
    ) -> CreatePaymentLinkResult:
        """Send POST /v1/payment_links to Razorpay API in Test Mode."""
        url = "https://api.razorpay.com/v1/payment_links"
        auth = (self.settings.RAZORPAY_KEY_ID, self.settings.RAZORPAY_KEY_SECRET)

        payload: dict[str, Any] = {
            "amount": request.amount_paise,
            "currency": request.currency,
            "accept_partial": False,
            "reference_id": request.reference_id,
            "description": request.description,
            "expire_by": int(request.expire_by.timestamp()),
            "reminder_enable": False,
            "notes": {
                "recovery_case_id": request.case_id,
                "recovery_action_id": request.action_id,
                "policy_version": request.policy_version,
            },
            "notify": {
                "sms": False,
                "email": False,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, auth=auth)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise PaymentLinkUnknownResultError(
                f"Transport error connecting to Razorpay API: {exc}"
            ) from exc

        if response.status_code == 200 or response.status_code == 201:
            data = response.json()
            return CreatePaymentLinkResult(
                provider_link_id=data["id"],
                reference_id=data.get("reference_id", request.reference_id),
                short_url=data["short_url"],
                status=PaymentLinkStatus.CREATED,
                amount_paise=int(data["amount"]),
                currency=data.get("currency", request.currency),
                expire_by=datetime.fromtimestamp(data["expire_by"], tz=UTC),
                provider_created_at=datetime.fromtimestamp(data["created_at"], tz=UTC),
            )

        # Handle provider errors
        if response.status_code >= 400 and response.status_code < 500:
            raise PaymentLinkDefinitiveFailureError(
                f"Razorpay rejected Payment Link creation with HTTP {response.status_code}: "
                f"{response.text}"
            )
        raise PaymentLinkUnknownResultError(
            f"Razorpay server error HTTP {response.status_code}; status unknown."
        )

    async def fetch_payment_link_by_reference_id(
        self, reference_id: str
    ) -> CreatePaymentLinkResult | None:
        """Fetch existing Payment Link from Razorpay by reference_id."""
        url = f"https://api.razorpay.com/v1/payment_links?reference_id={reference_id}"
        auth = (self.settings.RAZORPAY_KEY_ID, self.settings.RAZORPAY_KEY_SECRET)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, auth=auth)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise PaymentLinkUnknownResultError(
                f"Transport error fetching link by reference_id: {exc}"
            ) from exc

        if response.status_code == 200:
            data = response.json()
            items = data.get("payment_links", [])
            if items:
                item = items[0]
                return CreatePaymentLinkResult(
                    provider_link_id=item["id"],
                    reference_id=item.get("reference_id", reference_id),
                    short_url=item["short_url"],
                    status=PaymentLinkStatus.CREATED,
                    amount_paise=int(item["amount"]),
                    currency=item.get("currency", "INR"),
                    expire_by=datetime.fromtimestamp(item["expire_by"], tz=UTC),
                    provider_created_at=datetime.fromtimestamp(item["created_at"], tz=UTC),
                )
        return None

    async def send_notification(self, provider_link_id: str, medium: str) -> NotificationResult:
        """Resend/notify a Payment Link via SMS or Email using approved APIs."""
        if medium not in ("sms", "email"):
            return NotificationResult(
                status=NotificationStatus.FAILED,
                error_code="INVALID_MEDIUM",
                error_message=(
                    f"Unsupported notification medium '{medium}'. "
                    "Only 'sms' and 'email' are supported."
                ),
            )

        url = f"https://api.razorpay.com/v1/payment_links/{provider_link_id}/notify_by/{medium}"
        auth = (self.settings.RAZORPAY_KEY_ID, self.settings.RAZORPAY_KEY_SECRET)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, auth=auth)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise PaymentLinkUnknownResultError(
                f"Transport error connecting to Razorpay notify API: {exc}"
            ) from exc

        if response.status_code == 200:
            data = response.json() if response.text else {}
            req_id = response.headers.get("x-request-id", f"req_{uuid.uuid4().hex[:10]}")
            notif_id = data.get("id") or f"notif_rzp_{uuid.uuid4().hex[:10]}"
            return NotificationResult(
                status=NotificationStatus.ACCEPTED,
                provider_notification_id=notif_id,
                request_id=req_id,
            )

        if 400 <= response.status_code < 500:
            return NotificationResult(
                status=NotificationStatus.FAILED,
                error_code=f"HTTP_{response.status_code}",
                error_message=(
                    f"Razorpay notify_by/{medium} rejected with HTTP {response.status_code}."
                ),
            )

        raise PaymentLinkUnknownResultError(
            f"Razorpay server error HTTP {response.status_code} during notify_by/{medium}."
        )

"""Parser and normalizer for Razorpay webhook payloads."""

from datetime import UTC, datetime
from typing import Any

from retrypay.domain.events import NormalizedWebhookPayload, PaymentEventType
from retrypay.domain.models import PaymentFailureContext, PaymentStatus


def parse_and_normalize_webhook(
    raw_json: dict[str, Any],
    provider_event_id: str,
) -> NormalizedWebhookPayload | None:
    """Extract normalized domain payload from raw Razorpay webhook JSON dictionary.

    Returns NormalizedWebhookPayload for supported events, or None if unsupported.
    """
    event_name = raw_json.get("event")
    if not event_name or not isinstance(event_name, str):
        return None

    if event_name not in PaymentEventType._value2member_map_:
        return None

    event_type = PaymentEventType(event_name)
    payload_container = raw_json.get("payload", {})
    if not isinstance(payload_container, dict):
        return None

    created_at_ts = raw_json.get("created_at")
    occurred_at = (
        datetime.fromtimestamp(created_at_ts, tz=UTC)
        if isinstance(created_at_ts, (int, float))
        else datetime.now(UTC)
    )

    if event_type in (PaymentEventType.PAYMENT_FAILED, PaymentEventType.PAYMENT_CAPTURED):
        payment_entity = payload_container.get("payment", {}).get("entity", {})
        if not payment_entity:
            return None

        payment_id = payment_entity.get("id")
        order_id = payment_entity.get("order_id")
        amount = payment_entity.get("amount")
        currency = payment_entity.get("currency", "INR")
        method = payment_entity.get("method", "unknown")

        if not payment_id or not order_id or not isinstance(amount, int):
            return None

        failure_ctx = None
        if event_type == PaymentEventType.PAYMENT_FAILED:
            payment_status = PaymentStatus.FAILED
            failure_ctx = PaymentFailureContext(
                error_code=payment_entity.get("error_code") or "UNKNOWN_ERROR",
                error_description=payment_entity.get("error_description") or "Payment failure",
                error_source=payment_entity.get("error_source") or "gateway",
                error_step=payment_entity.get("error_step") or "payment_authorization",
                error_reason=payment_entity.get("error_reason") or "payment_failed",
            )
        else:
            payment_status = PaymentStatus.CAPTURED

        return NormalizedWebhookPayload(
            event_type=event_type,
            provider_event_id=provider_event_id,
            order_id=order_id,
            payment_id=payment_id,
            amount_paise=amount,
            currency=currency,
            payment_status=payment_status,
            method=method,
            failure_context=failure_ctx,
            occurred_at=occurred_at,
        )

    elif event_type == PaymentEventType.ORDER_PAID:
        order_entity = payload_container.get("order", {}).get("entity", {})
        if not order_entity:
            return None

        order_id = order_entity.get("id")
        amount = order_entity.get("amount") or order_entity.get("amount_paid")
        currency = order_entity.get("currency", "INR")

        if not order_id or not isinstance(amount, int):
            return None

        # Check if an accompanying payment entity is present
        payment_entity = payload_container.get("payment", {}).get("entity", {})
        payment_id = payment_entity.get("id") if payment_entity else None
        method = payment_entity.get("method", "unknown") if payment_entity else "unknown"

        return NormalizedWebhookPayload(
            event_type=event_type,
            provider_event_id=provider_event_id,
            order_id=order_id,
            payment_id=payment_id,
            amount_paise=amount,
            currency=currency,
            payment_status=PaymentStatus.CAPTURED if payment_id else None,
            method=method,
            failure_context=None,
            occurred_at=occurred_at,
        )

    elif event_type in (
        PaymentEventType.PAYMENT_LINK_PAID,
        PaymentEventType.PAYMENT_LINK_EXPIRED,
        PaymentEventType.PAYMENT_LINK_CANCELLED,
        PaymentEventType.PAYMENT_LINK_PARTIALLY_PAID,
    ):
        plink_entity = payload_container.get("payment_link", {}).get("entity", {})
        if not plink_entity:
            return None

        provider_link_id = plink_entity.get("id")
        if not provider_link_id:
            return None

        amount = plink_entity.get("amount") or plink_entity.get("amount_paid") or 1
        currency = plink_entity.get("currency", "INR")
        reference_id = plink_entity.get("reference_id")
        link_status = plink_entity.get("status")

        payment_entity = payload_container.get("payment", {}).get("entity", {})
        payment_id = payment_entity.get("id") if payment_entity else None
        notes = plink_entity.get("notes") if isinstance(plink_entity.get("notes"), dict) else {}
        order_id = (
            plink_entity.get("order_id")
            or (payment_entity.get("order_id") if payment_entity else None)
            or notes.get("order_id")
        )

        return NormalizedWebhookPayload(
            event_type=event_type,
            provider_event_id=provider_event_id,
            order_id=order_id,
            payment_id=payment_id,
            provider_link_id=provider_link_id,
            reference_id=reference_id,
            link_status=link_status,
            amount_paise=amount if isinstance(amount, int) else 1,
            currency=currency,
            payment_status=(
                PaymentStatus.CAPTURED
                if (event_type == PaymentEventType.PAYMENT_LINK_PAID and payment_id is not None)
                else None
            ),
            method="unknown",
            failure_context=None,
            occurred_at=occurred_at,
        )

    return None

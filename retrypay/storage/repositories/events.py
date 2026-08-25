"""Repository for persisting and querying webhook events with deduplication."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.events import EventProcessingStatus, PaymentEventType, WebhookEvent
from retrypay.storage.models import WebhookEventModel


class WebhookEventRepository:
    """Repository handling persistence, deduplication, and lookup of webhook events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_provider_event_id(
        self, provider_event_id: str, source: str = "LOCAL_SIMULATION"
    ) -> WebhookEvent | None:
        """Retrieve a webhook event by Razorpay event ID and source if already stored."""
        stmt = select(WebhookEventModel).where(
            WebhookEventModel.provider_event_id == provider_event_id,
            WebhookEventModel.source == source,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            return None

        return WebhookEvent(
            provider_event_id=model.provider_event_id,
            source=model.source,
            event_type=PaymentEventType(model.event_type)
            if model.event_type in PaymentEventType._value2member_map_
            else PaymentEventType.UNSUPPORTED,
            received_at=model.received_at,
            signature_verification_status=model.signature_verification_status,
            payload_sha256=model.payload_sha256,
            processing_status=EventProcessingStatus(model.processing_status),
            error_reason=model.error_reason,
        )

    async def is_event_processed(
        self, provider_event_id: str, source: str = "LOCAL_SIMULATION"
    ) -> bool:
        """Check if an event ID has already been recorded in the database for the given source."""
        event = await self.get_by_provider_event_id(provider_event_id, source=source)
        return event is not None

    async def record_event(
        self,
        event: WebhookEvent,
        raw_payload_text: str | None = None,
        source: str = "LOCAL_SIMULATION",
    ) -> None:
        """Persist a new webhook event audit record."""
        model = WebhookEventModel(
            provider_event_id=event.provider_event_id,
            source=event.source or source,
            event_type=event.event_type.value,
            received_at=event.received_at,
            signature_verification_status=event.signature_verification_status,
            payload_sha256=event.payload_sha256,
            normalized_payload=event.normalized_payload.model_dump(mode="json")
            if event.normalized_payload
            else None,
            processing_status=event.processing_status.value,
            error_reason=event.error_reason,
            raw_payload=raw_payload_text,
        )
        self._session.add(model)
        await self._session.flush()

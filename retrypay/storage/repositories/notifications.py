"""Repository for persisting simulated notification logs."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.models import (
    ContactChannel,
    NotificationLog,
    NotificationStatus,
    NotificationTemplateKey,
)
from retrypay.storage.models import NotificationLogModel


class NotificationRepository:
    """Async repository for simulated notification execution records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_notification(self, notification_id: str) -> NotificationLog | None:
        """Fetch notification log by ID."""
        stmt = select(NotificationLogModel).where(
            NotificationLogModel.notification_id == notification_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_notifications_for_action(self, action_id: str) -> list[NotificationLog]:
        """Fetch all notifications associated with an action."""
        stmt = select(NotificationLogModel).where(NotificationLogModel.action_id == action_id)
        result = await self._session.execute(stmt)
        return [self._to_domain(m) for m in result.scalars().all()]

    async def save_notification(self, notification: NotificationLog) -> None:
        """Persist simulated notification record."""
        model = NotificationLogModel(
            notification_id=notification.notification_id,
            case_id=notification.case_id,
            action_id=notification.action_id,
            channel=notification.channel.value,
            template_key=notification.template_key.value,
            masked_recipient=notification.masked_recipient,
            link_reference=notification.link_reference,
            status=notification.status.value,
            simulated_at=notification.simulated_at,
        )
        self._session.add(model)
        await self._session.flush()

    def _to_domain(self, model: NotificationLogModel) -> NotificationLog:
        return NotificationLog(
            notification_id=model.notification_id,
            case_id=model.case_id,
            action_id=model.action_id,
            channel=ContactChannel(model.channel),
            template_key=NotificationTemplateKey(model.template_key),
            masked_recipient=model.masked_recipient,
            link_reference=model.link_reference,
            status=NotificationStatus(model.status),
            simulated_at=model.simulated_at,
        )

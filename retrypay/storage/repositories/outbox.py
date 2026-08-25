"""Repository and worker support for transactional webhook outbox processing."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retrypay.domain.models import EventSource
from retrypay.storage.models import WebhookOutboxJobModel


class WebhookOutboxRepository:
    """Async repository for managing durable transactional outbox jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_outbox_job(
        self,
        provider_event_id: str,
        source: str = EventSource.LOCAL_SIMULATION.value,
        max_attempts: int = 3,
    ) -> WebhookOutboxJobModel:
        """Atomically persist a pending outbox job for a webhook event."""
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)

        job = WebhookOutboxJobModel(
            job_id=job_id,
            source=source,
            provider_event_id=provider_event_id,
            status="PENDING",
            attempts=0,
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def claim_unprocessed_jobs(
        self, worker_id: str, limit: int = 10
    ) -> Sequence[WebhookOutboxJobModel]:
        """Claim PENDING or expired locked outbox jobs for processing."""
        now = datetime.now(UTC)
        stmt = (
            select(WebhookOutboxJobModel)
            .where(
                WebhookOutboxJobModel.status.in_(["PENDING", "FAILED"]),
                WebhookOutboxJobModel.attempts < WebhookOutboxJobModel.max_attempts,
            )
            .order_by(WebhookOutboxJobModel.created_at.asc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        jobs = res.scalars().all()

        for job in jobs:
            job.status = "PROCESSING"
            job.attempts += 1
            job.locked_at = now
            job.locked_by = worker_id
            job.updated_at = now

        if jobs:
            await self._session.flush()

        return jobs

    async def mark_completed(self, job_id: str) -> None:
        """Mark an outbox job as successfully completed."""
        stmt = select(WebhookOutboxJobModel).where(WebhookOutboxJobModel.job_id == job_id)
        res = await self._session.execute(stmt)
        job = res.scalar_one_or_none()
        if job:
            job.status = "COMPLETED"
            job.locked_at = None
            job.locked_by = None
            job.updated_at = datetime.now(UTC)
            await self._session.flush()

    async def mark_failed(self, job_id: str, error_reason: str) -> None:
        """Mark an outbox job failed with retry metadata."""
        stmt = select(WebhookOutboxJobModel).where(WebhookOutboxJobModel.job_id == job_id)
        res = await self._session.execute(stmt)
        job = res.scalar_one_or_none()
        if job:
            job.status = "FAILED"
            job.last_error = error_reason
            job.locked_at = None
            job.locked_by = None
            job.updated_at = datetime.now(UTC)
            await self._session.flush()

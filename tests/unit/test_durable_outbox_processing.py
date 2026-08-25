"""Unit tests for durable transactional outbox pattern and worker reliability."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.storage.models import WebhookOutboxJobModel
from retrypay.storage.repositories.outbox import WebhookOutboxRepository


@pytest.mark.asyncio
async def test_outbox_job_created_atomically(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Outbox job is created with status PENDING in database transaction."""
    async with test_session_factory() as session:
        repo = WebhookOutboxRepository(session)
        job = await repo.create_outbox_job("evt_test_outbox_1", source="RAZORPAY_TEST_MODE")
        await session.commit()
        job_id = job.job_id

    async with test_session_factory() as session:
        res = await session.execute(
            select(WebhookOutboxJobModel).where(WebhookOutboxJobModel.job_id == job_id)
        )
        saved = res.scalar_one_or_none()
        assert saved is not None
        assert saved.status == "PENDING"
        assert saved.provider_event_id == "evt_test_outbox_1"
        assert saved.source == "RAZORPAY_TEST_MODE"


@pytest.mark.asyncio
async def test_worker_claims_and_completes_outbox_job(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Outbox worker claims pending outbox job and marks it COMPLETED."""
    async with test_session_factory() as session:
        repo = WebhookOutboxRepository(session)
        await repo.create_outbox_job("evt_test_outbox_2", source="RAZORPAY_TEST_MODE")
        await session.commit()

    # Worker claims job
    async with test_session_factory() as session:
        repo = WebhookOutboxRepository(session)
        claimed = await repo.claim_unprocessed_jobs(worker_id="worker_instance_1")
        assert len(claimed) == 1
        assert claimed[0].provider_event_id == "evt_test_outbox_2"
        assert claimed[0].status == "PROCESSING"
        assert claimed[0].locked_by == "worker_instance_1"
        await repo.mark_completed(claimed[0].job_id)
        await session.commit()

    async with test_session_factory() as session:
        res = await session.execute(
            select(WebhookOutboxJobModel).where(
                WebhookOutboxJobModel.provider_event_id == "evt_test_outbox_2"
            )
        )
        final_job = res.scalar_one_or_none()
        assert final_job is not None
        assert final_job.status == "COMPLETED"


@pytest.mark.asyncio
async def test_unprocessed_outbox_job_survives_worker_restart(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Outbox job with status FAILED can be re-claimed and processed after worker restart."""
    async with test_session_factory() as session:
        repo = WebhookOutboxRepository(session)
        job = await repo.create_outbox_job("evt_test_outbox_3", source="RAZORPAY_TEST_MODE")
        await session.commit()
        job_id = job.job_id

    # Worker 1 fails job
    async with test_session_factory() as session:
        repo = WebhookOutboxRepository(session)
        claimed = await repo.claim_unprocessed_jobs(worker_id="worker_1")
        await repo.mark_failed(claimed[0].job_id, error_reason="Transient network glitch")
        await session.commit()

    # Worker 2 restarts and re-claims failed job for retry
    async with test_session_factory() as session:
        repo = WebhookOutboxRepository(session)
        reclaimed = await repo.claim_unprocessed_jobs(worker_id="worker_2_restart")
        assert len(reclaimed) == 1
        assert reclaimed[0].job_id == job_id
        assert reclaimed[0].attempts == 2
        await repo.mark_completed(reclaimed[0].job_id)
        await session.commit()

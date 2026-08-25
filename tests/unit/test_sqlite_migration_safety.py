"""Unit tests verifying SQLite migration conflict detection and safe non-destructive halting."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from retrypay.storage.database import init_db


@pytest.mark.asyncio
async def test_migration_halts_safely_on_duplicate_order_ids() -> None:
    """Migration halts cleanly with RuntimeError if duplicate order IDs exist."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )

    # 1. Manually create orders table without unique constraint
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE orders ("
                "order_id VARCHAR(128) PRIMARY KEY, "
                "source VARCHAR(32) NOT NULL, "
                "amount_paise BIGINT NOT NULL, "
                "currency VARCHAR(3) NOT NULL, "
                "status VARCHAR(32) NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL);"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO orders "
                "(order_id, source, amount_paise, currency, status, created_at, updated_at) "
                "VALUES ('ord_dup_1', 'LOCAL_SIMULATION', 1000, 'INR', 'attempted', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);"
            )
        )

    # 2. Test duplicate provider_event_id on webhook_events table
    engine2 = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine2.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE webhook_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "provider_event_id VARCHAR(128) NOT NULL, "
                "source VARCHAR(32) NOT NULL, "
                "event_type VARCHAR(64) NOT NULL, "
                "received_at DATETIME NOT NULL, "
                "signature_verification_status VARCHAR(32) NOT NULL, "
                "payload_sha256 VARCHAR(64) NOT NULL, "
                "processing_status VARCHAR(32) NOT NULL);"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO webhook_events "
                "(provider_event_id, source, event_type, received_at, "
                "signature_verification_status, payload_sha256, processing_status) "
                "VALUES ('evt_dup_123', 'LOCAL_SIMULATION', 'payment.failed', "
                "CURRENT_TIMESTAMP, 'valid', 'hash1', 'PROCESSED');"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO webhook_events "
                "(provider_event_id, source, event_type, received_at, "
                "signature_verification_status, payload_sha256, processing_status) "
                "VALUES ('evt_dup_123', 'LOCAL_SIMULATION', 'payment.failed', "
                "CURRENT_TIMESTAMP, 'valid', 'hash2', 'PROCESSED');"
            )
        )

    with pytest.raises(RuntimeError) as excinfo:
        await init_db(engine2)

    assert "MIGRATION HALTED FOR SAFETY" in str(excinfo.value)
    assert "Webhook events has 1 duplicate key groups" in str(excinfo.value)

    await engine.dispose()
    await engine2.dispose()


@pytest.mark.asyncio
async def test_migration_idempotent_when_run_twice() -> None:
    """Running init_db twice on a clean database succeeds without error."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    await init_db(engine)
    await init_db(engine)  # Second run
    await engine.dispose()

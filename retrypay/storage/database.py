"""Async database engine, session management, and schema initialization."""

import os
from typing import Any
from urllib.parse import parse_qs, urlencode

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from retrypay.config import Settings
from retrypay.storage.models import Base

# ---------------------------------------------------------------------------
# Process-level immutable database identity
# ---------------------------------------------------------------------------
_process_canonical_db_target: str | None = None
_process_masked_db_target: str | None = None

# SQLite URI query parameters that change database semantics and must be
# preserved in the canonical identity.  Non-semantic params like
# check_same_thread are stripped.
_SQLITE_SEMANTIC_PARAMS = frozenset({"mode", "cache", "immutable", "vfs"})


def resolve_canonical_db_target(database_url: str) -> str:
    """Normalize a database connection string into a canonical identity string.

    Normalizes:
    - SQLite URI scheme prefixes (sqlite+aiosqlite:///, sqlite:///)
    - Relative vs absolute path resolution
    - Forward vs backward slash direction
    - './' prefixes
    - Query parameter ordering (semantic params only)

    Semantic SQLite query parameters (mode, cache, immutable, vfs) are
    preserved in sorted order.  Non-semantic parameters are stripped.
    """
    if not database_url or not database_url.strip():
        raise ValueError("DATABASE_URL must not be empty.")

    raw = database_url.strip()

    # --- Split off query string ---
    if "?" in raw:
        url_part, qs_part = raw.split("?", 1)
        parsed_qs = parse_qs(qs_part, keep_blank_values=True)
        semantic = {
            k: sorted(v)
            for k, v in sorted(parsed_qs.items())
            if k.lower() in _SQLITE_SEMANTIC_PARAMS
        }
        qs_canonical = urlencode(semantic, doseq=True) if semantic else ""
    else:
        url_part = raw
        qs_canonical = ""

    # --- Extract path after scheme ---
    if "://" in url_part:
        path_part = url_part.split("://", 1)[1]
    else:
        path_part = url_part

    # Strip leading slashes (SQLite triple-slash)
    path_part = path_part.lstrip("/")

    # Normalize slashes
    path_part = path_part.replace("\\", "/")

    # Strip ./
    if path_part.startswith("./"):
        path_part = path_part[2:]

    # Handle :memory: and empty
    if not path_part or path_part == ":memory:":
        canonical = path_part.lower()
    else:
        canonical = os.path.abspath(path_part).replace("\\", "/").lower()

    if qs_canonical:
        canonical = f"{canonical}?{qs_canonical}"

    return canonical


def get_masked_db_target(database_url: str) -> str:
    """Extract only the database filename for safe diagnostic health output.

    Never exposes absolute paths, credentials, query parameters, or secrets.
    """
    if not database_url or not database_url.strip():
        return "unknown"
    clean = database_url.split("?")[0].strip()
    raw_path = clean.split("://")[-1].replace("\\", "/").rstrip("/")
    filename = os.path.basename(raw_path)
    return filename or "unknown"


def verify_database_routing_preflight(settings: Settings) -> str:
    """Register and enforce the process-level immutable database target.

    On first call: binds the canonical target and masked name as the
    process identity.  On subsequent calls: raises RuntimeError if the
    resolved target differs from the startup-bound identity.

    When ``RETRYPAY_EXPECTED_DATABASE_TARGET`` is set in Settings, also
    validates that the canonical target matches the expected target.
    """
    global _process_canonical_db_target, _process_masked_db_target

    target = resolve_canonical_db_target(settings.DATABASE_URL)

    # --- Cross-process expected-target validation ---
    expected_raw = getattr(settings, "RETRYPAY_EXPECTED_DATABASE_TARGET", None)
    if expected_raw and expected_raw.strip():
        expected_canonical = resolve_canonical_db_target(expected_raw)
        if target != expected_canonical:
            raise RuntimeError(
                "DATABASE TARGET MISMATCH: The resolved DATABASE_URL target does not match "
                f"RETRYPAY_EXPECTED_DATABASE_TARGET. "
                f"Resolved='{get_masked_db_target(settings.DATABASE_URL)}', "
                f"Expected='{get_masked_db_target(expected_raw)}'. "
                "All API, worker, and CLI processes must use the same database."
            )

    # --- Process immutability enforcement ---
    if _process_canonical_db_target is None:
        _process_canonical_db_target = target
        _process_masked_db_target = get_masked_db_target(settings.DATABASE_URL)
    elif _process_canonical_db_target != target:
        raise RuntimeError(
            "DATABASE_URL mutation detected: process restart required. "
            f"Startup target='{_process_masked_db_target}', "
            f"current='{get_masked_db_target(settings.DATABASE_URL)}'."
        )

    return target


def get_startup_masked_db_target() -> str:
    """Return the masked database filename bound at process startup.

    Returns 'not_initialized' if preflight has not yet run.
    """
    return _process_masked_db_target or "not_initialized"


def reset_process_db_target_for_testing() -> None:
    """Reset process-level DB target tracker.  Unit testing only."""
    global _process_canonical_db_target, _process_masked_db_target
    _process_canonical_db_target = None
    _process_masked_db_target = None


def get_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine with SQLite concurrency optimizations."""
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}

    engine = create_async_engine(
        database_url,
        echo=False,
        connect_args=connect_args,
    )

    if is_sqlite:
        # Enable WAL mode and foreign key constraints on SQLite connections
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async sessionmaker bound to the given engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def init_db(engine: AsyncEngine) -> None:
    """Create or upgrade database tables, backfill source, and ensure unique indexes exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Check and perform non-destructive column upgrades for existing tables
        tables_to_upgrade = [
            "webhook_events",
            "orders",
            "payment_attempts",
            "recovery_cases",
            "recovery_actions",
            "payment_links",
            "notification_logs",
            "budget_reservations",
            "audit_events",
        ]

        for table in tables_to_upgrade:
            # Check existing columns via PRAGMA
            cursor_res = await conn.execute(text(f"PRAGMA table_info({table});"))
            cols = [row[1] for row in cursor_res.fetchall()]
            if cols and "source" not in cols:
                alter_sql = (
                    f"ALTER TABLE {table} ADD COLUMN source VARCHAR(32) "
                    "DEFAULT 'LOCAL_SIMULATION' NOT NULL;"
                )
                await conn.execute(text(alter_sql))
                await conn.execute(
                    text(f"UPDATE {table} SET source = 'LOCAL_SIMULATION' WHERE source IS NULL;")
                )

        # Check if audit_events has provider_event_id column
        cursor_res = await conn.execute(text("PRAGMA table_info(audit_events);"))
        audit_cols = [row[1] for row in cursor_res.fetchall()]
        if audit_cols and "provider_event_id" not in audit_cols:
            alter_sql = "ALTER TABLE audit_events ADD COLUMN provider_event_id VARCHAR(128);"
            await conn.execute(text(alter_sql))
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_audit_events_provider_event_id "
                    "ON audit_events(provider_event_id);"
                )
            )

        duplicate_checks: list[tuple[str, str, str]] = [
            ("webhook_events", "source, provider_event_id", "Webhook events"),
            ("orders", "source, order_id", "Orders"),
            ("payment_attempts", "source, payment_id", "Payment attempts"),
            ("payment_links", "source, provider_link_id", "Payment links (provider_link_id)"),
            ("payment_links", "source, reference_id", "Payment links (reference_id)"),
        ]

        conflicts: list[str] = []
        for tbl_name, col_names, label in duplicate_checks:
            check_sql = (
                f"SELECT {col_names}, COUNT(*) FROM {tbl_name} "
                f"GROUP BY {col_names} HAVING COUNT(*) > 1;"
            )
            res = await conn.execute(text(check_sql))
            dups = res.fetchall()
            if dups:
                conflicts.append(f"{label} has {len(dups)} duplicate key groups: {dups[:3]}")

        active_case_check = (
            "SELECT source, order_id, COUNT(*) FROM recovery_cases "
            "WHERE closed_at IS NULL GROUP BY source, order_id HAVING COUNT(*) > 1;"
        )
        res_cases = await conn.execute(text(active_case_check))
        dup_cases = res_cases.fetchall()
        if dup_cases:
            conflicts.append(f"Recovery cases has multiple active cases per order: {dup_cases[:3]}")

        if conflicts:
            conflict_msg = "; ".join(conflicts)
            raise RuntimeError(
                "MIGRATION HALTED FOR SAFETY: Duplicate composite identifiers detected "
                "before index creation. "
                f"Conflicts: {conflict_msg}. Database records preserved without deletion."
            )

        # Ensure source-partitioned unique indexes exist
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_source_provider_event_id "
                "ON webhook_events(source, provider_event_id);"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_source_order_id ON orders(source, order_id);"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_source_payment_id "
                "ON payment_attempts(source, payment_id);"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_source_provider_link_id "
                "ON payment_links(source, provider_link_id);"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_source_reference_id "
                "ON payment_links(source, reference_id);"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_one_active_recovery_case_per_order "
                "ON recovery_cases(source, order_id) WHERE closed_at IS NULL;"
            )
        )

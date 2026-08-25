"""FastAPI dependency injection providers."""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retrypay.adapters.razorpay.verifier import WebhookVerifier
from retrypay.config import Settings, get_settings
from retrypay.policy.engine import PolicyEngine
from retrypay.storage.database import (
    get_engine,
    get_session_factory,
    verify_database_routing_preflight,
)

__all__ = [
    "Settings",
    "get_settings",
    "get_configured_session_factory",
    "get_db_session",
    "get_webhook_verifier",
    "get_policy_engine",
]

# Global singleton storage for session factory
_session_factory: async_sessionmaker[AsyncSession] | None = None
_policy_engine: PolicyEngine | None = None


def get_configured_session_factory(
    settings: Settings = Depends(get_settings),
) -> async_sessionmaker[AsyncSession]:
    """Provide or initialize the async session factory.

    Enforces process database immutability via preflight check.
    """
    global _session_factory
    verify_database_routing_preflight(settings)
    if _session_factory is None:
        engine = get_engine(settings.DATABASE_URL)
        _session_factory = get_session_factory(engine)
    return _session_factory


async def get_db_session(
    factory: async_sessionmaker[AsyncSession] = Depends(get_configured_session_factory),
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session within a transaction context."""
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_webhook_verifier(
    settings: Settings = Depends(get_settings),
) -> WebhookVerifier:
    """Provide a configured Razorpay WebhookVerifier instance."""
    return WebhookVerifier(settings.RAZORPAY_WEBHOOK_SECRET)


def get_policy_engine() -> PolicyEngine:
    """Provide a singleton PolicyEngine instance."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = PolicyEngine()
    return _policy_engine

"""Pytest test configuration and global fixtures for ReTryPay."""

import hashlib
import hmac
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from retrypay.api.dependencies import get_configured_session_factory
from retrypay.config import AppEnvironment, Settings, get_settings
from retrypay.storage.database import init_db, reset_process_db_target_for_testing

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "webhooks"


@pytest.fixture(autouse=True)
def reset_db_process_target() -> Generator[None, None, None]:
    """Reset process DB target identity before and after every test function in pytest."""
    reset_process_db_target_for_testing()
    yield
    reset_process_db_target_for_testing()


@pytest.fixture
def default_test_settings() -> Settings:
    """Provide standard default test settings."""
    return Settings(
        RETRYPAY_ENV=AppEnvironment.TEST,
        LLM_ENABLED=False,
        RETRYPAY_RETAIN_RAW_WEBHOOK_PAYLOAD=False,
        RAZORPAY_KEY_ID="rzp_test_fixture_key_id",
        RAZORPAY_KEY_SECRET="rzp_test_fixture_secret",
        RAZORPAY_WEBHOOK_SECRET="retrypay_test_webhook_secret_key_123",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.fixture
async def test_session_factory(
    default_test_settings: Settings,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Provide an isolated in-memory SQLite session factory for integration tests.

    Uses StaticPool so that all connections share the same in-memory database,
    allowing the app and verification queries to see the same data.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await init_db(engine)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def test_client(
    default_test_settings: Settings,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient configured with test in-memory database.

    Creates a FastAPI app without lifespan to avoid creating a second
    in-memory SQLite engine that would be separate from the test's StaticPool.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from retrypay.api.routes.dashboard import router as dashboard_router
    from retrypay.api.routes.health import router as health_router
    from retrypay.api.routes.metrics import router as metrics_router
    from retrypay.api.routes.simulator import router as simulator_router
    from retrypay.api.routes.webhooks import router as webhooks_router

    test_app = FastAPI(title="ReTryPay Test")
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    test_app.include_router(health_router)
    test_app.include_router(webhooks_router)
    test_app.include_router(dashboard_router)
    test_app.include_router(metrics_router)
    test_app.include_router(simulator_router)

    test_app.dependency_overrides[get_settings] = lambda: default_test_settings
    test_app.dependency_overrides[get_configured_session_factory] = lambda: test_session_factory

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def compute_signature(
    payload_bytes: bytes, secret: str = "retrypay_test_webhook_secret_key_123"
) -> str:
    """Helper to compute valid Razorpay HMAC-SHA256 signature for test payloads."""
    return hmac.new(secret.encode("utf-8"), msg=payload_bytes, digestmod=hashlib.sha256).hexdigest()


def load_fixture(fixture_name: str) -> bytes:
    """Load fixture JSON file content as bytes."""
    path = FIXTURES_DIR / fixture_name
    return path.read_bytes()

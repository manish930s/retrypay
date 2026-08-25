"""FastAPI application factory and lifespan configuration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from retrypay.api.routes.checkout import router as checkout_router
from retrypay.api.routes.dashboard import router as dashboard_router
from retrypay.api.routes.health import router as health_router
from retrypay.api.routes.metrics import router as metrics_router
from retrypay.api.routes.simulator import router as simulator_router
from retrypay.api.routes.webhooks import router as webhooks_router
from retrypay.config import Settings, get_settings
from retrypay.storage.database import (
    get_engine,
    init_db,
    verify_database_routing_preflight,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context initializing database schemas on application startup."""
    settings = get_settings()
    verify_database_routing_preflight(settings)
    engine = get_engine(settings.DATABASE_URL)
    await init_db(engine)
    yield
    await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="ReTryPay API",
        description="Bounded checkout payment recovery system for Razorpay Test Mode",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Enable CORS for local Vite dashboard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount routers
    app.include_router(health_router)
    app.include_router(webhooks_router)
    app.include_router(dashboard_router)
    app.include_router(metrics_router)
    app.include_router(simulator_router)
    app.include_router(checkout_router)

    return app


app = create_app()

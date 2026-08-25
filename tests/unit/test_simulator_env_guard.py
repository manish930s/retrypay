"""Unit tests verifying strict environment protection on the internal simulator endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from retrypay.api.app import create_app
from retrypay.api.dependencies import get_settings
from retrypay.config import AppEnvironment, Settings


@pytest.mark.asyncio
async def test_simulator_disabled_in_demo_environment() -> None:
    """Simulator GET /scenarios and POST /trigger return HTTP 403 Forbidden in demo environment."""
    demo_settings = Settings(
        RETRYPAY_ENV=AppEnvironment.DEMO,
        RAZORPAY_KEY_ID="rzp_test_demo_key",
        RAZORPAY_KEY_SECRET="demo_secret",
        RAZORPAY_WEBHOOK_SECRET="whsec_demo",
    )
    app = create_app(demo_settings)
    app.dependency_overrides[get_settings] = lambda: demo_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/api/v1/simulator/scenarios")
        assert r1.status_code == 403
        assert "Simulator is disabled outside of test environment" in r1.json()["detail"]

        r2 = await client.post(
            "/api/v1/simulator/trigger", json={"scenario_id": "2_eligible_outreach_flow"}
        )
        assert r2.status_code == 403
        assert "Simulator is disabled outside of test environment" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_simulator_disabled_in_development_environment() -> None:
    """Simulator endpoints return HTTP 403 Forbidden in development environment."""
    dev_settings = Settings(
        RETRYPAY_ENV=AppEnvironment.DEVELOPMENT,
        RAZORPAY_KEY_ID="rzp_test_dev_key",
        RAZORPAY_KEY_SECRET="dev_secret",
        RAZORPAY_WEBHOOK_SECRET="whsec_dev",
    )
    app = create_app(dev_settings)
    app.dependency_overrides[get_settings] = lambda: dev_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/api/v1/simulator/scenarios")
        assert r1.status_code == 403

        r2 = await client.post(
            "/api/v1/simulator/trigger", json={"scenario_id": "2_eligible_outreach_flow"}
        )
        assert r2.status_code == 403

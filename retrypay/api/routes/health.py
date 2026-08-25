"""Health and liveness endpoints for operational monitoring."""

from typing import Any

from fastapi import APIRouter, Depends

from retrypay.config import Settings, get_settings
from retrypay.storage.database import get_startup_masked_db_target

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", status_code=200)
async def health_check(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Return operational health status and active configuration modes."""
    return {
        "status": "healthy",
        "environment": settings.RETRYPAY_ENV.value,
        "policy_version": settings.RETRYPAY_POLICY_VERSION,
        "llm_enabled": settings.LLM_ENABLED,
        "database_target": get_startup_masked_db_target(),
    }

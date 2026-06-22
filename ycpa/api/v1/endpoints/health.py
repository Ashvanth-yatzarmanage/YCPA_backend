import logging
from datetime import datetime, timezone

import psutil
from fastapi import APIRouter, status
from sqlalchemy import text

from ycpa.core.auth.dependencies import StaffUser
from ycpa.core.config import get_settings
from ycpa.core.database.dependencies import DatabaseSession
from ycpa.core.database.session import check_database_health

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["Health"])
settings = get_settings()


@router.get("", summary="Liveness probe", status_code=status.HTTP_200_OK)
async def health():
    return {
        "success":   True,
        "status":    "healthy",
        "service":   settings.APP_NAME,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready", summary="Readiness probe (includes DB)", status_code=status.HTTP_200_OK)
async def readiness_check(session: DatabaseSession):
    checks = {"timestamp": datetime.now(timezone.utc).isoformat()}

    try:
        result = await session.execute(text("SELECT 1"))
        result.scalar()
        checks["database"] = "healthy"
    except Exception as e:
        logger.error("Database health check failed", extra={"error": str(e)}, exc_info=True)
        checks["database"]       = "unhealthy"
        checks["database_error"] = str(e)[:100]
        return {
            "success": False,
            "status":  "unhealthy",
            "service": settings.APP_NAME,
            "checks":  checks,
        }

    return {
        "success": True,
        "status":  "ready",
        "service": settings.APP_NAME,
        "checks":  checks,
    }


@router.get("/detailed", summary="Detailed health metrics", status_code=status.HTTP_200_OK)
async def detailed_health(session: DatabaseSession, current_user: StaffUser):
    checks = {"timestamp": datetime.now(timezone.utc).isoformat()}

    try:
        await session.execute(text("SELECT 1"))
        checks["database"]      = "healthy"
        checks["database_pool"] = await check_database_health()
    except Exception as e:
        logger.error("Database health check failed", extra={"error": str(e)}, exc_info=True)
        checks["database"]       = "unhealthy"
        checks["database_error"] = str(e)[:100]

    try:
        checks["system"] = {
            "cpu_percent":    psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent":   psutil.disk_usage("/").percent,
        }
    except Exception as e:
        logger.warning(f"Failed to get system metrics: {e}")
        checks["system"] = "unavailable"

    is_healthy = checks.get("database") == "healthy"

    return {
        "success":     is_healthy,
        "status":      "healthy" if is_healthy else "degraded",
        "service":     settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "version":     "1.0.0",
        "checks":      checks,
    }
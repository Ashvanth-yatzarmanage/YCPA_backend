import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ycpa.core.auth.jwt_verifier import get_jwt_verifier
from ycpa.core.config import get_settings
from ycpa.core.database.engine import silence_sqlalchemy
from ycpa.core.database.session import check_database_health, close_db, init_db
from ycpa.core.logger.visual_logger import VisualLogger, console

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):

    silence_sqlalchemy()

    console.clear()
    VisualLogger.banner(settings.APP_NAME)
    VisualLogger.config_table(settings)

    VisualLogger.step("Initializing database", "running")
    await init_db()
    VisualLogger.step("Database initialized", "success")

    VisualLogger.step("Running database health check", "running")
    health = await check_database_health()
    logger.info(
        f"DB health — PostgreSQL: {health['postgresql']['status']} | "
    )

    if health.get("status") == "degraded":
        VisualLogger.panel(
            f"PostgreSQL: {health['postgresql']['status']}\n"
            "Database Health Check Failed", "red"
        )
        raise RuntimeError("One or more databases are unhealthy on startup")
    VisualLogger.step("Database health check passed", "success")

    VisualLogger.step("Warming JWKS cache", "running")
    if settings.ENVIRONMENT == "local":
        try:
            await get_jwt_verifier().preload()
            VisualLogger.step("JWKS cache ready", "success")
        except Exception as e:
            logger.warning(f"JWKS preload skipped in local env: {e}")
            VisualLogger.step("JWKS cache skipped (local mode)", "success")
    else:
        await get_jwt_verifier().preload()
        VisualLogger.step("JWKS cache ready", "success")

    VisualLogger.panel(
        "[cyan]Docs:[/cyan]   http://localhost:8000/docs\n"
        "[cyan]Health:[/cyan] http://localhost:8000/health",
        "Startup Complete", "green"
    )
    console.print()

    yield

    VisualLogger.panel("Shutting down...", "Shutdown", "yellow")
    VisualLogger.step("Closing database connections", "running")
    await close_db()
    VisualLogger.step("Database connections closed", "success")
    VisualLogger.panel("Goodbye!", "Clean Exit", "green")

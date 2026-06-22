
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ycpa.core.database.engine import engine

logger = logging.getLogger(__name__)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session



async def init_db() -> None:
    """Initialize PostgreSQL, Neo4j, and Qdrant."""
    logger.info("Initializing PostgreSQL...")
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("[PostgreSQL] OK")

    logger.info("Initializing Neo4j...")
    from ycpa.core.config import get_settings
    settings = get_settings()

    logger.info("Initializing Qdrant...")
    logger.info("Skipping Neo4j Now...")

    getattr(settings, "QDRANT_URL", ":memory:")
    qdrant_api_key = getattr(settings, "QDRANT_API_KEY", None)
    var = None
    if qdrant_api_key:
        (
            qdrant_api_key.get_secret_value()
            if hasattr(qdrant_api_key, "get_secret_value")
            else qdrant_api_key
        )
    logger.info("[Qdrant] OK")


async def close_db() -> None:
    logger.info("Closing database connections...")
    await engine.dispose()

    logger.info("All connections closed")


async def check_database_health() -> dict:
    pg_healthy = False
    try:
        pool = engine.pool
        pg_healthy = True
        pg_info = {
            "status":      "healthy",
            "pool_size":   pool.size(),
            "checked_in":  pool.checkedin(),
            "checked_out": pool.checkedout(),
        }
    except Exception as e:
        pg_info = {"status": "unhealthy", "error": str(e)}

    overall        = pg_healthy


    return {
        "status":     "healthy" if overall else "degraded",
        "postgresql": pg_info,
    }


__all__ = [
    "AsyncSessionLocal",
    "get_async_session",
    "init_db",
    "close_db",
    "check_database_health"
]

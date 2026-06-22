import logging
import ssl
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from ycpa.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_SQLALCHEMY_LOGGERS = (
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlalchemy.engine.Engine",
    "sqlalchemy.pool",
    "sqlalchemy.dialects",
    "sqlalchemy.orm",
)


class _DropAll(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


def silence_sqlalchemy() -> None:
    if settings.ENVIRONMENT == "development":
        return

    drop = _DropAll("sqlalchemy_silence")

    for name in _SQLALCHEMY_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.propagate = False
        lg.handlers.clear()
        lg.addHandler(logging.NullHandler())
        lg.filters = [f for f in lg.filters if not isinstance(f, _DropAll)]
        lg.addFilter(drop)


def create_database_engine() -> AsyncEngine:
    connect_args: dict[str, Any] = {
        "server_settings": {
            "application_name": settings.APP_NAME,
        },
        "command_timeout": 30,
        "timeout": 30,
        "prepared_statement_cache_size": 0,
        "statement_cache_size": 0,
    }

    if settings.DB_USE_SSL:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_context
    else:
        connect_args["ssl"] = False

    logger.info(f"Database: {settings.ENVIRONMENT} mode (AsyncAdaptedQueuePool)")
    return create_async_engine(
        str(settings.DATABASE_URL),
        echo=settings.DB_ECHO,
        poolclass=AsyncAdaptedQueuePool,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=settings.DB_POOL_PRE_PING,
        pool_recycle=settings.DB_POOL_RECYCLE,
        connect_args=connect_args,
    )


engine: AsyncEngine = create_database_engine()

silence_sqlalchemy()

# REMOVED: before_cursor_execute / after_cursor_execute sync event listeners
# They caused "cannot perform operation: another operation is in progress"
# on asyncpg because sync SQLAlchemy events are not safe on async engines
# when concurrent requests share a pooled connection.
# Slow query logging is handled by performance_middleware instead.

__all__ = ["engine", "silence_sqlalchemy"]
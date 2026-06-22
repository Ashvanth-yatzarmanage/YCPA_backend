import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@asynccontextmanager
async def transaction(session: AsyncSession):

    try:
        yield session
        await session.commit()
        logger.debug("Transaction committed successfully")

    except Exception as e:
        await session.rollback()
        logger.error(f"Transaction rolled back due to error: {e}")
        raise
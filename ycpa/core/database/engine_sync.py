from sqlalchemy import create_engine

from ycpa.core.config import get_settings

settings = get_settings()

engine_sync = create_engine(
    str(settings.DATABASE_URL_SYNC),
    pool_pre_ping=True,
)


settings = get_settings()

print("settings:")
print(settings)
print("engine_sync:")
print(engine_sync)
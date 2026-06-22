from ycpa.core.config.base import BaseAppSettings


class LocalSettings(BaseAppSettings):
    ENVIRONMENT: str = "local"
    DEBUG: bool = True
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

class DevelopmentSettings(BaseAppSettings):
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10


class StagingSettings(BaseAppSettings):
    ENVIRONMENT: str = "staging"
    DEBUG: bool = False
    DB_USE_SSL: bool = True

# class ProductionSettings(BaseAppSettings):
#     ENVIRONMENT: str = "production"
#     DEBUG: bool = False
#     DB_POOL_SIZE: int = max(20, multiprocessing.cpu_count() * 5)
#     DB_MAX_OVERFLOW: int = max(40, multiprocessing.cpu_count() * 10)
#     DB_USE_SSL: bool = True
#     DB_ECHO: bool = False

class ProductionSettings(BaseAppSettings):
    ENVIRONMENT: str = "production"
    DEBUG: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_USE_SSL: bool = True
    DB_ECHO: bool = False
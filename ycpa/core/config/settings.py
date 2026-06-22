import os
from functools import lru_cache
from typing import Type  # noqa: UP035

from ycpa.core.config.base import BaseAppSettings
from ycpa.core.config.environments import (
    DevelopmentSettings,
    LocalSettings,
    ProductionSettings,
    StagingSettings,
)

ENVIRONMENT_MAP: dict[str, Type[BaseAppSettings]] = {
    "local":       LocalSettings,
    "development": DevelopmentSettings,
    "staging":     StagingSettings,
    "production":  ProductionSettings,
}


@lru_cache
def get_settings() -> BaseAppSettings:
    env = os.getenv("ENVIRONMENT", "local").lower()
    settings_class = ENVIRONMENT_MAP.get(env)

    if not settings_class:
        raise ValueError(
            f"Invalid ENVIRONMENT: {env}. "
            f"Must be one of: {', '.join(ENVIRONMENT_MAP.keys())}"
        )

    return settings_class()

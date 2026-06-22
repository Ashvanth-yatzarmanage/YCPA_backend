import logging

from fastapi import FastAPI

from ycpa.api.v1.router import api_router
from ycpa.core.config import get_settings
from ycpa.core.error_handlers import register_exception_handlers
from ycpa.core.lifespan import lifespan
from ycpa.core.logger import VisualLogger, setup_logging
from ycpa.middleware.registry import register_middleware

settings = get_settings()

setup_logging()
if settings.ENVIRONMENT == "production":
    logging.getLogger("sqlalchemy.engine").disabled = True

logger = logging.getLogger(__name__)
enable_docs = settings.DEBUG or settings.ENVIRONMENT != "production"

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if enable_docs else None,
    redoc_url="/redoc" if enable_docs else None,
    openapi_url="/openapi.json" if enable_docs else None,
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "persistAuthorization": True,
    },
)

middleware_manifest = register_middleware(app, settings)
VisualLogger.middleware_table(middleware_manifest)
register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

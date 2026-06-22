from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from ycpa.core.config.base import BaseAppSettings
from ycpa.middleware.correlation_middleware import CorrelationIdMiddleware
from ycpa.middleware.logging_middleware import LoggingMiddleware
from ycpa.middleware.performance_middleware import PerformanceMonitoringMiddleware
from ycpa.middleware.security_middleware import (
    RateLimitMiddleware,
    RequestValidationMiddleware,
    SecurityHeadersMiddleware,
)


def register_middleware(app: FastAPI, settings: BaseAppSettings) -> list[dict]:
    manifest = []

    def add(mw_class, name: str, status: str, **kwargs):
        app.add_middleware(mw_class, **kwargs)
        manifest.append({"name": name, "status": status})

    add(PerformanceMonitoringMiddleware,
        "[Performance] Monitor", "[green]Threshold: 1.0s[/green]",
        slow_request_threshold=1.0)
    add(LoggingMiddleware,
        "[Logging] Request Logging", "[green]Active[/green]")
    add(CorrelationIdMiddleware,
        "[Tracking] Correlation ID", "[green]Active[/green]")
    add(RequestValidationMiddleware,
        "[Validation] Request Validation", "[green]Active[/green]")
    add(RateLimitMiddleware,
        "[Security] Rate Limit", "[green]60 req/min[/green]",
        requests_per_minute=60)
    add(SecurityHeadersMiddleware,
        "[Security] Security Headers", "[green]Active[/green]")
    add(GZipMiddleware,
        "[Compression] GZip", "[green]Level 6[/green]",
        minimum_size=1000, compresslevel=6)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
        expose_headers=["X-Request-ID", "X-Correlation-ID", "X-Response-Time"],
        max_age=3600,
    )
    manifest.append({
        "name": "[Network] CORS",
        "status": f"[green]{len(settings.CORS_ORIGINS)} origin(s)[/green]"
    })
    return manifest
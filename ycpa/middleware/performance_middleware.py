import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    def __init__(
            self,
            app,
            slow_request_threshold: float = 1.0,  # seconds
            enable_metrics: bool = True
    ):
        super().__init__(app)
        self.slow_request_threshold = slow_request_threshold
        self.enable_metrics = enable_metrics

        self.metrics = {
            "request_count": 0,
            "error_count": 0,
            "slow_request_count": 0,
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        request_id = getattr(request.state, 'request_id', 'N/A')

        self.metrics["request_count"] += 1

        try:
            response = await call_next(request)

            duration = time.time() - start_time
            duration_ms = duration * 1000

            if duration > self.slow_request_threshold:
                self.metrics["slow_request_count"] += 1
                logger.warning(
                    f"Slow request detected: {request.method} {request.url.path}",
                    extra={
                        "request_id": request_id,
                        "duration_ms": duration_ms,
                        "threshold_ms": self.slow_request_threshold * 1000,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "performance_issue": True
                    }
                )

            response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

            logger.info(
                "Request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else "unknown",
                    "user_agent": request.headers.get("user-agent", "unknown"),
                    "metric_type": "request_performance"
                }
            )

            return response

        except Exception as e:
            duration = time.time() - start_time
            duration_ms = duration * 1000

            self.metrics["error_count"] += 1

            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "error": str(e),
                    "metric_type": "request_error"
                },
                exc_info=True
            )

            raise

    def get_metrics(self) -> dict:
        return self.metrics.copy()

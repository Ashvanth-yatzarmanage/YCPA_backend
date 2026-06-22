import logging
import time
from collections import defaultdict, deque
from typing import Callable, Dict  # noqa: UP035

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):


    def __init__(
            self,
            app,
            requests_per_minute: int = 60,
            burst_size: int = 10,
            cleanup_every: int = 500,
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.clients: Dict[str, deque] = defaultdict(deque)
        self._request_count = 0
        self._cleanup_every = cleanup_every

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_id = self._get_client_id(request)

        self._request_count += 1
        if self._request_count % self._cleanup_every == 0:
            self._cleanup()

        if not self._is_allowed(client_id):
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "client_id": client_id,
                    "path": request.url.path,
                    "method": request.method,
                    "security_event": "rate_limit_exceeded",
                },
            )
            return JSONResponse(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "success": False,
                    "error": {
                        "error_code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests. Please try again later.",
                        "details": {"limit": self.requests_per_minute, "window": "1 minute"},
                    },
                },
            )

        response = await call_next(request)
        return response

    def _get_client_id(self, request: Request) -> str:
        if hasattr(request.state, "user_id"):
            return f"user:{request.state.user_id}"
        if request.client:
            return f"ip:{request.client.host}"
        return "unknown"

    def _is_allowed(self, client_id: str) -> bool:
        now = time.time()
        window_start = now - 60
        requests = self.clients[client_id]

        while requests and requests[0] < window_start:
            requests.popleft()

        if len(requests) >= self.requests_per_minute:
            return False

        requests.append(now)
        return True

    def _cleanup(self) -> None:
        cutoff = time.time() - 60
        stale = [cid for cid, dq in self.clients.items() if not dq or dq[-1] < cutoff]
        for cid in stale:
            del self.clients[cid]
        if stale:
            logger.debug("Rate limiter pruned %d stale clients", len(stale))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        is_docs = request.url.path in ["/docs", "/redoc", "/openapi.json"]

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"

        for h in ("server", "x-powered-by"):
            if h in response.headers:
                del response.headers[h]

        if is_docs:
            response.headers["Content-Security-Policy"] = (
                "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:; "
                "script-src * 'unsafe-inline' 'unsafe-eval'; "
                "style-src * 'unsafe-inline'; "
                "img-src * data: blob: 'unsafe-inline'; "
                "font-src * data:; "
                "connect-src *;"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self';"
            )

        return response


class RequestValidationMiddleware(BaseHTTPMiddleware):
    SUSPICIOUS_PATTERNS = [
        "<script",
        "javascript:",
        "onerror=",
        "onload=",
        "../",
        "..\\",
        "eval(",
        "expression(",
    ]

    SKIP_VALIDATION_PATHS = ["/docs", "/redoc", "/openapi.json"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.SKIP_VALIDATION_PATHS:
            return await call_next(request)
        url_path = str(request.url.path).lower()

        for pattern in self.SUSPICIOUS_PATTERNS:
            if pattern in url_path:
                logger.warning(
                    f"Suspicious pattern detected in URL: {pattern}",
                    extra={
                        "pattern": pattern,
                        "path": request.url.path,
                        "client_ip": request.client.host if request.client else "unknown",
                        "security_event": "suspicious_pattern"
                    }
                )

                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": {
                            "error_code": "INVALID_REQUEST",
                            "message": "Invalid request detected"
                        }
                    }
                )

        user_agent = request.headers.get("user-agent", "").lower()
        if not user_agent or len(user_agent) > 500:
            logger.warning(
                "Suspicious user agent — request blocked",
                extra={
                    "user_agent": user_agent[:100],
                    "client_ip": request.client.host if request.client else "unknown",
                    "security_event": "suspicious_user_agent",
                },
            )
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": {
                        "error_code": "INVALID_REQUEST",
                        "message": "Invalid request detected",
                    },
                },
            )

        response = await call_next(request)
        return response

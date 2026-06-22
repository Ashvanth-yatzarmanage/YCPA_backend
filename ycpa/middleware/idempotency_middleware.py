import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Dict, Optional, Set, Tuple  # noqa: UP035

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class IdempotencyMiddleware(BaseHTTPMiddleware):

    def __init__(
            self,
            app,
            cache_ttl: int = 300,  # 5 minutes
            max_cache_size: int = 10000,
            enabled_methods: Optional[Set[str]] = None,
            skip_paths: Optional[Set[str]] = None
    ):
        super().__init__(app)
        self.cache_ttl = cache_ttl
        self.max_cache_size = max_cache_size

        self.enabled_methods = enabled_methods or {"POST", "PUT", "DELETE", "PATCH"}
        self.skip_paths = skip_paths or {"/health", "/docs", "/redoc", "/openapi.json"}

        self.cache: OrderedDict[str, Tuple[int, bytes, dict, float]] = OrderedDict()

        self._cleanup_task = None

        logger.info(
            f"IdempotencyMiddleware initialized: "
            f"TTL={cache_ttl}s, Methods={enabled_methods}, MaxCache={max_cache_size}"
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._should_apply(request):
            return await call_next(request)

        idempotency_key = await self._get_idempotency_key(request)

        cached = self._get_from_cache(idempotency_key)
        if cached:
            status_code, body, headers, _ = cached

            logger.info(
                f"Idempotency: Returning cached response",
                extra={
                    "idempotency_key": idempotency_key[:16],
                    "method": request.method,
                    "path": request.url.path,
                    "cache_hit": True
                }
            )

            response = Response(
                content=body,
                status_code=status_code,
                headers=headers
            )
            response.headers["X-Idempotent-Replay"] = "true"
            response.headers["X-Idempotency-Key"] = idempotency_key
            return response

        logger.debug(
            f"Idempotency: Processing new request",
            extra={
                "idempotency_key": idempotency_key[:16],
                "method": request.method,
                "path": request.url.path
            }
        )

        response = await call_next(request)

        if 200 <= response.status_code < 300:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            self._store_in_cache(
                idempotency_key,
                response.status_code,
                body,
                dict(response.headers)
            )

            response = Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
            response.headers["X-Idempotency-Key"] = idempotency_key

        return response

    def _should_apply(self, request: Request) -> bool:
        if request.method not in self.enabled_methods:
            return False

        for skip_path in self.skip_paths:
            if request.url.path.startswith(skip_path):
                return False

        return True

    async def _get_idempotency_key(self, request: Request) -> str:

        client_key = request.headers.get("Idempotency-Key")
        if client_key:
            return client_key

        user_id = getattr(request.state, 'user_id', 'anonymous')

        body_bytes = await request.body()

        key_source = (
            f"{request.method}:"
            f"{request.url.path}:"
            f"{user_id}:"
            f"{hashlib.sha256(body_bytes).hexdigest()}"
        )

        key_hash = hashlib.sha256(key_source.encode()).hexdigest()
        return f"auto_{key_hash[:32]}"

    def _get_from_cache(
            self,
            key: str
    ) -> tuple[int, bytes, dict, float] | None:
        if key not in self.cache:
            return None

        cached = self.cache[key]
        _, _, _, timestamp = cached

        if time.time() - timestamp > self.cache_ttl:
            logger.debug(f"Idempotency cache expired for key: {key[:16]}")
            del self.cache[key]
            return None

        self.cache.move_to_end(key)
        return cached

    def _store_in_cache(
            self,
            key: str,
            status_code: int,
            body: bytes,
            headers: dict
    ):
        if len(self.cache) >= self.max_cache_size:
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            logger.debug(f"Idempotency cache full, evicted: {oldest_key[:16]}")

        # Store with timestamp
        self.cache[key] = (status_code, body, headers, time.time())

        logger.debug(
            "Idempotency: Cached response",
            extra={
                "idempotency_key": key[:16],
                "cache_size": len(self.cache),
                "status_code": status_code
            }
        )

    async def cleanup_expired(self):
        while True:
            try:
                await asyncio.sleep(60)

                now = time.time()
                expired_keys = [
                    key for key, (_, _, _, timestamp) in self.cache.items()
                    if now - timestamp > self.cache_ttl
                ]

                for key in expired_keys:
                    del self.cache[key]

                if expired_keys:
                    logger.info(
                        f"Cleaned up {len(expired_keys)} expired idempotency keys"
                    )

            except Exception as e:
                logger.error(f"Error in idempotency cleanup: {e}", exc_info=True)

    def get_cache_stats(self) -> dict:
        return {
            "cache_size": len(self.cache),
            "max_cache_size": self.max_cache_size,
            "ttl_seconds": self.cache_ttl,
            "enabled_methods": list(self.enabled_methods),
        }

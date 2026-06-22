import logging
import time
from collections.abc import Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ycpa.core.database.context import clear_request_context, set_request_context

logger = logging.getLogger(__name__)
access_logger = logging.getLogger("access")


class LoggingMiddleware(BaseHTTPMiddleware):


    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id
        start_time = time.time()

        correlation_id = getattr(request.state, 'correlation_id', 'N/A')
        user_id = getattr(request.state, 'user_id', None)

        set_request_context(
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=user_id
        )

        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={"request_id": request_id}
        )
        client_host = request.client.host if request.client else "unknown"

        try:
            response = await call_next(request)

            duration = time.time() - start_time
            access_logger.info(
                f'{client_host} - "{request.method} {request.url.path}" '
                f'{response.status_code} {duration:.3f}s [{request_id}]'
            )

            logger.info(
                f"Request completed: {request.method} {request.url.path} - "
                f"Status: {response.status_code} - Duration: {duration:.3f}s",
                extra={"request_id": request_id}
            )

            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            duration = time.time() - start_time

            logger.error(
                f"Request failed: {request.method} {request.url.path} - "
                f"Error: {str(e)} - Duration: {duration:.3f}s",
                exc_info=True,
                extra={"request_id": request_id}
            )

            access_logger.error(
                f'{client_host} - "{request.method} {request.url.path}" '
                f'500 {duration:.3f}s [{request_id}] - {str(e)}'
            )

            raise

        finally:
            clear_request_context()


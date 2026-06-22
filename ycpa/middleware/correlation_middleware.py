import logging
import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    CORRELATION_ID_HEADER = "X-Correlation-ID"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get(
            self.CORRELATION_ID_HEADER,
            str(uuid.uuid4())
        )

        request.state.correlation_id = correlation_id

        old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            record.correlation_id = correlation_id
            return record

        logging.setLogRecordFactory(record_factory)

        try:
            response = await call_next(request)
            response.headers[self.CORRELATION_ID_HEADER] = correlation_id
            return response

        finally:
            logging.setLogRecordFactory(old_factory)
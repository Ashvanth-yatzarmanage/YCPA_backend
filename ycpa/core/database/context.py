import logging
from contextvars import ContextVar

logger = logging.getLogger(__name__)

request_id_ctx: ContextVar[str] = ContextVar('request_id', default='N/A')
correlation_id_ctx: ContextVar[str] = ContextVar('correlation_id', default='N/A')
user_id_ctx: ContextVar[str | None] = ContextVar('user_id', default=None)


def set_request_context(
    request_id: str,
    correlation_id: str | None = None,
    user_id: str | None = None
):
    request_id_ctx.set(request_id)
    if correlation_id:
        correlation_id_ctx.set(correlation_id)
    if user_id:
        user_id_ctx.set(user_id)


def get_request_id() -> str:
    return request_id_ctx.get()


def get_correlation_id() -> str:
    return correlation_id_ctx.get()


def get_user_id() -> str | None:
    return user_id_ctx.get()


def clear_request_context():
    request_id_ctx.set('N/A')
    correlation_id_ctx.set('N/A')
    user_id_ctx.set(None)
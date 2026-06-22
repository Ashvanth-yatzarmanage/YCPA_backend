from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class FieldError(BaseModel):
    field:   str
    message: str
    code:    str


class ProblemDetail(BaseModel):
    type:       str                      # error category string
    title:      str                      # short human summary
    status:     int                      # HTTP status code
    detail:     str                      # what went wrong (show to user)
    instance:   str                      # which endpoint
    code:       str                      # your internal machine-readable code
    request_id: str
    timestamp:  str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    errors:     list[FieldError] | None = None   # only on 422
    meta:       dict[str, Any]  | None = None    # extra context if needed


_STATUS_TITLES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def make_problem(
    *,
    status:     int,
    code:       str,
    detail:     str,
    instance:   str,
    request_id: str,
    errors:     list[FieldError] | None = None,
    meta:       dict[str, Any]   | None = None,
) -> ProblemDetail:
    return ProblemDetail(
        type=f"error:{code.lower().replace('_', '-')}",
        title=_STATUS_TITLES.get(status, "Error"),
        status=status,
        detail=detail,
        instance=instance,
        code=code,
        request_id=request_id,
        errors=errors,
        meta=meta,
    )

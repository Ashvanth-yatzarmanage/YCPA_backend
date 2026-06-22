import logging
from typing import Union

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ycpa.core.exceptions import AppException
from ycpa.core.schemas.errors import FieldError, make_problem

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")

def _instance(request: Request) -> str:
    return str(request.url.path)

def _json(problem, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=problem.model_dump())


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    logger.log(
        logging.ERROR if exc.status_code >= 500 else logging.WARNING,
        f"{exc.error_code}: {exc.message}",
        extra={"request_id": _request_id(request), "details": exc.details},
        exc_info=exc.status_code >= 500,
    )
    return _json(make_problem(
        status=exc.status_code,
        code=exc.error_code,
        detail=exc.message,
        instance=_instance(request),
        request_id=_request_id(request),
        meta=exc.details or None,
    ), exc.status_code)



async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    logger.warning(
        f"HTTP {exc.status_code}: {exc.detail}",
        extra={"request_id": _request_id(request)},
    )
    return _json(make_problem(
        status=exc.status_code,
        code=f"HTTP_{exc.status_code}",
        detail=str(exc.detail),
        instance=_instance(request),
        request_id=_request_id(request),
    ), exc.status_code)



async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError | ValidationError,
) -> JSONResponse:
    errors = [
        FieldError(
            field=".".join(str(loc) for loc in e["loc"]),
            message=e["msg"],
            code=e["type"].upper(),
        )
        for e in exc.errors()
    ]
    logger.warning(
        f"Validation failed: {len(errors)} field(s)",
        extra={"request_id": _request_id(request)},
    )
    return _json(make_problem(
        status=422,
        code="VALIDATION_ERROR",
        detail=f"{len(errors)} field(s) failed validation",
        instance=_instance(request),
        request_id=_request_id(request),
        errors=errors,
    ), 422)



async def database_integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    raw = str(exc.orig) if hasattr(exc, "orig") else str(exc)
    raw_lower = raw.lower()

    if "unique constraint" in raw_lower:
        code, detail = "DUPLICATE_RECORD",          "This record already exists"
    elif "foreign key" in raw_lower:
        code, detail = "INVALID_REFERENCE",         "Referenced record does not exist"
    elif "not null constraint" in raw_lower:
        code, detail = "MISSING_REQUIRED_FIELD",    "A required field is missing"
    else:
        code, detail = "DATABASE_CONSTRAINT_ERROR", "Database constraint violation"

    logger.error(code, extra={"request_id": _request_id(request), "raw": raw[:200]}, exc_info=True)
    return _json(make_problem(
        status=409,
        code=code,
        detail=detail,
        instance=_instance(request),
        request_id=_request_id(request),
    ), 409)


async def database_operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    logger.critical("DB connection error", extra={"request_id": _request_id(request)}, exc_info=True)
    return _json(make_problem(
        status=503,
        code="DATABASE_UNAVAILABLE",
        detail="Service temporarily unavailable. Please try again in a moment.",
        instance=_instance(request),
        request_id=_request_id(request),
    ), 503)



async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        f"Unhandled {type(exc).__name__}: {exc}",
        extra={"request_id": _request_id(request)},
        exc_info=True,
    )
    return _json(make_problem(
        status=500,
        code="INTERNAL_SERVER_ERROR",
        detail="An unexpected error occurred. Please try again later.",
        instance=_instance(request),
        request_id=_request_id(request),
    ), 500)



def register_exception_handlers(app) -> None:
    app.add_exception_handler(AppException,              app_exception_handler)
    app.add_exception_handler(StarletteHTTPException,    http_exception_handler)
    app.add_exception_handler(RequestValidationError,    validation_exception_handler)
    app.add_exception_handler(ValidationError,           validation_exception_handler)
    app.add_exception_handler(IntegrityError,            database_integrity_error_handler)
    app.add_exception_handler(OperationalError,          database_operational_error_handler)
    app.add_exception_handler(DBAPIError,                database_operational_error_handler)
    app.add_exception_handler(Exception,                 unhandled_exception_handler)
    logger.info("Exception handlers registered")

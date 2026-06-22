from typing import Any, Dict, Optional  # noqa: UP035

from ycpa.core.exceptions.base import AppException


class BadRequestException(AppException):
    status_code = 400
    error_code  = "BAD_REQUEST"
    message     = "Bad request"


class ValidationException(AppException):
    status_code = 400
    error_code  = "VALIDATION_ERROR"
    message     = "Validation failed"


class UnauthorizedException(AppException):
    status_code = 401
    error_code  = "UNAUTHORIZED"
    message     = "Authentication required"


class ForbiddenException(AppException):
    status_code = 403
    error_code  = "FORBIDDEN"
    message     = "Access forbidden"


class NotFoundException(AppException):
    status_code = 404
    error_code  = "NOT_FOUND"
    message     = "Resource not found"

    def __init__(self, message: str = None, resource: Optional[str] = None, details: Optional[Dict] = None):
        details = details or {}
        if resource:
            details["resource"] = resource
        super().__init__(message=message, details=details)


class ConflictException(AppException):
    status_code = 409
    error_code  = "CONFLICT"
    message     = "Resource conflict"


class UnprocessableEntityException(AppException):
    status_code = 422
    error_code  = "UNPROCESSABLE_ENTITY"
    message     = "Unprocessable entity"


class TooManyRequestsException(AppException):
    status_code = 429
    error_code  = "RATE_LIMIT_EXCEEDED"
    message     = "Too many requests"

    def __init__(self, message: str = None, retry_after: Optional[int] = None, details: Optional[Any] = None):
        details = details or {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(message=message, details=details)
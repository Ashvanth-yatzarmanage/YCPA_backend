from typing import Any, Optional

from ycpa.core.exceptions.base import AppException



class BusinessLogicException(AppException):
    status_code = 400
    error_code  = "BUSINESS_LOGIC_ERROR"
    message     = "Business rule violated"


class InsufficientPermissionsException(BusinessLogicException):
    status_code = 403
    error_code  = "INSUFFICIENT_PERMISSIONS"
    message     = "Insufficient permissions"

    def __init__(self, message: str = None, required_permission: Optional[str] = None, details: Optional[Any] = None):
        details = details or {}
        if required_permission:
            details["required_permission"] = required_permission
        super().__init__(message=message, details=details)


class ResourceLockedException(BusinessLogicException):
    status_code = 409
    error_code  = "RESOURCE_LOCKED"
    message     = "Resource is currently locked"


class QuotaExceededException(BusinessLogicException):
    status_code = 429
    error_code  = "QUOTA_EXCEEDED"
    message     = "Quota exceeded"

    def __init__(
        self,
        message:    str          = None,
        quota_type: Optional[str] = None,
        current:    Optional[int] = None,
        limit:      Optional[int] = None,
        details:    Optional[Any] = None,
    ):
        details = details or {}
        if quota_type: details["quota_type"] = quota_type
        if current  is not None: details["current"] = current
        if limit    is not None: details["limit"]   = limit
        super().__init__(message=message, details=details)
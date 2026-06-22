from typing import Any, Optional

from ycpa.core.exceptions.base import AppException


class InternalServerException(AppException):
    status_code = 500
    error_code  = "INTERNAL_SERVER_ERROR"
    message     = "Internal server error"


class DatabaseException(AppException):
    status_code = 500
    error_code  = "DATABASE_ERROR"
    message     = "Database error occurred"


class StorageException(AppException):
    status_code = 500
    error_code  = "STORAGE_ERROR"
    message     = "Storage error occurred"


class FileUploadException(AppException):
    status_code = 400
    error_code  = "FILE_UPLOAD_ERROR"
    message     = "File upload failed"


class ExternalServiceException(AppException):
    status_code = 502
    error_code  = "EXTERNAL_SERVICE_ERROR"
    message     = "External service error"

    def __init__(self, message: str = None, service_name: Optional[str] = None, details: Optional[Any] = None):
        details = details or {}
        if service_name:
            details["service"] = service_name
        super().__init__(message=message, details=details)


class ServiceUnavailableException(AppException):
    status_code = 503
    error_code  = "SERVICE_UNAVAILABLE"
    message     = "Service temporarily unavailable"

    def __init__(self, message: str = None, retry_after: Optional[int] = None, details: Optional[Any] = None):
        details = details or {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(message=message, details=details)


class GatewayTimeoutException(AppException):
    status_code = 504
    error_code  = "GATEWAY_TIMEOUT"
    message     = "Gateway timeout"
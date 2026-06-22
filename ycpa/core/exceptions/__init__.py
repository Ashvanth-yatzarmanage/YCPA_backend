from ycpa.core.exceptions.base import AppException
from ycpa.core.exceptions.business import (
    BusinessLogicException,
    InsufficientPermissionsException,
    QuotaExceededException,
    ResourceLockedException,
)
from ycpa.core.exceptions.http_4xx import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    TooManyRequestsException,
    UnauthorizedException,
    UnprocessableEntityException,
    ValidationException,
)
from ycpa.core.exceptions.http_5xx import (
    DatabaseException,
    ExternalServiceException,
    FileUploadException,
    GatewayTimeoutException,
    InternalServerException,
    ServiceUnavailableException,
    StorageException,
)

__all__ = [
    "AppException",
    # 4xx
    "BadRequestException", "ValidationException", "UnauthorizedException",
    "ForbiddenException", "NotFoundException", "ConflictException",
    "UnprocessableEntityException", "TooManyRequestsException",
    # 5xx
    "InternalServerException", "DatabaseException", "StorageException",
    "FileUploadException", "ExternalServiceException",
    "ServiceUnavailableException", "GatewayTimeoutException",
    # business
    "BusinessLogicException", "InsufficientPermissionsException",
    "ResourceLockedException", "QuotaExceededException",
]

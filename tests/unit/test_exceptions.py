# tests/unit/test_exceptions.py

# Run with:  pytest tests/unit/test_exceptions.py -v

import pytest
from dtyc.core.exceptions import (
    AppException,
    NotFoundException,
    UnauthorizedException,
    ConflictException,
    QuotaExceededException,
    TooManyRequestsException,
    ForbiddenException,
    BadRequestException,
    DatabaseException,
)


class TestAppException:

    def test_default_values(self):
        exc = AppException()
        assert exc.status_code == 500
        assert exc.error_code  == "INTERNAL_SERVER_ERROR"

    def test_custom_message(self):
        exc = AppException(message="something broke")
        assert exc.message == "something broke"

    def test_str_representation(self):
        exc = AppException(message="oops")
        assert "oops" in str(exc)


class TestNotFoundException:

    def test_default(self):
        exc = NotFoundException()
        assert exc.status_code == 404
        assert exc.error_code  == "NOT_FOUND"

    def test_with_resource(self):
        exc = NotFoundException(resource="User")
        assert exc.details["resource"] == "User"

    def test_custom_message(self):
        exc = NotFoundException(message="Project not found")
        assert exc.message == "Project not found"


class TestUnauthorizedException:

    def test_status_code(self):
        assert UnauthorizedException().status_code == 401

    def test_error_code(self):
        assert UnauthorizedException().error_code == "UNAUTHORIZED"


class TestConflictException:

    def test_status_code(self):
        assert ConflictException().status_code == 409

    def test_error_code(self):
        assert ConflictException().error_code == "CONFLICT"


class TestQuotaExceededException:

    def test_status_code(self):
        assert QuotaExceededException().status_code == 429

    def test_with_all_details(self):
        exc = QuotaExceededException(
            quota_type="storage",
            current=100,
            limit=100,
        )
        assert exc.details["quota_type"] == "storage"
        assert exc.details["current"]    == 100
        assert exc.details["limit"]      == 100

    def test_custom_message(self):
        exc = QuotaExceededException(message="Storage full")
        assert exc.message == "Storage full"


class TestTooManyRequestsException:

    def test_with_retry_after(self):
        exc = TooManyRequestsException(retry_after=60)
        assert exc.details["retry_after"] == 60
        assert exc.status_code            == 429


class TestDatabaseException:

    def test_is_500(self):
        assert DatabaseException().status_code == 500

    def test_error_code(self):
        assert DatabaseException().error_code == "DATABASE_ERROR"
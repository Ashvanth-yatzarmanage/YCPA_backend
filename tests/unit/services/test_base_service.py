import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from dtyc.services.base import BaseService
from dtyc.core.exceptions import (
    UnauthorizedException,
    ForbiddenException,
    NotFoundException,
    QuotaExceededException,
)


# ── Setup ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def service(mock_session):
    """BaseService instance with a fake session"""
    return BaseService(session=mock_session)


# ── require_authenticated ─────────────────────────────────────────────────────

class TestRequireAuthenticated:

    def test_returns_user_id_when_authenticated(self, service):
        user_id = uuid4()
        result  = service.require_authenticated(user_id)
        assert result == user_id

    def test_raises_when_no_user_id(self, service):
        with pytest.raises(UnauthorizedException):
            service.require_authenticated(None)


# ── require_active_user ───────────────────────────────────────────────────────

class TestRequireActiveUser:

    def test_passes_for_active_user(self, service, fake_user):
        # should not raise anything
        service.require_active_user(fake_user)

    def test_raises_when_user_is_none(self, service):
        with pytest.raises(NotFoundException):
            service.require_active_user(None)

    def test_raises_when_user_inactive(self, service, fake_inactive_user):
        with pytest.raises(ForbiddenException) as exc_info:
            service.require_active_user(fake_inactive_user)
        assert "deactivated" in str(exc_info.value).lower()

    def test_raises_when_user_deleted(self, service, fake_user):
        from datetime import datetime, timezone
        fake_user.deleted_at = datetime.now(timezone.utc)
        with pytest.raises(ForbiddenException) as exc_info:
            service.require_active_user(fake_user)
        assert "no longer exists" in str(exc_info.value).lower()


# ── require_platform_role ─────────────────────────────────────────────────────

class TestRequirePlatformRole:

    def test_passes_when_role_matches(self, service, fake_user):
        fake_user.platform_role = "admin"
        service.require_platform_role(fake_user, "admin")  # should not raise

    def test_raises_when_role_wrong(self, service, fake_user):
        fake_user.platform_role = "customer"
        with pytest.raises(ForbiddenException):
            service.require_platform_role(fake_user, "admin")


# ── require_owner_or_admin ────────────────────────────────────────────────────

class TestRequireOwnerOrAdmin:

    def test_passes_when_owner(self, service):
        user_id = uuid4()
        service.require_owner_or_admin(
            resource_owner_id=user_id,
            current_user_id=user_id,
            user_role="customer",
        )

    def test_passes_when_admin(self, service):
        service.require_owner_or_admin(
            resource_owner_id=uuid4(),
            current_user_id=uuid4(),
            user_role="admin",
        )

    def test_raises_when_not_owner_and_not_admin(self, service):
        with pytest.raises(ForbiddenException):
            service.require_owner_or_admin(
                resource_owner_id=uuid4(),
                current_user_id=uuid4(),
                user_role="customer",
            )


# ── check_subscription_limit ──────────────────────────────────────────────────

class TestCheckSubscriptionLimit:

    def test_passes_when_under_limit(self, service):
        service.check_subscription_limit(
            current_count=3,
            max_allowed=10,
            resource_name="workspaces",
        )

    def test_passes_at_one_below_limit(self, service):
        service.check_subscription_limit(current_count=9, max_allowed=10, resource_name="workspaces")

    def test_raises_when_at_limit(self, service):
        with pytest.raises(QuotaExceededException) as exc_info:
            service.check_subscription_limit(
                current_count=10,
                max_allowed=10,
                resource_name="workspaces",
            )
        assert exc_info.value.status_code == 429

    def test_raises_when_over_limit(self, service):
        with pytest.raises(QuotaExceededException):
            service.check_subscription_limit(current_count=15, max_allowed=10, resource_name="workspaces")

    def test_quota_exception_has_correct_details(self, service):
        with pytest.raises(QuotaExceededException) as exc_info:
            service.check_subscription_limit(current_count=5, max_allowed=5, resource_name="projects")
        exc = exc_info.value
        assert exc.details["current"]    == 5
        assert exc.details["limit"]      == 5
        assert exc.details["quota_type"] == "projects"
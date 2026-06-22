from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.fixture
def fake_user():
    user = MagicMock()
    user.id            = uuid4()
    user.email         = "test@example.com"
    user.full_name     = "Test User"
    user.is_active     = True
    user.is_onboarded  = True
    user.email_verified = True
    user.platform_role = "customer"
    user.deleted_at    = None
    user.created_at    = datetime.now(timezone.utc)
    return user


@pytest.fixture
def fake_admin_user(fake_user):
    fake_user.platform_role = "admin"
    return fake_user


@pytest.fixture
def fake_inactive_user(fake_user):
    fake_user.is_active = False
    return fake_user



@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.flush   = AsyncMock()
    session.commit  = AsyncMock()
    session.refresh = AsyncMock()
    session.add     = MagicMock()
    session.get     = AsyncMock()
    return session



pytest_plugins = ["pytest_asyncio"]

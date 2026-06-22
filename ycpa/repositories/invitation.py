import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.models.invitation import Invitation
from ycpa.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class InvitationRepository(BaseRepository[Invitation]):

    def __init__(self, session: AsyncSession):
        super().__init__(Invitation, session)

    async def get_by_token(self, token: str) -> Invitation | None:
        result = await self.session.execute(
            select(Invitation).where(Invitation.token == token)
        )
        return result.scalar_one_or_none()

    # ── Duplicate checks ──────────────────────────────────────────────────────

    async def get_pending_by_email_and_project(
        self, email: str, project_id: UUID
    ) -> Invitation | None:
        result = await self.session.execute(
            select(Invitation).where(
                Invitation.email      == email,
                Invitation.project_id == project_id,
                Invitation.status     == "pending",
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_by_email_and_workspace(
        self, email: str, workspace_id: UUID
    ) -> Optional[Invitation]:
        """Check for existing pending workspace-level invitation."""
        result = await self.session.execute(
            select(Invitation).where(
                Invitation.email        == email,
                Invitation.workspace_id == workspace_id,
                Invitation.project_id.is_(None),   # workspace-only invite
                Invitation.status       == "pending",
            )
        )
        return result.scalar_one_or_none()

    # ── Status updates ────────────────────────────────────────────────────────

    async def mark_accepted(self, token: str, accepted_by: UUID) -> None:
        from datetime import datetime, timezone
        await self.session.execute(
            update(Invitation)
            .where(Invitation.token == token)
            .values(
                status      = "accepted",
                accepted_by = accepted_by,
                accepted_at = datetime.now(timezone.utc),
            )
        )
        await self.session.flush()

    async def mark_expired(self, token: str) -> None:
        await self.session.execute(
            update(Invitation)
            .where(Invitation.token == token)
            .values(status="expired")
        )
        await self.session.flush()
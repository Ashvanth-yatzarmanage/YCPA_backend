import logging
from typing import List, Optional  # noqa: UP035
from uuid import UUID

from sqlalchemy import delete, exists, func, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.models.user import User
from ycpa.models.workspace import (
    PimProject,
    PimProjectFile,
    PimProjectMember,
    PimWorkspace,
    PimWorkspaceMember,
)
from ycpa.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class PimWorkspaceRepository(BaseRepository[PimWorkspace]):

    def __init__(self, session: AsyncSession):
        super().__init__(PimWorkspace, session)

    async def get_my_workspaces(self, owner_id: UUID) -> List[PimWorkspace]:
        result = await self.session.execute(
            select(PimWorkspace).where(
                PimWorkspace.owner_id == owner_id,
                PimWorkspace.deleted_at.is_(None),
                PimWorkspace.is_active.is_(True),
            ).order_by(PimWorkspace.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_shared_workspaces(self, user_id: UUID) -> List[PimWorkspace]:
        """
        FIX: Returns workspaces where the user is a member but NOT the owner.

        A user is considered a member if:
          (A) they have a row in pim_workspace_members  ← NEW (workspace invite flow)
          OR
          (B) they have a row in pim_project_members    ← existing (project invite flow)
              for at least one project in the workspace

        Both paths now correctly populate Shared Workspaces on the frontend.
        """
        # (A) workspace-level membership
        has_workspace_member_row = exists(
            select(PimWorkspaceMember.user_id).where(
                PimWorkspaceMember.workspace_id == PimWorkspace.id,
                PimWorkspaceMember.user_id == user_id,
            )
        )

        # (B) project-level membership (existing logic)
        has_project_member_row = exists(
            select(PimProjectMember.project_id)
            .join(PimProject, PimProject.id == PimProjectMember.project_id)
            .where(
                PimProject.workspace_id == PimWorkspace.id,
                PimProject.deleted_at.is_(None),
                PimProjectMember.user_id == user_id,
            )
        )

        result = await self.session.execute(
            select(PimWorkspace).where(
                PimWorkspace.owner_id != user_id,
                PimWorkspace.deleted_at.is_(None),
                PimWorkspace.is_active.is_(True),
                or_(has_workspace_member_row, has_project_member_row),  # ← FIX
            ).order_by(PimWorkspace.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_workspace_with_owner_check(self, workspace_id: UUID) -> Optional[PimWorkspace]:
        result = await self.session.execute(
            select(PimWorkspace).where(
                PimWorkspace.id == workspace_id,
                PimWorkspace.deleted_at.is_(None),
                PimWorkspace.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def count_workspaces_owned(self, owner_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(PimWorkspace).where(
                PimWorkspace.owner_id == owner_id,
                PimWorkspace.deleted_at.is_(None),
                PimWorkspace.is_active.is_(True),
            )
        )
        return result.scalar() or 0

    async def get_member(self, workspace_id: UUID, user_id: UUID) -> Optional[PimWorkspaceMember]:
        result = await self.session.execute(
            select(PimWorkspaceMember).where(
                PimWorkspaceMember.workspace_id == workspace_id,
                PimWorkspaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_members_with_users(
        self, workspace_id: UUID
    ) -> List[tuple[PimWorkspaceMember, User]]:
        result = await self.session.execute(
            select(PimWorkspaceMember, User)
            .join(User, User.id == PimWorkspaceMember.user_id)
            .where(
                PimWorkspaceMember.workspace_id == workspace_id,
                User.deleted_at.is_(None),
            )
            .order_by(PimWorkspaceMember.joined_at)
        )
        return list(result.all())

    async def count_members(self, workspace_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(PimWorkspaceMember).where(
                PimWorkspaceMember.workspace_id == workspace_id,
            )
        )
        return result.scalar() or 0

    async def add_member(
        self, workspace_id: UUID, user_id: UUID, role: str, invited_by: UUID, created_by: UUID,
    ) -> PimWorkspaceMember:
        member = PimWorkspaceMember(
            workspace_id=workspace_id, user_id=user_id, role=role,
            invited_by=invited_by, created_by=created_by,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def update_member_role(
        self, workspace_id: UUID, user_id: UUID, role: str
    ) -> Optional[PimWorkspaceMember]:
        await self.session.execute(
            update(PimWorkspaceMember)
            .where(PimWorkspaceMember.workspace_id == workspace_id, PimWorkspaceMember.user_id == user_id)
            .values(role=role)
        )
        await self.session.flush()
        return await self.get_member(workspace_id, user_id)

    async def remove_member(self, workspace_id: UUID, user_id: UUID) -> bool:
        result = await self.session.execute(
            delete(PimWorkspaceMember).where(
                PimWorkspaceMember.workspace_id == workspace_id,
                PimWorkspaceMember.user_id == user_id,
            )
        )
        await self.session.flush()
        return result.rowcount > 0

    async def get_assignable_members(
        self, workspace_id: UUID, project_id: UUID,
    ) -> List[tuple[PimWorkspaceMember, User]]:
        already_in_project = (
            select(PimProjectMember.user_id)
            .where(PimProjectMember.project_id == project_id)
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(PimWorkspaceMember, User)
            .join(User, User.id == PimWorkspaceMember.user_id)
            .where(
                PimWorkspaceMember.workspace_id == workspace_id,
                User.deleted_at.is_(None),
                User.is_active.is_(True),
                not_(PimWorkspaceMember.user_id.in_(already_in_project)),
            )
            .order_by(User.full_name)
        )
        return list(result.all())

    async def get_owner_as_assignable(
        self, workspace_id: UUID, project_id: UUID,
    ) -> Optional[tuple[PimWorkspace, User]]:
        already_in_project = (
            select(PimProjectMember.user_id)
            .where(PimProjectMember.project_id == project_id)
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(PimWorkspace, User)
            .join(User, User.id == PimWorkspace.owner_id)
            .where(
                PimWorkspace.id == workspace_id,
                PimWorkspace.deleted_at.is_(None),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
                not_(PimWorkspace.owner_id.in_(already_in_project)),
            )
        )
        return result.one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# PROJECT REPOSITORY  (unchanged — keeping full file for completeness)
# ─────────────────────────────────────────────────────────────────────────────

class PimProjectRepository(BaseRepository[PimProject]):

    def __init__(self, session: AsyncSession):
        super().__init__(PimProject, session)

    async def get_projects_by_workspace(self, workspace_id: UUID) -> List[PimProject]:
        result = await self.session.execute(
            select(PimProject).where(
                PimProject.workspace_id == workspace_id,
                PimProject.deleted_at.is_(None),
            ).order_by(PimProject.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_projects_by_workspace_for_member(
        self, workspace_id: UUID, user_id: UUID
    ) -> List[PimProject]:
        result = await self.session.execute(
            select(PimProject)
            .join(PimProjectMember, PimProjectMember.project_id == PimProject.id)
            .where(
                PimProject.workspace_id == workspace_id,
                PimProject.deleted_at.is_(None),
                PimProjectMember.user_id == user_id,
            )
            .order_by(PimProject.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_projects_in_workspace(self, workspace_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(PimProject).where(
                PimProject.workspace_id == workspace_id,
                PimProject.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def count_projects_visible_to_member(self, workspace_id: UUID, user_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(PimProject)
            .join(PimProjectMember, PimProjectMember.project_id == PimProject.id)
            .where(
                PimProject.workspace_id == workspace_id,
                PimProject.deleted_at.is_(None),
                PimProjectMember.user_id == user_id,
            )
        )
        return result.scalar() or 0

    async def batch_count_members(self, project_ids: List[UUID]) -> dict:
        if not project_ids:
            return {}
        result = await self.session.execute(
            select(PimProjectMember.project_id, func.count().label("cnt"))
            .where(PimProjectMember.project_id.in_(project_ids))
            .group_by(PimProjectMember.project_id)
        )
        return {row.project_id: row.cnt for row in result.all()}

    async def batch_count_files(self, project_ids: List[UUID]) -> dict:
        if not project_ids:
            return {}
        result = await self.session.execute(
            select(PimProjectFile.project_id, func.count().label("cnt"))
            .where(PimProjectFile.project_id.in_(project_ids))
            .group_by(PimProjectFile.project_id)
        )
        return {row.project_id: row.cnt for row in result.all()}

    async def count_members_in_project(self, project_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(PimProjectMember).where(
                PimProjectMember.project_id == project_id
            )
        )
        return result.scalar() or 0

    async def count_files_in_project(self, project_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(PimProjectFile).where(
                PimProjectFile.project_id == project_id
            )
        )
        return result.scalar() or 0

    async def get_project_member(self, project_id: UUID, user_id: UUID) -> Optional[PimProjectMember]:
        result = await self.session.execute(
            select(PimProjectMember).where(
                PimProjectMember.project_id == project_id,
                PimProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_project_members_with_users(self, project_id: UUID) -> List[tuple[PimProjectMember, User]]:
        result = await self.session.execute(
            select(PimProjectMember, User)
            .join(User, User.id == PimProjectMember.user_id)
            .where(PimProjectMember.project_id == project_id, User.deleted_at.is_(None))
            .order_by(PimProjectMember.joined_at)
        )
        return list(result.all())

    async def add_project_member(
        self, project_id: UUID, user_id: UUID, invited_by: UUID, created_by: UUID,
        role_id: Optional[UUID] = None, is_share_only: bool = False,
    ) -> PimProjectMember:
        member = PimProjectMember(
            project_id=project_id, user_id=user_id, role_id=role_id,
            is_share_only=is_share_only, invited_by=invited_by, created_by=created_by,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def bulk_add_project_members(
        self, project_id: UUID, entries: List[dict], invited_by: UUID, created_by: UUID,
    ) -> List[PimProjectMember]:
        members = [
            PimProjectMember(
                project_id=project_id, user_id=entry["user_id"], role_id=entry["role_id"],
                is_share_only=False, invited_by=invited_by, created_by=created_by,
            )
            for entry in entries
        ]
        self.session.add_all(members)
        await self.session.flush()
        return members

    async def update_project_member_role(self, project_id: UUID, user_id: UUID, role_id: UUID) -> Optional[PimProjectMember]:
        await self.session.execute(
            update(PimProjectMember)
            .where(PimProjectMember.project_id == project_id, PimProjectMember.user_id == user_id)
            .values(role_id=role_id)
        )
        await self.session.flush()
        return await self.get_project_member(project_id, user_id)

    async def remove_project_member(self, project_id: UUID, user_id: UUID) -> bool:
        result = await self.session.execute(
            delete(PimProjectMember).where(
                PimProjectMember.project_id == project_id,
                PimProjectMember.user_id == user_id,
            )
        )
        await self.session.flush()
        return result.rowcount > 0

    async def get_project_counts_for_workspace_members(
        self, workspace_id: UUID, user_ids: List[UUID]
    ) -> dict[UUID, int]:
        if not user_ids:
            return {}
        result = await self.session.execute(
            select(PimProjectMember.user_id, func.count().label("cnt"))
            .join(PimProject, PimProject.id == PimProjectMember.project_id)
            .where(
                PimProject.workspace_id == workspace_id,
                PimProject.deleted_at.is_(None),
                PimProjectMember.user_id.in_(user_ids),
            )
            .group_by(PimProjectMember.user_id)
        )
        return {row.user_id: row.cnt for row in result.all()}
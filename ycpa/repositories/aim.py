import logging
from typing import List, Optional, Any  # noqa: UP035
from uuid import UUID

from sqlalchemy import delete, exists, func, not_, or_, select, update, Row
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.models.user import User
from ycpa.models.workspace import (
    AimProject,
    AimProjectFile,
    AimProjectMember,
    AimWorkspace,
    AimWorkspaceMember,
)
from ycpa.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class AimWorkspaceRepository(BaseRepository[AimWorkspace]):

    def __init__(self, session: AsyncSession):
        super().__init__(AimWorkspace, session)

    async def get_my_workspaces(self, owner_id: UUID) -> List[AimWorkspace]:
        result = await self.session.execute(
            select(AimWorkspace).where(
                AimWorkspace.owner_id == owner_id,
                AimWorkspace.deleted_at.is_(None),
                AimWorkspace.is_active.is_(True),
            ).order_by(AimWorkspace.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_shared_workspaces(self, user_id: UUID) -> List[AimWorkspace]:

        has_workspace_member_row = exists(
            select(AimWorkspaceMember.user_id).where(
                AimWorkspaceMember.workspace_id == AimWorkspace.id,
                AimWorkspaceMember.user_id == user_id,
            )
        )

        has_project_member_row = exists(
            select(AimProjectMember.project_id)
            .join(AimProject, AimProject.id == AimProjectMember.project_id)
            .where(
                AimProject.workspace_id == AimWorkspace.id,
                AimProject.deleted_at.is_(None),
                AimProjectMember.user_id == user_id,
            )
        )

        result = await self.session.execute(
            select(AimWorkspace).where(
                AimWorkspace.owner_id != user_id,
                AimWorkspace.deleted_at.is_(None),
                AimWorkspace.is_active.is_(True),
                or_(has_workspace_member_row, has_project_member_row),
            ).order_by(AimWorkspace.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_workspace_with_owner_check(self, workspace_id: UUID) -> AimWorkspace | None:
        result = await self.session.execute(
            select(AimWorkspace).where(
                AimWorkspace.id == workspace_id,
                AimWorkspace.deleted_at.is_(None),
                AimWorkspace.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def count_workspaces_owned(self, owner_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(AimWorkspace).where(
                AimWorkspace.owner_id == owner_id,
                AimWorkspace.deleted_at.is_(None),
                AimWorkspace.is_active.is_(True),
            )
        )
        return result.scalar() or 0

    async def get_member(self, workspace_id: UUID, user_id: UUID) -> AimWorkspaceMember | None:
        result = await self.session.execute(
            select(AimWorkspaceMember).where(
                AimWorkspaceMember.workspace_id == workspace_id,
                AimWorkspaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_members_with_users(self, workspace_id: UUID) -> list[Row[tuple[Any, Any]]]:
        result = await self.session.execute(
            select(AimWorkspaceMember, User)
            .join(User, User.id == AimWorkspaceMember.user_id)
            .where(AimWorkspaceMember.workspace_id == workspace_id, User.deleted_at.is_(None))
            .order_by(AimWorkspaceMember.joined_at)
        )
        return list(result.all())

    async def count_members(self, workspace_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(AimWorkspaceMember).where(
                AimWorkspaceMember.workspace_id == workspace_id,
            )
        )
        return result.scalar() or 0

    async def add_member(
        self, workspace_id: UUID, user_id: UUID, role: str, invited_by: UUID, created_by: UUID,
    ) -> AimWorkspaceMember:
        member = AimWorkspaceMember(
            workspace_id=workspace_id, user_id=user_id, role=role,
            invited_by=invited_by, created_by=created_by,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def update_member_role(self, workspace_id: UUID, user_id: UUID, role: str) -> AimWorkspaceMember | None:
        await self.session.execute(
            update(AimWorkspaceMember)
            .where(AimWorkspaceMember.workspace_id == workspace_id, AimWorkspaceMember.user_id == user_id)
            .values(role=role)
        )
        await self.session.flush()
        return await self.get_member(workspace_id, user_id)

    async def remove_member(self, workspace_id: UUID, user_id: UUID) -> bool:
        result = await self.session.execute(
            delete(AimWorkspaceMember).where(
                AimWorkspaceMember.workspace_id == workspace_id,
                AimWorkspaceMember.user_id == user_id,
            )
        )
        await self.session.flush()
        return result.rowcount > 0

    async def get_assignable_members(self, workspace_id: UUID, project_id: UUID) -> list[Row[tuple[Any, Any]]]:
        already_in_project = (
            select(AimProjectMember.user_id)
            .where(AimProjectMember.project_id == project_id)
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(AimWorkspaceMember, User)
            .join(User, User.id == AimWorkspaceMember.user_id)
            .where(
                AimWorkspaceMember.workspace_id == workspace_id,
                User.deleted_at.is_(None),
                User.is_active.is_(True),
                not_(AimWorkspaceMember.user_id.in_(already_in_project)),
            )
            .order_by(User.full_name)
        )
        return list(result.all())

    async def get_owner_as_assignable(self, workspace_id: UUID, project_id: UUID) -> Row[tuple[Any, Any]] | None:
        already_in_project = (
            select(AimProjectMember.user_id)
            .where(AimProjectMember.project_id == project_id)
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(AimWorkspace, User)
            .join(User, User.id == AimWorkspace.owner_id)
            .where(
                AimWorkspace.id == workspace_id,
                AimWorkspace.deleted_at.is_(None),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
                not_(AimWorkspace.owner_id.in_(already_in_project)),
            )
        )
        return result.one_or_none()



class AimProjectRepository(BaseRepository[AimProject]):

    def __init__(self, session: AsyncSession):
        super().__init__(AimProject, session)

    async def get_projects_by_workspace(self, workspace_id: UUID) -> list[AimProject]:
        result = await self.session.execute(
            select(AimProject).where(
                AimProject.workspace_id == workspace_id,
                AimProject.deleted_at.is_(None),
            ).order_by(AimProject.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_projects_by_workspace_for_member(self, workspace_id: UUID, user_id: UUID) -> list[AimProject]:
        result = await self.session.execute(
            select(AimProject)
            .join(AimProjectMember, AimProjectMember.project_id == AimProject.id)
            .where(
                AimProject.workspace_id == workspace_id,
                AimProject.deleted_at.is_(None),
                AimProjectMember.user_id == user_id,
            )
            .order_by(AimProject.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_projects_in_workspace(self, workspace_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(AimProject).where(
                AimProject.workspace_id == workspace_id,
                AimProject.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def count_projects_visible_to_member(self, workspace_id: UUID, user_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(AimProject)
            .join(AimProjectMember, AimProjectMember.project_id == AimProject.id)
            .where(
                AimProject.workspace_id == workspace_id,
                AimProject.deleted_at.is_(None),
                AimProjectMember.user_id == user_id,
            )
        )
        return result.scalar() or 0

    async def batch_count_members(self, project_ids: list[UUID]) -> dict:
        if not project_ids:
            return {}
        result = await self.session.execute(
            select(AimProjectMember.project_id, func.count().label("cnt"))
            .where(AimProjectMember.project_id.in_(project_ids))
            .group_by(AimProjectMember.project_id)
        )
        return {row.project_id: row.cnt for row in result.all()}

    async def batch_count_files(self, project_ids: list[UUID]) -> dict:
        if not project_ids:
            return {}
        result = await self.session.execute(
            select(AimProjectFile.project_id, func.count().label("cnt"))
            .where(AimProjectFile.project_id.in_(project_ids))
            .group_by(AimProjectFile.project_id)
        )
        return {row.project_id: row.cnt for row in result.all()}

    async def count_members_in_project(self, project_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(AimProjectMember).where(
                AimProjectMember.project_id == project_id
            )
        )
        return result.scalar() or 0

    async def count_files_in_project(self, project_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(AimProjectFile).where(
                AimProjectFile.project_id == project_id
            )
        )
        return result.scalar() or 0

    async def get_project_member(self, project_id: UUID, user_id: UUID) -> AimProjectMember | None:
        result = await self.session.execute(
            select(AimProjectMember).where(
                AimProjectMember.project_id == project_id,
                AimProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_project_members_with_users(self, project_id: UUID) -> list[Row[tuple[Any, Any]]]:
        result = await self.session.execute(
            select(AimProjectMember, User)
            .join(User, User.id == AimProjectMember.user_id)
            .where(AimProjectMember.project_id == project_id, User.deleted_at.is_(None))
            .order_by(AimProjectMember.joined_at)
        )
        return list(result.all())

    async def add_project_member(
        self, project_id: UUID, user_id: UUID, invited_by: UUID, created_by: UUID,
        role_id: UUID | None = None, is_share_only: bool = False,
    ) -> AimProjectMember:
        member = AimProjectMember(
            project_id=project_id, user_id=user_id, role_id=role_id,
            is_share_only=is_share_only, invited_by=invited_by, created_by=created_by,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def bulk_add_project_members(
        self, project_id: UUID, entries: list[dict], invited_by: UUID, created_by: UUID,
    ) -> list[AimProjectMember]:
        members = [
            AimProjectMember(
                project_id=project_id, user_id=entry["user_id"], role_id=entry["role_id"],
                is_share_only=False, invited_by=invited_by, created_by=created_by,
            )
            for entry in entries
        ]
        self.session.add_all(members)
        await self.session.flush()
        return members

    async def update_project_member_role(self, project_id: UUID, user_id: UUID, role_id: UUID) -> AimProjectMember | None:
        await self.session.execute(
            update(AimProjectMember)
            .where(AimProjectMember.project_id == project_id, AimProjectMember.user_id == user_id)
            .values(role_id=role_id)
        )
        await self.session.flush()
        return await self.get_project_member(project_id, user_id)

    async def remove_project_member(self, project_id: UUID, user_id: UUID) -> bool:
        result = await self.session.execute(
            delete(AimProjectMember).where(
                AimProjectMember.project_id == project_id,
                AimProjectMember.user_id == user_id,
            )
        )
        await self.session.flush()
        return result.rowcount > 0

    async def get_project_counts_for_workspace_members(self, workspace_id: UUID, user_ids: list[UUID]) -> dict[UUID, int]:
        if not user_ids:
            return {}
        result = await self.session.execute(
            select(AimProjectMember.user_id, func.count().label("cnt"))
            .join(AimProject, AimProject.id == AimProjectMember.project_id)
            .where(
                AimProject.workspace_id == workspace_id,
                AimProject.deleted_at.is_(None),
                AimProjectMember.user_id.in_(user_ids),
            )
            .group_by(AimProjectMember.user_id)
        )
        return {row.user_id: row.cnt for row in result.all()}

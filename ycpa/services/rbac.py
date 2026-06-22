from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.models.rbac import Module, RolePermission
from ycpa.models.workspace import (
    AimProject,
    AimProjectMember,
    AimWorkspace,
    AimWorkspaceMember,
    PimProject,
    PimProjectMember,
    PimWorkspace,
    PimWorkspaceMember,
)

WorkspaceType = Literal["pim", "aim"]
WorkspaceRole = Literal["owner", "admin", "member"]

ROLE_WEIGHT: dict[str, int] = {
    "owner":  3,
    "admin":  2,
    "member": 1,
}


class RBACService:


    @staticmethod
    async def get_workspace_role(
        db: AsyncSession,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        workspace_type: WorkspaceType,
    ) -> WorkspaceRole | None:

        if workspace_type == "pim":
            ws_model      = PimWorkspace
            member_model  = PimWorkspaceMember
            proj_model    = PimProject
            pm_model      = PimProjectMember
        else:
            ws_model      = AimWorkspace
            member_model  = AimWorkspaceMember
            proj_model    = AimProject
            pm_model      = AimProjectMember

        ws = await db.scalar(
            select(ws_model).where(
                ws_model.id == workspace_id,
                ws_model.owner_id == user_id,
                ws_model.deleted_at.is_(None),
            )
        )
        if ws:
            return "owner"

        member = await db.scalar(
            select(member_model).where(
                member_model.workspace_id == workspace_id,
                member_model.user_id == user_id,
            )
        )
        if member:
            return member.role


        project_membership = await db.scalar(
            select(pm_model)
            .join(proj_model, proj_model.id == pm_model.project_id)
            .where(
                proj_model.workspace_id == workspace_id,
                proj_model.deleted_at.is_(None),
                pm_model.user_id == user_id,
            )
        )
        if project_membership:
            return "member"

        return None

    @staticmethod
    def workspace_role_meets(
        actual: WorkspaceRole | None,
        required: WorkspaceRole,
    ) -> bool:
        if actual is None:
            return False
        return ROLE_WEIGHT.get(actual, 0) >= ROLE_WEIGHT.get(required, 0)


    @staticmethod
    async def get_project_permission(
        db: AsyncSession,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        workspace_type: WorkspaceType,
        module: str,
        action: str,
    ) -> bool:
        member_model = PimProjectMember if workspace_type == "pim" else AimProjectMember

        member = await db.scalar(
            select(member_model).where(
                member_model.project_id == project_id,
                member_model.user_id == user_id,
            )
        )
        if not member:
            return False

        if getattr(member, "is_share_only", False):
            return False

        module_row = await db.scalar(
            select(Module).where(
                Module.slug == module,
                Module.is_active.is_(True),
            )
        )
        if not module_row:
            return False

        perm = await db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == member.role_id,
                RolePermission.module_id == module_row.id,
                RolePermission.submodule_id.is_(None),
            )
        )
        if not perm:
            return False

        return bool(getattr(perm, action, False))

    @staticmethod
    async def get_project_submodule_permission(
        db: AsyncSession,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        workspace_type: WorkspaceType,
        module: str,
        submodule: str,
        action: str,
    ) -> bool:
        member_model = PimProjectMember if workspace_type == "pim" else AimProjectMember

        member = await db.scalar(
            select(member_model).where(
                member_model.project_id == project_id,
                member_model.user_id == user_id,
            )
        )
        if not member:
            return False
        if getattr(member, "is_share_only", False):
            return False

        module_row = await db.scalar(
            select(Module).where(
                Module.slug == module,
                Module.is_active.is_(True),
            )
        )
        if not module_row:
            return False

        from ycpa.models.rbac import Submodule
        submodule_row = await db.scalar(
            select(Submodule).where(
                Submodule.module_id == module_row.id,
                Submodule.slug == submodule,
                Submodule.is_active.is_(True),
            )
        )

        if submodule_row:
            perm = await db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == member.role_id,
                    RolePermission.module_id == module_row.id,
                    RolePermission.submodule_id == submodule_row.id,
                )
            )
            if perm:
                return bool(getattr(perm, action, False))

        perm = await db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == member.role_id,
                RolePermission.module_id == module_row.id,
                RolePermission.submodule_id.is_(None),
            )
        )
        if not perm:
            return False
        return bool(getattr(perm, action, False))

    @staticmethod
    async def get_all_project_permissions(
        db: AsyncSession,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        workspace_type: WorkspaceType,
    ) -> dict:
        member_model = PimProjectMember if workspace_type == "pim" else AimProjectMember

        member = await db.scalar(
            select(member_model).where(
                member_model.project_id == project_id,
                member_model.user_id == user_id,
            )
        )
        if not member:
            return {}

        if getattr(member, "is_share_only", False):
            return {}  

        from ycpa.models.rbac import Submodule

        result = await db.execute(
            select(RolePermission, Module, Submodule)
            .join(Module, Module.id == RolePermission.module_id)
            .outerjoin(Submodule, Submodule.id == RolePermission.submodule_id)
            .where(RolePermission.role_id == member.role_id)
        )

        permissions = {}
        for rp, mod, sub in result.all():
            key = f"{mod.slug}/{sub.slug}" if sub else mod.slug
            permissions[key] = {
                "can_view":    rp.can_view,
                "can_create":  rp.can_create,
                "can_edit":    rp.can_edit,
                "can_delete":  rp.can_delete,
                "can_approve": rp.can_approve,
                "can_share":   rp.can_share,
            }
        return permissions


    @staticmethod
    async def workspace_exists(
        db: AsyncSession,
        workspace_id: uuid.UUID,
        workspace_type: WorkspaceType,
    ) -> bool:
        model = PimWorkspace if workspace_type == "pim" else AimWorkspace
        result = await db.scalar(
            select(model).where(
                model.id == workspace_id,
                model.deleted_at.is_(None),
                model.is_active.is_(True),
            )
        )
        return result is not None


    @staticmethod
    async def project_exists(
        db: AsyncSession,
        project_id: uuid.UUID,
        workspace_type: WorkspaceType,
    ) -> bool:
        model = PimProject if workspace_type == "pim" else AimProject
        result = await db.scalar(
            select(model).where(
                model.id == project_id,
                model.deleted_at.is_(None),
            )
        )
        return result is not None

    @staticmethod
    async def get_workspace_role_for_project(
            db: AsyncSession,
            user_id: uuid.UUID,
            project_id: uuid.UUID,
            workspace_type: WorkspaceType,
    ) -> str | None:
        """Return the user's workspace role for the workspace that owns this project."""
        from ycpa.models.workspace import (
            PimProject, PimWorkspace, PimWorkspaceMember,
            AimProject, AimWorkspace, AimWorkspaceMember,
        )
        if workspace_type == "pim":
            project = await db.scalar(select(PimProject).where(PimProject.id == project_id))
            if not project:
                return None
            ws = await db.scalar(select(PimWorkspace).where(PimWorkspace.id == project.workspace_id))
            if not ws:
                return None
            if ws.owner_id == user_id:
                return "owner"
            member = await db.scalar(
                select(PimWorkspaceMember).where(
                    PimWorkspaceMember.workspace_id == ws.id,
                    PimWorkspaceMember.user_id == user_id,
                )
            )
            return member.role if member else None
        else:
            project = await db.scalar(select(AimProject).where(AimProject.id == project_id))
            if not project:
                return None
            ws = await db.scalar(select(AimWorkspace).where(AimWorkspace.id == project.workspace_id))
            if not ws:
                return None
            if ws.owner_id == user_id:
                return "owner"
            member = await db.scalar(
                select(AimWorkspaceMember).where(
                    AimWorkspaceMember.workspace_id == ws.id,
                    AimWorkspaceMember.user_id == user_id,
                )
            )
            return member.role if member else None
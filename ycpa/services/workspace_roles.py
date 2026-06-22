from __future__ import annotations

import uuid
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from ycpa.models.rbac import Module, RolePermission, Submodule
from ycpa.models.roles import Role
from ycpa.models.user import User
from ycpa.services.base import BaseService
from ycpa.services.rbac import RBACService, WorkspaceType


class PermissionFlags(BaseModel):
    can_view:    bool = False
    can_create:  bool = False
    can_edit:    bool = False
    can_delete:  bool = False
    can_approve: bool = False
    can_share:   bool = False


class SubmodulePermissionItem(BaseModel):
    submodule_id:   UUID
    submodule_slug: str
    submodule_name: str
    can_view:       bool
    can_create:     bool
    can_edit:       bool
    can_delete:     bool
    can_approve:    bool
    can_share:      bool


class ModulePermissionItem(BaseModel):
    module_id:    UUID
    module_slug:  str
    module_name:  str
    product_type: str
    order:        int
    can_view:     bool
    can_create:   bool
    can_edit:     bool
    can_delete:   bool
    can_approve:  bool
    can_share:    bool
    submodules:   list[SubmodulePermissionItem] = []


class WorkspaceRoleResponse(BaseModel):
    id:               UUID
    name:             str
    description:      str | None
    product_type:     str
    is_system:        bool
    is_editable:      bool
    is_active:        bool
    created_by_type:  str
    workspace_id:     UUID | None
    permissions:      list[ModulePermissionItem] = []
    model_config = {"from_attributes": True}


class BulkPermissionItem(BaseModel):
    module_id:    UUID
    submodule_id: UUID | None = None
    can_view:     bool = False
    can_create:   bool = False
    can_edit:     bool = False
    can_delete:   bool = False
    can_approve:  bool = False
    can_share:    bool = False



class WorkspaceRolesService(BaseService):

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def _assert_workspace_access(
        self,
        workspace_id: UUID,
        workspace_type: WorkspaceType,
        current_user: User,
        require_admin: bool = True,
    ) -> None:

        if current_user.platform_role == "super_admin":
            return

        role = await RBACService.get_workspace_role(
            self.session, current_user.id, workspace_id, workspace_type
        )
        if role is None:
            raise ForbiddenException("You are not a member of this workspace.")

        if require_admin and role not in ("owner", "admin"):
            raise ForbiddenException("Only workspace owner or admin can manage roles.")

    async def _build_role_response(self, role: Role) -> WorkspaceRoleResponse:
        perms_raw = await self.session.execute(
            select(RolePermission, Module, Submodule)
            .join(Module, Module.id == RolePermission.module_id)
            .outerjoin(Submodule, Submodule.id == RolePermission.submodule_id)
            .where(RolePermission.role_id == role.id)
            .order_by(Module.order, Submodule.order)
        )

        module_map: dict[UUID, dict] = {}

        for rp, mod, sub in perms_raw.all():
            if mod.id not in module_map:
                module_map[mod.id] = {
                    "module_id":    mod.id,
                    "module_slug":  mod.slug,
                    "module_name":  mod.name,
                    "product_type": mod.product_type,
                    "order":        mod.order,
                    "can_view": False, "can_create": False, "can_edit": False,
                    "can_delete": False, "can_approve": False, "can_share": False,
                    "submodules": [],
                }

            if sub is None:
                module_map[mod.id].update({
                    "can_view":    rp.can_view,
                    "can_create":  rp.can_create,
                    "can_edit":    rp.can_edit,
                    "can_delete":  rp.can_delete,
                    "can_approve": rp.can_approve,
                    "can_share":   rp.can_share,
                })
            else:
                module_map[mod.id]["submodules"].append(SubmodulePermissionItem(
                    submodule_id=sub.id,
                    submodule_slug=sub.slug,
                    submodule_name=sub.name,
                    can_view=rp.can_view,
                    can_create=rp.can_create,
                    can_edit=rp.can_edit,
                    can_delete=rp.can_delete,
                    can_approve=rp.can_approve,
                    can_share=rp.can_share,
                ))

        permissions = [
            ModulePermissionItem(**v)
            for v in sorted(module_map.values(), key=lambda x: x["order"])
        ]

        return WorkspaceRoleResponse(
            id=role.id,
            name=role.name,
            description=role.description,
            product_type=role.product_type,
            is_system=role.is_system,
            is_editable=role.is_editable,
            is_active=role.is_active,
            created_by_type=role.created_by_type,
            workspace_id=role.workspace_id,
            permissions=permissions,
        )


    async def list_roles(
        self,
        workspace_id: UUID,
        workspace_type: WorkspaceType,
        current_user: User,
    ) -> list[WorkspaceRoleResponse]:

        await self._assert_workspace_access(
            workspace_id, workspace_type, current_user, require_admin=False
        )

        result = await self.session.execute(
            select(Role).where(
                Role.is_active.is_(True),
                Role.deleted_at.is_(None),
                Role.name.not_in(["Owner", "Admin", "Member"]),
                (Role.workspace_id.is_(None)) | (Role.workspace_id == workspace_id),
            ).order_by(Role.created_at)
        )
        roles = list(result.scalars().all())
        return [await self._build_role_response(r) for r in roles]


    async def create_role(
        self,
        workspace_id: UUID,
        workspace_type: WorkspaceType,
        name: str,
        description: str | None,
        product_type: str,
        current_user: User,
    ) -> WorkspaceRoleResponse:
        await self._assert_workspace_access(workspace_id, workspace_type, current_user)

        if product_type not in ("pim", "aim", "both"):
            raise ForbiddenException("product_type must be pim | aim | both")

        existing = await self.session.scalar(
            select(Role).where(
                Role.name == name,
                Role.deleted_at.is_(None),
                (Role.workspace_id.is_(None)) | (Role.workspace_id == workspace_id),
            )
        )
        if existing:
            raise ConflictException(f"A role named '{name}' already exists.")

        created_by_type = (
            "super_admin" if current_user.platform_role == "super_admin"
            else "workspace_admin"
        )

        role = Role(
            id=uuid.uuid4(),
            name=name,
            description=description,
            product_type=product_type,
            is_system=False,
            is_editable=True,
            is_active=True,
            created_by_type=created_by_type,
            workspace_id=workspace_id,
            created_by=current_user.id,
        )
        self.session.add(role)
        await self.session.flush()

        await self.log_audit(
            action="ROLE_CREATED",
            resource_type=f"{workspace_type}_workspace",
            resource_id=str(workspace_id),
            user_id=current_user.id,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            payload={"role_name": name, "product_type": product_type},
        )
        await self.session.commit()
        return await self._build_role_response(role)


    async def update_role(
        self,
        workspace_id: UUID,
        workspace_type: WorkspaceType,
        role_id: UUID,
        name: str | None,
        description: str | None,
        is_active: bool | None,
        current_user: User,
    ) -> WorkspaceRoleResponse:
        await self._assert_workspace_access(workspace_id, workspace_type, current_user)

        role = await self.session.scalar(
            select(Role).where(Role.id == role_id, Role.deleted_at.is_(None))
        )
        if not role:
            raise NotFoundException("Role not found.")

        if role.is_system and not role.is_editable:
            raise ForbiddenException("This system role cannot be modified.")

        if not role.is_system and role.workspace_id != workspace_id:
            raise ForbiddenException("This role does not belong to your workspace.")

        if role.is_system and name and current_user.platform_role != "super_admin":
            raise ForbiddenException("Only super admin can rename system roles.")

        if name:
            role.name = name
        if description is not None:
            role.description = description
        if is_active is not None:
            role.is_active = is_active
        role.updated_by = current_user.id

        await self.session.flush()
        await self.session.commit()
        return await self._build_role_response(role)


    async def bulk_upsert_permissions(
        self,
        workspace_id: UUID,
        workspace_type: WorkspaceType,
        role_id: UUID,
        permissions: list[BulkPermissionItem],
        current_user: User,
    ) -> WorkspaceRoleResponse:

        await self._assert_workspace_access(workspace_id, workspace_type, current_user)

        role = await self.session.scalar(
            select(Role).where(Role.id == role_id, Role.deleted_at.is_(None))
        )
        if not role:
            raise NotFoundException("Role not found.")

        if role.is_system and not role.is_editable:
            raise ForbiddenException("This system role's permissions cannot be edited.")

        if not role.is_system and role.workspace_id != workspace_id:
            raise ForbiddenException("This role does not belong to your workspace.")

        for item in permissions:
            module = await self.session.scalar(
                select(Module).where(Module.id == item.module_id)
            )
            if not module:
                raise NotFoundException(f"Module {item.module_id} not found.")

            existing = await self.session.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role_id,
                    RolePermission.module_id == item.module_id,
                    RolePermission.submodule_id == item.submodule_id,
                )
            )
            if existing:
                existing.can_view    = item.can_view
                existing.can_create  = item.can_create
                existing.can_edit    = item.can_edit
                existing.can_delete  = item.can_delete
                existing.can_approve = item.can_approve
                existing.can_share   = item.can_share
                existing.updated_by  = current_user.id
            else:
                self.session.add(RolePermission(
                    id=uuid.uuid4(),
                    role_id=role_id,
                    module_id=item.module_id,
                    submodule_id=item.submodule_id,
                    can_view=item.can_view,
                    can_create=item.can_create,
                    can_edit=item.can_edit,
                    can_delete=item.can_delete,
                    can_approve=item.can_approve,
                    can_share=item.can_share,
                    created_by=current_user.id,
                ))

        await self.session.flush()
        await self.log_audit(
            action="ROLE_PERMISSIONS_UPDATED",
            resource_type=f"{workspace_type}_workspace",
            resource_id=str(workspace_id),
            user_id=current_user.id,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            payload={"role_id": str(role_id), "updated_count": len(permissions)},
        )
        await self.session.commit()
        return await self._build_role_response(role)


    async def clone_role(
        self,
        workspace_id: UUID,
        workspace_type: WorkspaceType,
        role_id: UUID,
        new_name: str,
        current_user: User,
    ) -> WorkspaceRoleResponse:

        await self._assert_workspace_access(workspace_id, workspace_type, current_user)

        source = await self.session.scalar(
            select(Role).where(Role.id == role_id, Role.deleted_at.is_(None))
        )
        if not source:
            raise NotFoundException("Source role not found.")

        name_exists = await self.session.scalar(
            select(Role).where(
                Role.name == new_name,
                Role.deleted_at.is_(None),
                (Role.workspace_id.is_(None)) | (Role.workspace_id == workspace_id),
            )
        )
        if name_exists:
            raise ConflictException(f"A role named '{new_name}' already exists.")

        created_by_type = (
            "super_admin" if current_user.platform_role == "super_admin"
            else "workspace_admin"
        )

        new_role = Role(
            id=uuid.uuid4(),
            name=new_name,
            description=f"Cloned from '{source.name}'",
            product_type=source.product_type,
            is_system=False,
            is_editable=True,
            is_active=True,
            created_by_type=created_by_type,
            workspace_id=workspace_id,
            created_by=current_user.id,
        )
        self.session.add(new_role)
        await self.session.flush()

        source_perms = await self.session.execute(
            select(RolePermission).where(RolePermission.role_id == source.id)
        )
        for perm in source_perms.scalars().all():
            self.session.add(RolePermission(
                id=uuid.uuid4(),
                role_id=new_role.id,
                module_id=perm.module_id,
                submodule_id=perm.submodule_id,
                can_view=perm.can_view,
                can_create=perm.can_create,
                can_edit=perm.can_edit,
                can_delete=perm.can_delete,
                can_approve=perm.can_approve,
                can_share=perm.can_share,
                created_by=current_user.id,
            ))

        await self.session.flush()
        await self.log_audit(
            action="ROLE_CLONED",
            resource_type=f"{workspace_type}_workspace",
            resource_id=str(workspace_id),
            user_id=current_user.id,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            payload={"source_role": source.name, "new_role": new_name},
        )
        await self.session.commit()
        return await self._build_role_response(new_role)


    async def delete_role(
        self,
        workspace_id: UUID,
        workspace_type: WorkspaceType,
        role_id: UUID,
        current_user: User,
    ) -> None:
        await self._assert_workspace_access(workspace_id, workspace_type, current_user)

        role = await self.session.scalar(
            select(Role).where(Role.id == role_id, Role.deleted_at.is_(None))
        )
        if not role:
            raise NotFoundException("Role not found.")

        if role.is_system:
            raise ForbiddenException("System roles cannot be deleted.")

        if role.workspace_id != workspace_id:
            raise ForbiddenException("This role does not belong to your workspace.")

        from datetime import datetime, timezone
        role.deleted_at = datetime.now(timezone.utc)
        role.deleted_by = current_user.id

        await self.session.flush()
        await self.log_audit(
            action="ROLE_DELETED",
            resource_type=f"{workspace_type}_workspace",
            resource_id=str(workspace_id),
            user_id=current_user.id,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            payload={"role_name": role.name},
        )
        await self.session.commit()


    async def get_my_project_permissions(
        self,
        project_id: UUID,
        workspace_type: WorkspaceType,
        current_user: User,
    ) -> dict:

        from ycpa.services.rbac import RBACService
        return await RBACService.get_all_project_permissions(
            self.session, current_user.id, project_id, workspace_type
        )

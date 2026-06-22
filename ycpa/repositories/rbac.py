from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.models.rbac import Module, RolePermission, Submodule
from ycpa.models.roles import Role


class RBACRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    async def get_all_roles(self) -> list[Role]:
        result = await self.session.execute(
            select(Role)
            .where(Role.deleted_at.is_(None))
            .order_by(Role.created_at)
        )
        return list(result.scalars().all())

    async def get_role_by_id(self, role_id: uuid.UUID) -> Role | None:
        return await self.session.scalar(
            select(Role).where(Role.id == role_id, Role.deleted_at.is_(None))
        )

    async def get_role_by_name(self, name: str, product_type: str) -> Role | None:
        return await self.session.scalar(
            select(Role).where(
                Role.name == name,
                Role.product_type == product_type,
                Role.deleted_at.is_(None),
            )
        )

    async def create_role(
        self,
        name: str,
        product_type: str,
        description: str | None,
        created_by: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> Role:
        role = Role(
            id=uuid.uuid4(),
            name=name,
            description=description,
            product_type=product_type,
            is_system=False,
            is_editable=True,
            is_active=True,
            created_by_type="super_admin",
            workspace_id=workspace_id,
            created_by=created_by,
        )
        self.session.add(role)
        await self.session.flush()
        return role

    async def update_role(
        self,
        role: Role,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        updated_by: uuid.UUID | None = None,
    ) -> Role:
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if is_active is not None:
            role.is_active = is_active
        if updated_by:
            role.updated_by = updated_by
        await self.session.flush()
        return role

    async def delete_role(self, role: Role, deleted_by: uuid.UUID) -> None:
        from datetime import datetime, timezone
        role.deleted_at = datetime.now(timezone.utc)
        role.deleted_by = deleted_by
        await self.session.flush()

    # ── Modules ────────────────────────────────────────────────────────────────

    async def get_all_modules(self) -> list[Module]:
        result = await self.session.execute(
            select(Module).where(Module.is_active.is_(True)).order_by(Module.order)
        )
        return list(result.scalars().all())

    async def get_module_by_id(self, module_id: uuid.UUID) -> Module | None:
        return await self.session.scalar(
            select(Module).where(Module.id == module_id)
        )

    # ── Submodules ─────────────────────────────────────────────────────────────

    async def get_submodules_for_module(self, module_id: uuid.UUID) -> list[Submodule]:
        result = await self.session.execute(
            select(Submodule)
            .where(Submodule.module_id == module_id, Submodule.is_active.is_(True))
            .order_by(Submodule.order)
        )
        return list(result.scalars().all())


    async def get_permissions_for_role(self, role_id: uuid.UUID) -> list[RolePermission]:
        result = await self.session.execute(
            select(RolePermission).where(RolePermission.role_id == role_id)
        )
        return list(result.scalars().all())

    async def get_permission(
        self,
        role_id: uuid.UUID,
        module_id: uuid.UUID,
        submodule_id: uuid.UUID | None,
    ) -> RolePermission | None:
        return await self.session.scalar(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.module_id == module_id,
                RolePermission.submodule_id == submodule_id,
            )
        )

    async def upsert_permission(
        self,
        role_id: uuid.UUID,
        module_id: uuid.UUID,
        submodule_id: uuid.UUID | None,
        can_view: bool,
        can_create: bool,
        can_edit: bool,
        can_delete: bool,
        can_approve: bool,
        can_share: bool,
        updated_by: uuid.UUID,
    ) -> RolePermission:
        existing = await self.get_permission(role_id, module_id, submodule_id)

        if existing:
            existing.can_view    = can_view
            existing.can_create  = can_create
            existing.can_edit    = can_edit
            existing.can_delete  = can_delete
            existing.can_approve = can_approve
            existing.can_share   = can_share
            existing.updated_by  = updated_by
            await self.session.flush()
            return existing

        perm = RolePermission(
            id=uuid.uuid4(),
            role_id=role_id,
            module_id=module_id,
            submodule_id=submodule_id,
            can_view=can_view,
            can_create=can_create,
            can_edit=can_edit,
            can_delete=can_delete,
            can_approve=can_approve,
            can_share=can_share,
            created_by=updated_by,
        )
        self.session.add(perm)
        await self.session.flush()
        return perm

    async def delete_permissions_for_role(self, role_id: uuid.UUID) -> None:
        perms = await self.get_permissions_for_role(role_id)
        for p in perms:
            await self.session.delete(p)
        await self.session.flush()
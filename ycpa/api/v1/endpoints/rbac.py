from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.auth.dependencies import SuperAdminUser, get_current_user
from ycpa.core.database.session import get_async_session
from ycpa.repositories.rbac import RBACRepository

router = APIRouter(prefix="/rbac", tags=["rbac"])



class PermissionFlags(BaseModel):
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_approve: bool = False
    can_share: bool = False


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    product_type: str
    is_system: bool
    is_editable: bool
    is_active: bool
    created_by_type: str
    workspace_id: uuid.UUID | None
    model_config = {"from_attributes": True}


class ModuleResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    product_type: str
    order: int
    model_config = {"from_attributes": True}


class SubmoduleResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    order: int
    model_config = {"from_attributes": True}


class ModuleWithSubmodules(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    product_type: str
    order: int
    submodules: list[SubmoduleResponse] = []
    model_config = {"from_attributes": True}


class PermissionResponse(BaseModel):
    id: uuid.UUID
    role_id: uuid.UUID
    module_id: uuid.UUID
    submodule_id: uuid.UUID | None
    can_view: bool
    can_create: bool
    can_edit: bool
    can_delete: bool
    can_approve: bool
    can_share: bool
    model_config = {"from_attributes": True}


class CreateRoleRequest(BaseModel):
    name: str
    description: str | None = None
    product_type: str  # pim | aim | both
    workspace_id: uuid.UUID | None = None


class UpdateRoleRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class UpsertPermissionRequest(BaseModel):
    module_id: uuid.UUID
    submodule_id: uuid.UUID | None = None
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_approve: bool = False
    can_share: bool = False



@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    current_user: SuperAdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    repo = RBACRepository(db)
    return await repo.get_all_roles()


@router.post("/roles", response_model=RoleResponse, status_code=201)
async def create_role(
    body: CreateRoleRequest,
    current_user: SuperAdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    repo = RBACRepository(db)

    if body.product_type not in ("pim", "aim", "both"):
        raise HTTPException(400, "product_type must be pim | aim | both")

    existing = await repo.get_role_by_name(body.name, body.product_type)
    if existing:
        raise HTTPException(409, f"Role '{body.name}' already exists for {body.product_type}")

    role = await repo.create_role(
        name=body.name,
        product_type=body.product_type,
        description=body.description,
        created_by=current_user.id,
        workspace_id=body.workspace_id,
    )
    await db.commit()
    return role


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: uuid.UUID,
    body: UpdateRoleRequest,
    current_user: SuperAdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    repo = RBACRepository(db)
    role = await repo.get_role_by_id(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if role.is_system and not role.is_editable:
        raise HTTPException(403, "System roles cannot be modified")

    role = await repo.update_role(
        role,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        updated_by=current_user.id,
    )
    await db.commit()
    return role


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: uuid.UUID,
    current_user: SuperAdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    repo = RBACRepository(db)
    role = await repo.get_role_by_id(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if role.is_system:
        raise HTTPException(403, "System roles cannot be deleted")

    await repo.delete_permissions_for_role(role_id)
    await repo.delete_role(role, deleted_by=current_user.id)
    await db.commit()


@router.get("/modules", response_model=list[ModuleWithSubmodules])
async def list_modules(
    current_user: SuperAdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    repo = RBACRepository(db)
    modules = await repo.get_all_modules()
    result = []
    for mod in modules:
        subs = await repo.get_submodules_for_module(mod.id)
        result.append(ModuleWithSubmodules(
            id=mod.id,
            name=mod.name,
            slug=mod.slug,
            product_type=mod.product_type,
            order=mod.order,
            submodules=[SubmoduleResponse.model_validate(s) for s in subs],
        ))
    return result


@router.get("/roles/{role_id}/permissions", response_model=list[PermissionResponse])
async def get_role_permissions(
    role_id: uuid.UUID,
    current_user: SuperAdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    repo = RBACRepository(db)
    role = await repo.get_role_by_id(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    return await repo.get_permissions_for_role(role_id)


@router.put("/roles/{role_id}/permissions", response_model=PermissionResponse)
async def upsert_permission(
    role_id: uuid.UUID,
    body: UpsertPermissionRequest,
    current_user: SuperAdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    repo = RBACRepository(db)
    role = await repo.get_role_by_id(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if role.is_system and not role.is_editable:
        raise HTTPException(403, "This system role's permissions are not editable")

    module = await repo.get_module_by_id(body.module_id)
    if not module:
        raise HTTPException(404, "Module not found")

    perm = await repo.upsert_permission(
        role_id=role_id,
        module_id=body.module_id,
        submodule_id=body.submodule_id,
        can_view=body.can_view,
        can_create=body.can_create,
        can_edit=body.can_edit,
        can_delete=body.can_delete,
        can_approve=body.can_approve,
        can_share=body.can_share,
        updated_by=current_user.id,
    )
    await db.commit()
    return perm
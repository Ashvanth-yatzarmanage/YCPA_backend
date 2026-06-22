import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status

from ycpa.api.dependencies.rbac import WorkspaceGuard
from ycpa.core.auth.dependencies import CurrentUser
from ycpa.core.database.dependencies import DatabaseSession
from ycpa.core.exceptions import ForbiddenException
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.schemas.requests.pim import (
    BulkPermissionsRequest,
    CloneRoleRequest,
    CreatePimProjectRequest,
    CreatePimWorkspaceRequest,
    CreateWorkspaceRoleRequest,
    InviteMemberRequest,
    UpdatePimProjectRequest,
    UpdatePimWorkspaceRequest,
    UpdateWorkspaceMemberRoleRequest,
    UpdateWorkspaceRoleRequest,
)
from ycpa.schemas.responses.pim import (
    PimProjectResponse,
    PimWorkspaceDetailResponse,
    PimWorkspaceListResponse,
    PimWorkspaceMemberResponse,
)
from ycpa.services.pim import PimService
from ycpa.services.workspace_roles import (
    BulkPermissionItem,
    WorkspaceRoleResponse,
    WorkspaceRolesService,
)

router = APIRouter(prefix="/pim", tags=["PIM"])


# ── Workspaces ─────────────────────────────────────────────────────────────────

@router.get(
    "/workspaces",
    response_model=SuccessResponse[PimWorkspaceListResponse],
    status_code=status.HTTP_200_OK,
)
async def list_workspaces(
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[PimWorkspaceListResponse]:
    service = PimService(session)
    data = await service.list_workspaces(current_user)
    return SuccessResponse(success=True, message="PIM workspaces retrieved.", data=data)


@router.post(
    "/workspaces",
    response_model=SuccessResponse[PimWorkspaceDetailResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    body: CreatePimWorkspaceRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[PimWorkspaceDetailResponse]:
    # Only super_admin can create workspaces; customers are members only
    if current_user.platform_role not in ("super_admin",):
        raise ForbiddenException("Only admins can create workspaces.")
    service = PimService(session)
    data = await service.create_workspace(body, current_user)
    return SuccessResponse(success=True, message="PIM workspace created.", data=data)


@router.get(
    "/workspaces/{workspace_id}",
    response_model=SuccessResponse[PimWorkspaceDetailResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "member"))],
)
async def get_workspace(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[PimWorkspaceDetailResponse]:
    service = PimService(session)
    data = await service.get_workspace(workspace_id, current_user)
    return SuccessResponse(success=True, message="PIM workspace retrieved.", data=data)


@router.patch(
    "/workspaces/{workspace_id}",
    response_model=SuccessResponse[PimWorkspaceDetailResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
)
async def update_workspace(
    workspace_id: uuid.UUID,
    body: UpdatePimWorkspaceRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[PimWorkspaceDetailResponse]:
    service = PimService(session)
    data = await service.update_workspace(workspace_id, body, current_user)
    return SuccessResponse(success=True, message="PIM workspace updated.", data=data)


@router.delete(
    "/workspaces/{workspace_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_workspace(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse:
    # Only super_admin or the workspace owner can delete
    from sqlalchemy import select
    from ycpa.models.workspace import PimWorkspace

    ws = await session.scalar(
        select(PimWorkspace).where(
            PimWorkspace.id == workspace_id,
            PimWorkspace.deleted_at.is_(None),
        )
    )
    if not ws:
        from ycpa.core.exceptions import NotFoundException
        raise NotFoundException("Workspace not found.")

    if current_user.platform_role != "super_admin" and ws.owner_id != current_user.id:
        raise ForbiddenException("Only the workspace owner or admin can delete this workspace.")

    ws.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    return SuccessResponse(success=True, message="PIM workspace deleted.")


# ── Members ────────────────────────────────────────────────────────────────────

@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=SuccessResponse[list[PimWorkspaceMemberResponse]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "member"))],
    summary="List all workspace members (owner + admins + members)",
)
async def list_workspace_members(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[list[PimWorkspaceMemberResponse]]:
    service = PimService(session)
    data = await service.list_workspace_members(workspace_id, current_user)
    return SuccessResponse(success=True, message="Workspace members retrieved.", data=data)


@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=SuccessResponse[PimWorkspaceMemberResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
    summary="Add an existing user to the workspace",
)
async def invite_member(
    workspace_id: uuid.UUID,
    body: InviteMemberRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[PimWorkspaceMemberResponse]:
    service = PimService(session)
    data = await service.invite_member(workspace_id, body, current_user)
    return SuccessResponse(success=True, message=f"{body.email} added to workspace.", data=data)


@router.patch(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=SuccessResponse[PimWorkspaceMemberResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
    summary="Change a workspace member's role (admin ↔ member).",
)
async def update_workspace_member_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpdateWorkspaceMemberRoleRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[PimWorkspaceMemberResponse]:
    service = PimService(session)
    data = await service.update_workspace_member_role(workspace_id, user_id, body, current_user)
    return SuccessResponse(success=True, message=f"Member role updated to {body.role}.", data=data)


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
    summary="Remove a member from the workspace",
)
async def remove_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse:
    service = PimService(session)
    await service.remove_member(workspace_id, user_id, current_user)
    return SuccessResponse(success=True, message="Member removed.")


# ── Projects ───────────────────────────────────────────────────────────────────

@router.get(
    "/workspaces/{workspace_id}/projects",
    response_model=SuccessResponse[list[PimProjectResponse]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "member"))],
)
async def list_projects(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[list[PimProjectResponse]]:
    service = PimService(session)
    data = await service.list_projects(workspace_id, current_user)
    return SuccessResponse(success=True, message="Projects retrieved.", data=data)


@router.post(
    "/workspaces/{workspace_id}/projects",
    response_model=SuccessResponse[PimProjectResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
)
async def create_project(
    workspace_id: uuid.UUID,
    body: CreatePimProjectRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[PimProjectResponse]:
    service = PimService(session)
    data = await service.create_project(workspace_id, body, current_user)
    return SuccessResponse(success=True, message="Project created.", data=data)


@router.get(
    "/projects/{project_id}",
    response_model=SuccessResponse[PimProjectResponse],
    status_code=status.HTTP_200_OK,
)
async def get_project(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[PimProjectResponse]:
    service = PimService(session)
    data = await service.get_project(project_id, current_user)
    return SuccessResponse(success=True, message="Project retrieved.", data=data)


@router.patch(
    "/projects/{project_id}",
    response_model=SuccessResponse[PimProjectResponse],
    status_code=status.HTTP_200_OK,
)
async def update_project(
    project_id: uuid.UUID,
    body: UpdatePimProjectRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[PimProjectResponse]:
    service = PimService(session)
    data = await service.update_project(project_id, body, current_user)
    return SuccessResponse(success=True, message="Project updated.", data=data)


@router.delete(
    "/projects/{project_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_project(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse:
    service = PimService(session)
    await service.delete_project(project_id, current_user)
    return SuccessResponse(success=True, message="Project deleted.")


# ── Workspace Roles ────────────────────────────────────────────────────────────

@router.get(
    "/workspaces/{workspace_id}/roles",
    response_model=SuccessResponse[list[WorkspaceRoleResponse]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "member"))],
    summary="List all roles available in this PIM workspace (system + custom)",
)
async def list_pim_workspace_roles(
        workspace_id: uuid.UUID,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[list[WorkspaceRoleResponse]]:
    svc = WorkspaceRolesService(session)
    data = await svc.list_roles(workspace_id, "pim", current_user)
    return SuccessResponse(success=True, message="Roles retrieved.", data=data)


@router.post(
    "/workspaces/{workspace_id}/roles",
    response_model=SuccessResponse[WorkspaceRoleResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
    summary="Create a custom role for this PIM workspace",
)
async def create_pim_workspace_role(
        workspace_id: uuid.UUID,
        body: CreateWorkspaceRoleRequest,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[WorkspaceRoleResponse]:
    svc = WorkspaceRolesService(session)
    data = await svc.create_role(
        workspace_id=workspace_id, workspace_type="pim",
        name=body.name, description=body.description,
        product_type=body.product_type, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"Role '{body.name}' created.", data=data)


@router.patch(
    "/workspaces/{workspace_id}/roles/{role_id}",
    response_model=SuccessResponse[WorkspaceRoleResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
    summary="Update a custom role name or description",
)
async def update_pim_workspace_role(
        workspace_id: uuid.UUID,
        role_id: uuid.UUID,
        body: UpdateWorkspaceRoleRequest,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[WorkspaceRoleResponse]:
    svc = WorkspaceRolesService(session)
    data = await svc.update_role(
        workspace_id=workspace_id, workspace_type="pim", role_id=role_id,
        name=body.name, description=body.description, is_active=body.is_active,
        current_user=current_user,
    )
    return SuccessResponse(success=True, message="Role updated.", data=data)


@router.put(
    "/workspaces/{workspace_id}/roles/{role_id}/permissions",
    response_model=SuccessResponse[WorkspaceRoleResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
    summary="Bulk upsert permissions for a role",
)
async def bulk_upsert_pim_role_permissions(
        workspace_id: uuid.UUID,
        role_id: uuid.UUID,
        body: BulkPermissionsRequest,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[WorkspaceRoleResponse]:
    svc = WorkspaceRolesService(session)
    items = [BulkPermissionItem(**p.model_dump()) for p in body.permissions]
    data = await svc.bulk_upsert_permissions(
        workspace_id=workspace_id, workspace_type="pim",
        role_id=role_id, permissions=items, current_user=current_user,
    )
    return SuccessResponse(success=True, message="Permissions updated.", data=data)


@router.post(
    "/workspaces/{workspace_id}/roles/{role_id}/clone",
    response_model=SuccessResponse[WorkspaceRoleResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
    summary="Clone a role into a new custom role for this workspace",
)
async def clone_pim_workspace_role(
        workspace_id: uuid.UUID,
        role_id: uuid.UUID,
        body: CloneRoleRequest,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[WorkspaceRoleResponse]:
    svc = WorkspaceRolesService(session)
    data = await svc.clone_role(
        workspace_id=workspace_id, workspace_type="pim",
        role_id=role_id, new_name=body.new_name, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"Role cloned as '{body.new_name}'.", data=data)


@router.delete(
    "/workspaces/{workspace_id}/roles/{role_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
    summary="Delete a custom role (system roles cannot be deleted)",
)
async def delete_pim_workspace_role(
        workspace_id: uuid.UUID,
        role_id: uuid.UUID,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse:
    svc = WorkspaceRolesService(session)
    await svc.delete_role(
        workspace_id=workspace_id, workspace_type="pim",
        role_id=role_id, current_user=current_user,
    )
    return SuccessResponse(success=True, message="Role deleted.")


# ── Permissions ────────────────────────────────────────────────────────────────

@router.get(
    "/projects/{project_id}/permissions/me",
    response_model=SuccessResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="Get current user's full permission map for a PIM project",
)
async def get_my_pim_project_permissions(
        project_id: uuid.UUID,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[dict]:
    from ycpa.services.rbac import RBACService

    if current_user.platform_role == "super_admin":
        return SuccessResponse(
            success=True,
            message="Permissions retrieved.",
            data={"*": {"can_view": True, "can_create": True, "can_edit": True,
                        "can_delete": True, "can_approve": True, "can_share": True}},
        )

    perms = await RBACService.get_all_project_permissions(
        session, current_user.id, project_id, "pim"
    )
    return SuccessResponse(success=True, message="Permissions retrieved.", data=perms)
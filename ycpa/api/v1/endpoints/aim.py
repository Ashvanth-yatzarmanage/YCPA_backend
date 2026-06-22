import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status

from ycpa.api.dependencies.rbac import WorkspaceGuard
from ycpa.core.auth.dependencies import CurrentUser
from ycpa.core.database.dependencies import DatabaseSession
from ycpa.core.exceptions import ForbiddenException
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.schemas.requests.aim import (
    BulkPermissionsRequest,
    CloneRoleRequest,
    CreateAimProjectRequest,
    CreateAimWorkspaceRequest,
    CreateWorkspaceRoleRequest,
    InviteAimMemberRequest,
    UpdateAimWorkspaceRequest,
    UpdateWorkspaceMemberRoleRequest,
    UpdateWorkspaceRoleRequest,
)
from ycpa.schemas.responses.aim import (
    AimProjectResponse,
    AimWorkspaceDetailResponse,
    AimWorkspaceListResponse,
    AimWorkspaceMemberResponse,
)
from ycpa.services.aim import AimService
from ycpa.services.workspace_roles import (
    BulkPermissionItem,
    WorkspaceRoleResponse,
    WorkspaceRolesService,
)

router = APIRouter(prefix="/aim", tags=["AIM"])


# ── Workspaces ─────────────────────────────────────────────────────────────────

@router.get(
    "/workspaces",
    response_model=SuccessResponse[AimWorkspaceListResponse],
    status_code=status.HTTP_200_OK,
)
async def list_workspaces(
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[AimWorkspaceListResponse]:
    service = AimService(session)
    data = await service.list_workspaces(current_user)
    return SuccessResponse(success=True, message="AIM workspaces retrieved.", data=data)


@router.post(
    "/workspaces",
    response_model=SuccessResponse[AimWorkspaceDetailResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    body: CreateAimWorkspaceRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[AimWorkspaceDetailResponse]:
    # Only super_admin can create workspaces
    if current_user.platform_role not in ("super_admin",):
        raise ForbiddenException("Only admins can create workspaces.")
    service = AimService(session)
    data = await service.create_workspace(body, current_user)
    return SuccessResponse(success=True, message="AIM workspace created.", data=data)


@router.get(
    "/workspaces/{workspace_id}",
    response_model=SuccessResponse[AimWorkspaceDetailResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "member"))],
)
async def get_workspace(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[AimWorkspaceDetailResponse]:
    service = AimService(session)
    data = await service.get_workspace(workspace_id, current_user)
    return SuccessResponse(success=True, message="AIM workspace retrieved.", data=data)


@router.patch(
    "/workspaces/{workspace_id}",
    response_model=SuccessResponse[AimWorkspaceDetailResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
)
async def update_workspace(
    workspace_id: uuid.UUID,
    body: UpdateAimWorkspaceRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[AimWorkspaceDetailResponse]:
    service = AimService(session)
    data = await service.update_workspace(workspace_id, body, current_user)
    return SuccessResponse(success=True, message="AIM workspace updated.", data=data)


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
    from sqlalchemy import select
    from ycpa.models.workspace import AimWorkspace

    ws = await session.scalar(
        select(AimWorkspace).where(
            AimWorkspace.id == workspace_id,
            AimWorkspace.deleted_at.is_(None),
        )
    )
    if not ws:
        from ycpa.core.exceptions import NotFoundException
        raise NotFoundException("Workspace not found.")

    if current_user.platform_role != "super_admin" and ws.owner_id != current_user.id:
        raise ForbiddenException("Only the workspace owner or admin can delete this workspace.")

    ws.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    return SuccessResponse(success=True, message="AIM workspace deleted.")


# ── Members ────────────────────────────────────────────────────────────────────

@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=SuccessResponse[list[AimWorkspaceMemberResponse]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "member"))],
    summary="List all workspace members (owner + admins + members)",
)
async def list_workspace_members(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[list[AimWorkspaceMemberResponse]]:
    service = AimService(session)
    data = await service.list_workspace_members(workspace_id, current_user)
    return SuccessResponse(success=True, message="Workspace members retrieved.", data=data)


@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=SuccessResponse[AimWorkspaceMemberResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
    summary="Add an existing user to the workspace",
)
async def invite_member(
    workspace_id: uuid.UUID,
    body: InviteAimMemberRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[AimWorkspaceMemberResponse]:
    service = AimService(session)
    data = await service.invite_member(workspace_id, body, current_user)
    return SuccessResponse(success=True, message=f"{body.email} added to workspace.", data=data)


@router.patch(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=SuccessResponse[AimWorkspaceMemberResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
    summary="Change a workspace member's role (admin ↔ member).",
)
async def update_workspace_member_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpdateWorkspaceMemberRoleRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[AimWorkspaceMemberResponse]:
    service = AimService(session)
    data = await service.update_workspace_member_role(workspace_id, user_id, body, current_user)
    return SuccessResponse(success=True, message=f"Member role updated to {body.role}.", data=data)


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
    summary="Remove a member from the workspace",
)
async def remove_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse:
    service = AimService(session)
    await service.remove_member(workspace_id, user_id, current_user)
    return SuccessResponse(success=True, message="Member removed.")


# ── Projects ───────────────────────────────────────────────────────────────────

@router.get(
    "/workspaces/{workspace_id}/projects",
    response_model=SuccessResponse[list[AimProjectResponse]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "member"))],
)
async def list_projects(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[list[AimProjectResponse]]:
    service = AimService(session)
    data = await service.list_projects(workspace_id, current_user)
    return SuccessResponse(success=True, message="Projects retrieved.", data=data)


@router.post(
    "/workspaces/{workspace_id}/projects",
    response_model=SuccessResponse[AimProjectResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
)
async def create_project(
    workspace_id: uuid.UUID,
    body: CreateAimProjectRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[AimProjectResponse]:
    service = AimService(session)
    data = await service.create_project(workspace_id, body, current_user)
    return SuccessResponse(success=True, message="Project created.", data=data)


@router.get(
    "/projects/{project_id}",
    response_model=SuccessResponse[AimProjectResponse],
    status_code=status.HTTP_200_OK,
)
async def get_project(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[AimProjectResponse]:
    service = AimService(session)
    data = await service.get_project(project_id, current_user)
    return SuccessResponse(success=True, message="AIM project retrieved.", data=data)


@router.patch(
    "/projects/{project_id}",
    response_model=SuccessResponse[AimProjectResponse],
    status_code=status.HTTP_200_OK,
)
async def update_project(
    project_id: uuid.UUID,
    body: UpdateAimWorkspaceRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[AimProjectResponse]:
    service = AimService(session)
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
    service = AimService(session)
    await service.delete_project(project_id, current_user)
    return SuccessResponse(success=True, message="Project deleted.")


# ── Workspace Roles ────────────────────────────────────────────────────────────

@router.get(
    "/workspaces/{workspace_id}/roles",
    response_model=SuccessResponse[list[WorkspaceRoleResponse]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "member"))],
    summary="List all roles available in this AIM workspace (system + custom)",
)
async def list_aim_workspace_roles(
        workspace_id: uuid.UUID,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[list[WorkspaceRoleResponse]]:
    svc = WorkspaceRolesService(session)
    data = await svc.list_roles(workspace_id, "aim", current_user)
    return SuccessResponse(success=True, message="Roles retrieved.", data=data)


@router.post(
    "/workspaces/{workspace_id}/roles",
    response_model=SuccessResponse[WorkspaceRoleResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
    summary="Create a custom role for this AIM workspace",
)
async def create_aim_workspace_role(
        workspace_id: uuid.UUID,
        body: CreateWorkspaceRoleRequest,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[WorkspaceRoleResponse]:
    svc = WorkspaceRolesService(session)
    data = await svc.create_role(
        workspace_id=workspace_id, workspace_type="aim",
        name=body.name, description=body.description,
        product_type=body.product_type, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"Role '{body.name}' created.", data=data)


@router.patch(
    "/workspaces/{workspace_id}/roles/{role_id}",
    response_model=SuccessResponse[WorkspaceRoleResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
    summary="Update a custom role name or description",
)
async def update_aim_workspace_role(
        workspace_id: uuid.UUID,
        role_id: uuid.UUID,
        body: UpdateWorkspaceRoleRequest,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[WorkspaceRoleResponse]:
    svc = WorkspaceRolesService(session)
    data = await svc.update_role(
        workspace_id=workspace_id, workspace_type="aim", role_id=role_id,
        name=body.name, description=body.description, is_active=body.is_active,
        current_user=current_user,
    )
    return SuccessResponse(success=True, message="Role updated.", data=data)


@router.put(
    "/workspaces/{workspace_id}/roles/{role_id}/permissions",
    response_model=SuccessResponse[WorkspaceRoleResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
    summary="Bulk upsert permissions for a role",
)
async def bulk_upsert_aim_role_permissions(
        workspace_id: uuid.UUID,
        role_id: uuid.UUID,
        body: BulkPermissionsRequest,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[WorkspaceRoleResponse]:
    svc = WorkspaceRolesService(session)
    items = [BulkPermissionItem(**p.model_dump()) for p in body.permissions]
    data = await svc.bulk_upsert_permissions(
        workspace_id=workspace_id, workspace_type="aim",
        role_id=role_id, permissions=items, current_user=current_user,
    )
    return SuccessResponse(success=True, message="Permissions updated.", data=data)


@router.post(
    "/workspaces/{workspace_id}/roles/{role_id}/clone",
    response_model=SuccessResponse[WorkspaceRoleResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
    summary="Clone a role into a new custom role for this workspace",
)
async def clone_aim_workspace_role(
        workspace_id: uuid.UUID,
        role_id: uuid.UUID,
        body: CloneRoleRequest,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse[WorkspaceRoleResponse]:
    svc = WorkspaceRolesService(session)
    data = await svc.clone_role(
        workspace_id=workspace_id, workspace_type="aim",
        role_id=role_id, new_name=body.new_name, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"Role cloned as '{body.new_name}'.", data=data)


@router.delete(
    "/workspaces/{workspace_id}/roles/{role_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
    summary="Delete a custom role",
)
async def delete_aim_workspace_role(
        workspace_id: uuid.UUID,
        role_id: uuid.UUID,
        current_user: CurrentUser,
        session: DatabaseSession,
) -> SuccessResponse:
    svc = WorkspaceRolesService(session)
    await svc.delete_role(
        workspace_id=workspace_id, workspace_type="aim",
        role_id=role_id, current_user=current_user,
    )
    return SuccessResponse(success=True, message="Role deleted.")


# ── Permissions ────────────────────────────────────────────────────────────────

@router.get(
    "/projects/{project_id}/permissions/me",
    response_model=SuccessResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="Get current user's full permission map for an AIM project",
)
async def get_my_aim_project_permissions(
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
        session, current_user.id, project_id, "aim"
    )
    return SuccessResponse(success=True, message="Permissions retrieved.", data=perms)
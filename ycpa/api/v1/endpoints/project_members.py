import uuid

from fastapi import APIRouter, Depends, Query, status

from ycpa.api.dependencies.rbac import ProjectGuard, WorkspaceGuard
from ycpa.core.auth.dependencies import CurrentUser
from ycpa.core.database.dependencies import DatabaseSession
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.schemas.requests.project_members import (
    AssignWorkspaceMemberRequest,
    BulkAssignMembersRequest,
    InviteProjectMemberRequest,
    UpdateProjectMemberRoleRequest,
)
from ycpa.schemas.responses.project_members import (
    AssignableWorkspaceMemberListResponse,
    BulkAssignResponse,
    ProjectMemberListResponse,
    ProjectMemberResponse,
)
from ycpa.services.project_members import ProjectMemberService

router = APIRouter(tags=["Project Members"])


@router.get(
    "/pim/workspaces/{workspace_id}/members/assignable",
    response_model=SuccessResponse[AssignableWorkspaceMemberListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "member"))],
    summary="Get PIM workspace members not yet in the given project",
)
async def get_pim_assignable_members(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
    project_id: uuid.UUID = Query(..., description="Target project to check against"),

) -> SuccessResponse[AssignableWorkspaceMemberListResponse]:
    service = ProjectMemberService(session)
    data = await service.get_assignable_members(workspace_id, project_id, "pim")
    return SuccessResponse(success=True, message="Assignable members retrieved.", data=data)


@router.get(
    "/aim/workspaces/{workspace_id}/members/assignable",
    response_model=SuccessResponse[AssignableWorkspaceMemberListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("aim", "member"))],
    summary="Get AIM workspace members not yet in the given project",
)
async def get_aim_assignable_members(
    workspace_id: uuid.UUID,
    session: DatabaseSession,
    current_user: CurrentUser,
    project_id: uuid.UUID = Query(..., description="Target project to check against"),
) -> SuccessResponse[AssignableWorkspaceMemberListResponse]:
    service = ProjectMemberService(session)
    data = await service.get_assignable_members(workspace_id, project_id, "aim")
    return SuccessResponse(success=True, message="Assignable members retrieved.", data=data)


@router.get(
    "/pim/projects/{project_id}/members",
    response_model=SuccessResponse[ProjectMemberListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_view"))],
    summary="List PIM project members",
)
async def list_pim_project_members(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[ProjectMemberListResponse]:
    service = ProjectMemberService(session)
    data = await service.list_members(project_id, "pim")
    return SuccessResponse(success=True, message="Project members retrieved.", data=data)


@router.post(
    "/pim/projects/{project_id}/members",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_create"))],
    summary="Invite external user to PIM project by email",
)
async def invite_pim_project_member(
    project_id: uuid.UUID,
    body: InviteProjectMemberRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.invite_member(
        project_id=project_id, workspace_type="pim",
        email=body.email, role_name=body.role_name, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"{body.email} added to project as {body.role_name}.", data=data)


@router.post(
    "/pim/projects/{project_id}/members/assign",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_create"))],
    summary="Assign a workspace member to PIM project by user_id",
)
async def assign_pim_project_member(
    project_id: uuid.UUID,
    body: AssignWorkspaceMemberRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.assign_workspace_member(
        project_id=project_id, workspace_type="pim",
        user_id=body.user_id, role_name=body.role_name, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"Member assigned to project as {body.role_name}.", data=data)


@router.post(
    "/pim/projects/{project_id}/members/bulk",
    response_model=SuccessResponse[BulkAssignResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_create"))],
    summary="Bulk assign workspace members to PIM project",
)
async def bulk_assign_pim_project_members(
    project_id: uuid.UUID,
    body: BulkAssignMembersRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[BulkAssignResponse]:
    service = ProjectMemberService(session)
    data = await service.bulk_assign_members(
        project_id=project_id, workspace_type="pim",
        members_input=body.members, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"{data.added} members added, {data.skipped} skipped.", data=data)


@router.patch(
    "/pim/projects/{project_id}/members/{user_id}",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_edit"))],
    summary="Change a member's BIM role in a PIM project",
)
async def update_pim_project_member_role(
    project_id: uuid.UUID, user_id: uuid.UUID,
    body: UpdateProjectMemberRoleRequest,
    current_user: CurrentUser, session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.update_member_role(
        project_id=project_id, workspace_type="pim",
        user_id=user_id, role_name=body.role_name, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"Member role updated to {body.role_name}.", data=data)


@router.delete(
    "/pim/projects/{project_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_delete"))],
    summary="Remove a member from a PIM project",
)
async def remove_pim_project_member(
    project_id: uuid.UUID, user_id: uuid.UUID,
    current_user: CurrentUser, session: DatabaseSession,
) -> SuccessResponse:
    service = ProjectMemberService(session)
    await service.remove_member(project_id=project_id, workspace_type="pim", user_id=user_id, current_user=current_user)
    return SuccessResponse(success=True, message="Member removed from project.")

# ── AIM PROJECT MEMBERS ───────────────────────────────────────────────────────

@router.get(
    "/aim/projects/{project_id}/members",
    response_model=SuccessResponse[ProjectMemberListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_view"))],
    summary="List AIM project members",
)
async def list_aim_project_members(
    project_id: uuid.UUID, current_user: CurrentUser, session: DatabaseSession,
) -> SuccessResponse[ProjectMemberListResponse]:
    service = ProjectMemberService(session)
    data = await service.list_members(project_id, "aim")
    return SuccessResponse(success=True, message="Project members retrieved.", data=data)


@router.post(
    "/aim/projects/{project_id}/members",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_create"))],
    summary="Invite external user to AIM project by email",
)
async def invite_aim_project_member(
    project_id: uuid.UUID, body: InviteProjectMemberRequest,
    current_user: CurrentUser, session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.invite_member(
        project_id=project_id, workspace_type="aim",
        email=body.email, role_name=body.role_name, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"{body.email} added to project as {body.role_name}.", data=data)


@router.post(
    "/aim/projects/{project_id}/members/assign",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_create"))],
    summary="Assign a workspace member to AIM project by user_id",
)
async def assign_aim_project_member(
    project_id: uuid.UUID, body: AssignWorkspaceMemberRequest,
    current_user: CurrentUser, session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.assign_workspace_member(
        project_id=project_id, workspace_type="aim",
        user_id=body.user_id, role_name=body.role_name, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"Member assigned to project as {body.role_name}.", data=data)


@router.post(
    "/aim/projects/{project_id}/members/bulk",
    response_model=SuccessResponse[BulkAssignResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_create"))],
    summary="Bulk assign workspace members to AIM project",
)
async def bulk_assign_aim_project_members(
    project_id: uuid.UUID, body: BulkAssignMembersRequest,
    current_user: CurrentUser, session: DatabaseSession,
) -> SuccessResponse[BulkAssignResponse]:
    service = ProjectMemberService(session)
    data = await service.bulk_assign_members(
        project_id=project_id, workspace_type="aim",
        members_input=body.members, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"{data.added} members added, {data.skipped} skipped.", data=data)


@router.patch(
    "/aim/projects/{project_id}/members/{user_id}",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_edit"))],
    summary="Change a member's BIM role in an AIM project",
)
async def update_aim_project_member_role(
    project_id: uuid.UUID, user_id: uuid.UUID,
    body: UpdateProjectMemberRoleRequest,
    current_user: CurrentUser, session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.update_member_role(
        project_id=project_id, workspace_type="aim",
        user_id=user_id, role_name=body.role_name, current_user=current_user,
    )
    return SuccessResponse(success=True, message=f"Member role updated to {body.role_name}.", data=data)


@router.delete(
    "/aim/projects/{project_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_delete"))],
    summary="Remove a member from an AIM project",
)
async def remove_aim_project_member(
    project_id: uuid.UUID, user_id: uuid.UUID,
    current_user: CurrentUser, session: DatabaseSession,
) -> SuccessResponse:
    service = ProjectMemberService(session)
    await service.remove_member(project_id=project_id, workspace_type="aim", user_id=user_id, current_user=current_user)
    return SuccessResponse(success=True, message="Member removed from project.")
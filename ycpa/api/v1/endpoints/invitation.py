from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from ycpa.api.dependencies.rbac import ProjectGuard, WorkspaceGuard
from ycpa.core.auth.dependencies import CurrentUser
from ycpa.core.database.dependencies import DatabaseSession
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.schemas.requests.invitation import (
    AcceptInvitationRequest,
    SendInvitationRequest,
    SendWorkspaceInvitationRequest,
)
from ycpa.schemas.responses.invitation import (
    InvitationAcceptResponse,
    InvitationDetailResponse,
)
from ycpa.services.invitation import InvitationService

router = APIRouter(prefix="/invitations", tags=["Invitations"])



@router.post(
    "/pim/workspaces/{workspace_id}",
    response_model=SuccessResponse[InvitationDetailResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("pim", "admin"))],
    summary="Invite someone to PIM workspace via email",
)
async def send_pim_workspace_invitation(
    workspace_id:     UUID,
    body:             SendWorkspaceInvitationRequest,
    current_user:     CurrentUser,
    session:          DatabaseSession,
    background_tasks: BackgroundTasks,
) -> SuccessResponse[InvitationDetailResponse]:
    service = InvitationService(session)
    data = await service.send_workspace_invitation(
        workspace_id, body, "pim", current_user, background_tasks
    )
    return SuccessResponse(success=True, message=f"Invitation sent to {body.email}.", data=data)


@router.post(
    "/aim/workspaces/{workspace_id}",
    response_model=SuccessResponse[InvitationDetailResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(WorkspaceGuard("aim", "admin"))],
    summary="Invite someone to AIM workspace via email",
)
async def send_aim_workspace_invitation(
    workspace_id:     UUID,
    body:             SendWorkspaceInvitationRequest,
    current_user:     CurrentUser,
    session:          DatabaseSession,
    background_tasks: BackgroundTasks,
) -> SuccessResponse[InvitationDetailResponse]:
    service = InvitationService(session)
    data = await service.send_workspace_invitation(
        workspace_id, body, "aim", current_user, background_tasks
    )
    return SuccessResponse(success=True, message=f"Invitation sent to {body.email}.", data=data)



@router.post(
    "/pim/projects/{project_id}",
    response_model=SuccessResponse[InvitationDetailResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_create"))],
    summary="Invite user to PIM project via email",
)
async def send_pim_invitation(
    project_id:       UUID,
    body:             SendInvitationRequest,
    current_user:     CurrentUser,
    session:          DatabaseSession,
    background_tasks: BackgroundTasks,
) -> SuccessResponse[InvitationDetailResponse]:
    body.project_id = project_id
    service = InvitationService(session)
    data = await service.send_invitation(body, "pim", current_user, background_tasks)
    return SuccessResponse(success=True, message=f"Invitation sent to {body.email}.", data=data)

@router.get(
    "/my",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user's pending invitations",
)
async def get_my_invitations(
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse:
    from sqlalchemy import select
    from ycpa.models.invitation import Invitation
    from ycpa.models.user import User
    from ycpa.models.roles import Role
    from datetime import datetime, timezone

    invitations = await session.scalars(
        select(Invitation).where(
            Invitation.email == current_user.email,
            Invitation.status == "pending",
            Invitation.expires_at > datetime.now(timezone.utc),
        )
    )
    result = []
    for inv in invitations:
        inviter = await session.get(User, inv.invited_by)
        role = await session.get(Role, inv.role_id) if inv.role_id else None

        # Get project/workspace names
        project_name = None
        workspace_name = None
        if inv.project_id:
            from ycpa.models.workspace import PimProject, AimProject
            proj = await session.get(
                PimProject if inv.workspace_type == "pim" else AimProject,
                inv.project_id
            )
            if proj:
                project_name = proj.name
                from ycpa.models.workspace import PimWorkspace, AimWorkspace
                ws = await session.get(
                    PimWorkspace if inv.workspace_type == "pim" else AimWorkspace,
                    proj.workspace_id
                )
                workspace_name = ws.name if ws else None

        result.append({
            "token": inv.token,
            "workspace_type": inv.workspace_type,
            "project_name": project_name,
            "workspace_name": workspace_name,
            "role_name": role.name if role else "Member",
            "invited_by_name": inviter.full_name if inviter else "Someone",
            "expires_at": inv.expires_at.isoformat(),
            "status": inv.status,
        })

    return SuccessResponse(success=True, message="Invitations retrieved.", data=result)

@router.post(
    "/aim/projects/{project_id}",
    response_model=SuccessResponse[InvitationDetailResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_create"))],
    summary="Invite user to AIM project via email",
)
async def send_aim_invitation(
    project_id:       UUID,
    body:             SendInvitationRequest,
    current_user:     CurrentUser,
    session:          DatabaseSession,
    background_tasks: BackgroundTasks,
) -> SuccessResponse[InvitationDetailResponse]:
    body.project_id = project_id
    service = InvitationService(session)
    data = await service.send_invitation(body, "aim", current_user, background_tasks)
    return SuccessResponse(success=True, message=f"Invitation sent to {body.email}.", data=data)



@router.get(
    "/validate",
    response_model=SuccessResponse[InvitationDetailResponse],
    status_code=status.HTTP_200_OK,
    summary="Validate an invitation token (no auth required)",
)
async def validate_invitation(
    session: DatabaseSession,
    token:   str = Query(..., description="Invitation token from email link"),
) -> SuccessResponse[InvitationDetailResponse]:
    service = InvitationService(session)
    data = await service.validate_token(token)
    return SuccessResponse(success=True, message="Invitation is valid.", data=data)


@router.post(
    "/accept",
    response_model=SuccessResponse[InvitationAcceptResponse],
    status_code=status.HTTP_200_OK,
    summary="Accept an invitation (works for both workspace and project invites)",
)
async def accept_invitation(
    body:         AcceptInvitationRequest,
    current_user: CurrentUser,
    session:      DatabaseSession,
) -> SuccessResponse[InvitationAcceptResponse]:
    service = InvitationService(session)
    data = await service.accept_invitation(body.token, current_user)

    msg = (
        f"You've joined {data.workspace_name} as {data.role_name}."
        if data.invite_type == "workspace"
        else f"You've joined {data.project_name} as {data.role_name}."
    )
    return SuccessResponse(success=True, message=msg, data=data)
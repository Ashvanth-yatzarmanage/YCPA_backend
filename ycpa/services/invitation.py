import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.config import get_settings
from ycpa.core.email import build_invite_email, send_email
from ycpa.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from ycpa.models.invitation import Invitation
from ycpa.models.roles import Role
from ycpa.models.user import User
from ycpa.repositories.aim import AimProjectRepository, AimWorkspaceRepository
from ycpa.repositories.auth.users import UserRepository
from ycpa.repositories.invitation import InvitationRepository
from ycpa.repositories.pim import PimProjectRepository, PimWorkspaceRepository
from ycpa.schemas.requests.invitation import (
    SendInvitationRequest,
    SendWorkspaceInvitationRequest,
)
from ycpa.schemas.responses.invitation import (
    InvitationAcceptResponse,
    InvitationDetailResponse,
)
from ycpa.services.base import BaseService
from ycpa.services.rbac import WorkspaceType

logger = logging.getLogger(__name__)
settings = get_settings()

INVITE_EXPIRY_HOURS = 48


class InvitationService(BaseService):

    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.inv_repo      = InvitationRepository(session)
        self.user_repo     = UserRepository(session)
        self.pim_proj_repo = PimProjectRepository(session)
        self.aim_proj_repo = AimProjectRepository(session)
        self.pim_ws_repo   = PimWorkspaceRepository(session)
        self.aim_ws_repo   = AimWorkspaceRepository(session)

    def _proj_repo(self, workspace_type: WorkspaceType):
        return self.pim_proj_repo if workspace_type == "pim" else self.aim_proj_repo

    def _ws_repo(self, workspace_type: WorkspaceType):
        return self.pim_ws_repo if workspace_type == "pim" else self.aim_ws_repo


    async def send_invitation(
        self,
        body: SendInvitationRequest,
        workspace_type: WorkspaceType,
        current_user: User,
        background_tasks: BackgroundTasks,
    ) -> InvitationDetailResponse:
        proj_repo = self._proj_repo(workspace_type)
        ws_repo   = self._ws_repo(workspace_type)

        project = await proj_repo.get_by_id(body.project_id)
        if not project:
            raise NotFoundException("Project not found")

        workspace = await ws_repo.get_workspace_with_owner_check(project.workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        role = await self.session.scalar(
            select(Role).where(
                Role.name == body.role_name,
                Role.is_active.is_(True),
                Role.deleted_at.is_(None),
            )
        )
        if not role:
            raise NotFoundException(f"Role '{body.role_name}' not found")

        existing_user = await self.user_repo.get_by_email(body.email)
        if existing_user:
            existing_proj_member = await proj_repo.get_project_member(
                body.project_id, existing_user.id
            )
            if existing_proj_member:
                raise ConflictException(f"{body.email} is already a member of this project")

        existing_invite = await self.inv_repo.get_pending_by_email_and_project(
            body.email, body.project_id
        )
        if existing_invite:
            raise ConflictException(
                f"A pending invitation already exists for {body.email}. "
                f"It expires in {INVITE_EXPIRY_HOURS} hours."
            )

        token      = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_EXPIRY_HOURS)

        invitation = Invitation(
            token          = token,
            workspace_type = workspace_type,
            workspace_id   = project.workspace_id,
            project_id     = body.project_id,
            email          = body.email,
            role_id        = role.id,
            disciplines    = [],
            invited_by     = current_user.id,
            status         = "pending",
            expires_at     = expires_at,
            created_by     = current_user.id,
        )
        self.session.add(invitation)
        await self.session.flush()

        invite_link = f"{settings.FRONTEND_URL}/invite?token={token}&type={workspace_type}"
        html = build_invite_email(
            inviter_name     = current_user.full_name,
            project_name     = project.name,
            workspace_name   = workspace.name,
            role_name        = body.role_name,
            invite_link      = invite_link,
            expires_in_hours = INVITE_EXPIRY_HOURS,
        )

        try:
            background_tasks.add_task(
                send_email,
                to=body.email,
                subject=f"{current_user.full_name} invited you to {project.name} on YCPA",
                html_body=html,
            )
        except Exception:
            logger.warning("Email sending skipped (local env — no SMTP configured)")

        await self.log_audit(
            action         = "MEMBER_INVITED",
            resource_type  = f"{workspace_type}_project",
            resource_id    = str(body.project_id),
            user_id        = current_user.id,
            workspace_type = workspace_type,
            workspace_id   = project.workspace_id,
            project_id     = body.project_id,
            payload        = {"invitee_email": body.email, "role": body.role_name},
        )
        await self.session.commit()

        return InvitationDetailResponse(
            token           = token,
            email           = body.email,
            role_name       = body.role_name,
            project_name    = project.name,
            workspace_name  = workspace.name,
            workspace_type  = workspace_type,
            invited_by_name = current_user.full_name,
            expires_at      = expires_at,
            status          = "pending",
            invite_type     = "project",
        )


    async def send_workspace_invitation(
        self,
        workspace_id: UUID,
        body: SendWorkspaceInvitationRequest,
        workspace_type: WorkspaceType,
        current_user: User,
        background_tasks: BackgroundTasks,
    ) -> InvitationDetailResponse:
        ws_repo = self._ws_repo(workspace_type)

        workspace = await ws_repo.get_workspace_with_owner_check(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        existing_user = await self.user_repo.get_by_email(body.email)
        if existing_user:
            existing_ws_member = await ws_repo.get_member(workspace_id, existing_user.id)
            if existing_ws_member:
                raise ConflictException(f"{body.email} is already a member of this workspace")
            if existing_user.id == workspace.owner_id:
                raise ConflictException(f"{body.email} is the workspace owner")

        existing_invite = await self.inv_repo.get_pending_by_email_and_workspace(
            body.email, workspace_id
        )
        if existing_invite:
            raise ConflictException(
                f"A pending invitation already exists for {body.email}. "
                f"It expires in {INVITE_EXPIRY_HOURS} hours."
            )

        token      = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_EXPIRY_HOURS)

        invitation = Invitation(
            token          = token,
            workspace_type = workspace_type,
            workspace_id   = workspace_id,
            project_id     = None,
            email          = body.email,
            role_id        = None,
            disciplines    = [],
            invited_by     = current_user.id,
            status         = "pending",
            expires_at     = expires_at,
            created_by     = current_user.id,
        )
        self.session.add(invitation)
        await self.session.flush()

        invite_link = f"{settings.FRONTEND_URL}/invite?token={token}&type={workspace_type}"
        html = build_invite_email(
            inviter_name     = current_user.full_name,
            project_name     = workspace.name,
            workspace_name   = workspace.name,
            role_name        = "Member",
            invite_link      = invite_link,
            expires_in_hours = INVITE_EXPIRY_HOURS,
        )

        try:
            background_tasks.add_task(
                send_email,
                to=body.email,
                subject=f"{current_user.full_name} invited you to join {workspace.name} on YCPA",
                html_body=html,
            )
        except Exception:
            logger.warning("Email sending skipped (local env — no SMTP configured)")

        await self.log_audit(
            action         = "WORKSPACE_MEMBER_INVITED",
            resource_type  = f"{workspace_type}_workspace",
            resource_id    = str(workspace_id),
            user_id        = current_user.id,
            workspace_type = workspace_type,
            workspace_id   = workspace_id,
            payload        = {"invitee_email": body.email},
        )
        await self.session.commit()

        return InvitationDetailResponse(
            token           = token,
            email           = body.email,
            role_name       = "Member",
            project_name    = None,
            workspace_name  = workspace.name,
            workspace_type  = workspace_type,
            invited_by_name = current_user.full_name,
            expires_at      = expires_at,
            status          = "pending",
            invite_type     = "workspace",
        )


    async def validate_token(self, token: str) -> InvitationDetailResponse:
        invitation = await self.inv_repo.get_by_token(token)
        if not invitation:
            raise NotFoundException("Invitation not found or already used")

        now = datetime.now(timezone.utc)
        if invitation.expires_at < now:
            await self.inv_repo.mark_expired(token)
            await self.session.commit()
            raise BadRequestException("This invitation has expired")

        if invitation.status != "pending":
            raise BadRequestException(f"This invitation has already been {invitation.status}")

        workspace_type = invitation.workspace_type
        ws_repo        = self._ws_repo(workspace_type)

        workspace = await ws_repo.get_workspace_with_owner_check(invitation.workspace_id)
        inviter   = await self.user_repo.get_by_id(invitation.invited_by)

        is_workspace_invite = invitation.project_id is None

        if is_workspace_invite:
            return InvitationDetailResponse(
                token           = token,
                email           = invitation.email,
                role_name       = "Member",
                project_name    = None,
                workspace_name  = workspace.name if workspace else "Unknown Workspace",
                workspace_type  = workspace_type,
                invited_by_name = inviter.full_name if inviter else "A team member",
                expires_at      = invitation.expires_at,
                status          = invitation.status,
                invite_type     = "workspace",
            )

        proj_repo = self._proj_repo(workspace_type)
        project   = await proj_repo.get_by_id(invitation.project_id)
        role      = await self.session.scalar(
            select(Role).where(Role.id == invitation.role_id)
        )

        return InvitationDetailResponse(
            token           = token,
            email           = invitation.email,
            role_name       = role.name if role else "BIM Member",
            project_name    = project.name if project else "Unknown Project",
            workspace_name  = workspace.name if workspace else "Unknown Workspace",
            workspace_type  = workspace_type,
            invited_by_name = inviter.full_name if inviter else "A team member",
            expires_at      = invitation.expires_at,
            status          = invitation.status,
            invite_type     = "project",
        )


    async def accept_invitation(
        self, token: str, current_user: User
    ) -> InvitationAcceptResponse:
        invitation = await self.inv_repo.get_by_token(token)
        if not invitation:
            raise NotFoundException("Invitation not found or already used")

        now = datetime.now(timezone.utc)
        if invitation.expires_at < now:
            await self.inv_repo.mark_expired(token)
            await self.session.commit()
            raise BadRequestException("This invitation has expired")

        if invitation.status != "pending":
            raise BadRequestException(f"This invitation has already been {invitation.status}")

        if current_user.email.lower() != invitation.email.lower():
            raise ForbiddenException(
                f"This invitation was sent to {invitation.email}. "
                f"Please log in with that email."
            )

        workspace_type = invitation.workspace_type
        ws_repo        = self._ws_repo(workspace_type)
        workspace      = await ws_repo.get_workspace_with_owner_check(invitation.workspace_id)

        is_workspace_invite = invitation.project_id is None

        if is_workspace_invite:
            existing_ws = await ws_repo.get_member(invitation.workspace_id, current_user.id)
            if not existing_ws and (workspace and workspace.owner_id != current_user.id):
                await ws_repo.add_member(
                    workspace_id = invitation.workspace_id,
                    user_id      = current_user.id,
                    role         = "member",
                    invited_by   = invitation.invited_by,
                    created_by   = invitation.invited_by,
                )

            await self.inv_repo.mark_accepted(token, current_user.id)
            await self.log_audit(
                action         = "WORKSPACE_MEMBER_JOINED",
                resource_type  = f"{workspace_type}_workspace",
                resource_id    = str(invitation.workspace_id),
                user_id        = current_user.id,
                workspace_type = workspace_type,
                workspace_id   = invitation.workspace_id,
                payload        = {"via": "invitation"},
            )
            await self.session.commit()

            return InvitationAcceptResponse(
                workspace_id   = invitation.workspace_id,
                workspace_type = workspace_type,
                workspace_name = workspace.name if workspace else "Workspace",
                role_name      = "Member",
                invite_type    = "workspace",
                project_id     = None,
                project_name   = None,
            )

        proj_repo = self._proj_repo(workspace_type)

        role = await self.session.scalar(
            select(Role).where(Role.id == invitation.role_id)
        )
        if not role:
            raise NotFoundException("Invitation role no longer exists")

        existing_ws = await ws_repo.get_member(invitation.workspace_id, current_user.id)
        if not existing_ws and (workspace and workspace.owner_id != current_user.id):
            await ws_repo.add_member(
                workspace_id = invitation.workspace_id,
                user_id      = current_user.id,
                role         = "member",
                invited_by   = invitation.invited_by,
                created_by   = invitation.invited_by,
            )

        existing_proj = await proj_repo.get_project_member(
            invitation.project_id, current_user.id
        )
        if not existing_proj:
            await proj_repo.add_project_member(
                project_id = invitation.project_id,
                user_id    = current_user.id,
                role_id    = role.id,
                invited_by = invitation.invited_by,
                created_by = invitation.invited_by,
            )

        await self.inv_repo.mark_accepted(token, current_user.id)
        await self.log_audit(
            action         = "MEMBER_JOINED",
            resource_type  = f"{workspace_type}_project",
            resource_id    = str(invitation.project_id),
            user_id        = current_user.id,
            workspace_type = workspace_type,
            workspace_id   = invitation.workspace_id,
            project_id     = invitation.project_id,
            payload        = {"via": "invitation", "role": role.name},
        )
        await self.session.commit()

        project   = await proj_repo.get_by_id(invitation.project_id)
        ws_detail = await ws_repo.get_workspace_with_owner_check(invitation.workspace_id)

        return InvitationAcceptResponse(
            workspace_id   = invitation.workspace_id,
            workspace_type = workspace_type,
            workspace_name = ws_detail.name if ws_detail else "Workspace",
            role_name      = role.name,
            invite_type    = "project",
            project_id     = invitation.project_id,
            project_name   = project.name if project else "Project",
        )

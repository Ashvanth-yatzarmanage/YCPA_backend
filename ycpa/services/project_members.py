import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from ycpa.models.roles import Role
from ycpa.models.user import User
from ycpa.repositories.aim import AimProjectRepository, AimWorkspaceRepository
from ycpa.repositories.auth.users import UserRepository
from ycpa.repositories.pim import PimProjectRepository, PimWorkspaceRepository
from ycpa.schemas.responses.project_members import (
    AssignableWorkspaceMemberListResponse,
    AssignableWorkspaceMemberResponse,
    BulkAssignResponse,
    BulkAssignResult,
    ProjectMemberListResponse,
    ProjectMemberResponse,
)
from ycpa.services.base import BaseService
from ycpa.services.rbac import WorkspaceType

logger = logging.getLogger(__name__)


class ProjectMemberService(BaseService):

    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.user_repo     = UserRepository(session)
        self.pim_proj_repo = PimProjectRepository(session)
        self.aim_proj_repo = AimProjectRepository(session)
        self.pim_ws_repo   = PimWorkspaceRepository(session)
        self.aim_ws_repo   = AimWorkspaceRepository(session)

    def _proj_repo(self, workspace_type: WorkspaceType):
        return self.pim_proj_repo if workspace_type == "pim" else self.aim_proj_repo

    def _ws_repo(self, workspace_type: WorkspaceType):
        return self.pim_ws_repo if workspace_type == "pim" else self.aim_ws_repo


    async def _get_role_by_name(self, role_name: str) -> Role:
        role = await self.session.scalar(
            select(Role).where(
                Role.name == role_name,
                Role.is_active.is_(True),
                Role.deleted_at.is_(None),
            )
        )
        if not role:
            raise NotFoundException(f"Role '{role_name}' not found")
        return role

    async def _build_member_response(
        self, member, user: User, role: Role
    ) -> ProjectMemberResponse:
        return ProjectMemberResponse(
            user_id=user.id,
            role_id=role.id,
            role_name=role.name,
            full_name=user.full_name,
            email=user.email,
            avatar_url=user.avatar_url,
            joined_at=member.joined_at,
        )


    async def list_members(
        self,
        project_id: UUID,
        workspace_type: WorkspaceType,
    ) -> ProjectMemberListResponse:
        rows = await self._proj_repo(workspace_type).get_project_members_with_users(project_id)

        members = []
        for member, user in rows:
            if getattr(member, "is_share_only", False):
                continue
            role = await self.session.scalar(
                select(Role).where(Role.id == member.role_id)
            )
            if role:
                members.append(await self._build_member_response(member, user, role))

        return ProjectMemberListResponse(members=members, total=len(members))

    # ── INVITE BY EMAIL (external / new users) ────────────────────────────────

    async def invite_member(
        self,
        project_id: UUID,
        workspace_type: WorkspaceType,
        email: str,
        role_name: str,
        current_user: User,
    ) -> ProjectMemberResponse:

        proj_repo = self._proj_repo(workspace_type)

        invitee = await self.user_repo.get_by_email(email)
        if not invitee:
            raise NotFoundException(f"No user found with email {email}")
        if not invitee.is_active:
            raise ForbiddenException("This user account is inactive")

        role = await self._get_role_by_name(role_name)

        project = await proj_repo.get_by_id(project_id)
        if not project:
            raise NotFoundException("Project not found")

        existing = await proj_repo.get_project_member(project_id, invitee.id)
        if existing:
            raise ConflictException(f"{email} is already a member of this project")

        member = await proj_repo.add_project_member(
            project_id=project_id,
            user_id=invitee.id,
            role_id=role.id,
            invited_by=current_user.id,
            created_by=current_user.id,
        )

        await self.log_audit(
            action="MEMBER_INVITED",
            resource_type=f"{workspace_type}_project",
            resource_id=str(project_id),
            user_id=current_user.id,
            workspace_type=workspace_type,
            project_id=project_id,
            payload={
                "invitee_email": email,
                "role": role_name,
                "workspace_id": str(project.workspace_id),
            },
        )
        await self.session.commit()

        return await self._build_member_response(member, invitee, role)


    async def assign_workspace_member(
        self,
        project_id: UUID,
        workspace_type: WorkspaceType,
        user_id: UUID,
        role_name: str,
        current_user: User,
    ) -> ProjectMemberResponse:

        proj_repo = self._proj_repo(workspace_type)

        assignee = await self.user_repo.get_by_id(user_id)
        if not assignee:
            raise NotFoundException("User not found")
        if not assignee.is_active:
            raise ForbiddenException("This user account is inactive")

        role = await self._get_role_by_name(role_name)

        project = await proj_repo.get_by_id(project_id)
        if not project:
            raise NotFoundException("Project not found")

        existing = await proj_repo.get_project_member(project_id, user_id)
        if existing:
            raise ConflictException(f"{assignee.email} is already a member of this project")

        member = await proj_repo.add_project_member(
            project_id=project_id,
            user_id=user_id,
            role_id=role.id,
            invited_by=current_user.id,
            created_by=current_user.id,
        )

        await self.log_audit(
            action="MEMBER_ASSIGNED",
            resource_type=f"{workspace_type}_project",
            resource_id=str(project_id),
            user_id=current_user.id,
            workspace_type=workspace_type,
            project_id=project_id,
            payload={
                "assigned_user_id": str(user_id),
                "assigned_email": assignee.email,
                "role": role_name,
            },
        )
        await self.session.commit()

        return await self._build_member_response(member, assignee, role)


    async def bulk_assign_members(
        self,
        project_id: UUID,
        workspace_type: WorkspaceType,
        members_input: list,
        current_user: User,
    ) -> BulkAssignResponse:

        proj_repo = self._proj_repo(workspace_type)

        project = await proj_repo.get_by_id(project_id)
        if not project:
            raise NotFoundException("Project not found")

        results: list[BulkAssignResult] = []
        to_insert: list[dict] = []

        for req in members_input:
            user = await self.user_repo.get_by_id(req.user_id)
            if not user or not user.is_active:
                results.append(BulkAssignResult(
                    user_id=req.user_id,
                    email="unknown",
                    full_name="Unknown",
                    status="skipped",
                ))
                continue

            existing = await proj_repo.get_project_member(project_id, req.user_id)
            if existing:
                results.append(BulkAssignResult(
                    user_id=req.user_id,
                    email=user.email,
                    full_name=user.full_name,
                    status="skipped",
                ))
                continue

            role = await self._get_role_by_name(req.role_name)
            to_insert.append({"user_id": req.user_id, "role_id": role.id})
            results.append(BulkAssignResult(
                user_id=req.user_id,
                email=user.email,
                full_name=user.full_name,
                status="added",
                role_name=req.role_name,
            ))

        if to_insert:
            await proj_repo.bulk_add_project_members(
                project_id=project_id,
                entries=to_insert,
                invited_by=current_user.id,
                created_by=current_user.id,
            )

        added   = sum(1 for r in results if r.status == "added")
        skipped = sum(1 for r in results if r.status == "skipped")

        await self.log_audit(
            action="MEMBERS_BULK_ASSIGNED",
            resource_type=f"{workspace_type}_project",
            resource_id=str(project_id),
            user_id=current_user.id,
            workspace_type=workspace_type,
            project_id=project_id,
            payload={"added": added, "skipped": skipped, "total": len(results)},
        )
        await self.session.commit()

        return BulkAssignResponse(
            results=results,
            added=added,
            skipped=skipped,
            total=len(results),
        )


    async def get_assignable_members(
        self,
        workspace_id: UUID,
        project_id: UUID,
        workspace_type: WorkspaceType,
    ) -> AssignableWorkspaceMemberListResponse:

        ws_repo = self._ws_repo(workspace_type)

        rows = await ws_repo.get_assignable_members(workspace_id, project_id)
        members = [
            AssignableWorkspaceMemberResponse(
                user_id=user.id,
                full_name=user.full_name,
                email=user.email,
                avatar_url=user.avatar_url,
                workspace_role=ws_member.role,
            )
            for ws_member, user in rows
        ]

        owner_row = await ws_repo.get_owner_as_assignable(workspace_id, project_id)
        if owner_row:
            _, owner_user = owner_row
            already_added_ids = {m.user_id for m in members}
            if owner_user.id not in already_added_ids:
                members.insert(0, AssignableWorkspaceMemberResponse(
                    user_id=owner_user.id,
                    full_name=owner_user.full_name,
                    email=owner_user.email,
                    avatar_url=owner_user.avatar_url,
                    workspace_role="owner",
                ))

        return AssignableWorkspaceMemberListResponse(
            members=members,
            total=len(members),
        )


    async def update_member_role(
        self,
        project_id: UUID,
        workspace_type: WorkspaceType,
        user_id: UUID,
        role_name: str,
        current_user: User,
    ) -> ProjectMemberResponse:
        proj_repo = self._proj_repo(workspace_type)

        member      = await proj_repo.get_project_member(project_id, user_id)
        new_role    = await self._get_role_by_name(role_name)
        target_user = await self.user_repo.get_by_id(user_id)

        if not member:
            raise NotFoundException("Member not found in this project")
        if not target_user:
            raise NotFoundException("User not found")

        old_role = await self.session.scalar(
            select(Role).where(Role.id == member.role_id)
        )

        updated = await proj_repo.update_project_member_role(project_id, user_id, new_role.id)

        await self.log_audit(
            action="MEMBER_ROLE_CHANGED",
            resource_type=f"{workspace_type}_project",
            resource_id=str(project_id),
            user_id=current_user.id,
            workspace_type=workspace_type,
            project_id=project_id,
            changed_from={"role": old_role.name if old_role else None},
            changed_to={"role": role_name},
            payload={"target_user_id": str(user_id)},
        )
        await self.session.commit()

        return await self._build_member_response(updated, target_user, new_role)


    async def remove_member(
        self,
        project_id: UUID,
        workspace_type: WorkspaceType,
        user_id: UUID,
        current_user: User,
    ) -> None:
        proj_repo = self._proj_repo(workspace_type)

        member = await proj_repo.get_project_member(project_id, user_id)
        if not member:
            raise NotFoundException("Member not found in this project")

        if user_id == current_user.id:
            rows = await proj_repo.get_project_members_with_users(project_id)
            role = await self.session.scalar(
                select(Role).where(Role.id == member.role_id)
            )
            if role and role.name == "BIM Manager":
                manager_count = sum(
                    1 for m, _ in rows
                    if str(m.role_id) == str(member.role_id)
                )
                if manager_count <= 1:
                    raise ForbiddenException(
                        "Cannot remove the last BIM Manager from the project"
                    )

        removed = await proj_repo.remove_project_member(project_id, user_id)
        if not removed:
            raise NotFoundException("Member not found")

        await self.log_audit(
            action="MEMBER_REMOVED",
            resource_type=f"{workspace_type}_project",
            resource_id=str(project_id),
            user_id=current_user.id,
            workspace_type=workspace_type,
            project_id=project_id,
            payload={"removed_user_id": str(user_id)},
        )
        await self.session.commit()


# ─────────────────────────────────────────────────────────────────────────────


# ycpa/api/v1/endpoints/project_members.py

import uuid
from fastapi import APIRouter, Depends, Query, status

from ycpa.api.dependencies.rbac import ProjectGuard, WorkspaceGuard
from ycpa.core.auth.dependencies import CurrentUser
from ycpa.core.database.dependencies import DatabaseSession
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.schemas.requests.project_members import (
    InviteProjectMemberRequest,
    AssignWorkspaceMemberRequest,
    BulkAssignMembersRequest,
    UpdateProjectMemberRoleRequest,
)
from ycpa.schemas.responses.project_members import (
    ProjectMemberResponse,
    ProjectMemberListResponse,
    AssignableWorkspaceMemberListResponse,
    BulkAssignResponse,
)
from ycpa.services.project_members import ProjectMemberService

router = APIRouter(tags=["Project Members"])


# ─────────────────────────────────────────────────────────────────────────────
# SHARED: ASSIGNABLE MEMBERS PICKER
# Called by frontend before opening the "Add from team" modal.
# Works for both PIM and AIM — same logic, different workspace type.
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/pim/workspaces/{workspace_id}/members/assignable",
    response_model=SuccessResponse[AssignableWorkspaceMemberListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(WorkspaceGuard("pim", "member"))],
    summary="Get PIM workspace members not yet in the given project (for team picker)",
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
    summary="Get AIM workspace members not yet in the given project (for team picker)",
)
async def get_aim_assignable_members(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
    project_id: uuid.UUID = Query(..., description="Target project to check against"),

) -> SuccessResponse[AssignableWorkspaceMemberListResponse]:
    service = ProjectMemberService(session)
    data = await service.get_assignable_members(workspace_id, project_id, "aim")
    return SuccessResponse(success=True, message="Assignable members retrieved.", data=data)


# ─────────────────────────────────────────────────────────────────────────────
# PIM PROJECT MEMBERS
# ─────────────────────────────────────────────────────────────────────────────

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
        project_id=project_id,
        workspace_type="pim",
        email=body.email,
        role_name=body.role_name,
        current_user=current_user,
    )
    return SuccessResponse(
        success=True,
        message=f"{body.email} added to project as {body.role_name}.",
        data=data,
    )


@router.post(
    "/pim/projects/{project_id}/members/assign",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_create"))],
    summary="Assign a workspace member to PIM project by user_id (primary team flow)",
)
async def assign_pim_project_member(
    project_id: uuid.UUID,
    body: AssignWorkspaceMemberRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.assign_workspace_member(
        project_id=project_id,
        workspace_type="pim",
        user_id=body.user_id,
        role_name=body.role_name,
        current_user=current_user,
    )
    return SuccessResponse(
        success=True,
        message=f"Member assigned to project as {body.role_name}.",
        data=data,
    )


@router.post(
    "/pim/projects/{project_id}/members/bulk",
    response_model=SuccessResponse[BulkAssignResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_create"))],
    summary="Bulk assign workspace members to PIM project (new project setup)",
)
async def bulk_assign_pim_project_members(
    project_id: uuid.UUID,
    body: BulkAssignMembersRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[BulkAssignResponse]:
    service = ProjectMemberService(session)
    data = await service.bulk_assign_members(
        project_id=project_id,
        workspace_type="pim",
        members_input=body.members,
        current_user=current_user,
    )
    return SuccessResponse(
        success=True,
        message=f"{data.added} members added, {data.skipped} skipped.",
        data=data,
    )


@router.patch(
    "/pim/projects/{project_id}/members/{user_id}",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_edit"))],
    summary="Change a member's BIM role in a PIM project",
)
async def update_pim_project_member_role(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpdateProjectMemberRoleRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.update_member_role(
        project_id=project_id,
        workspace_type="pim",
        user_id=user_id,
        role_name=body.role_name,
        current_user=current_user,
    )
    return SuccessResponse(
        success=True,
        message=f"Member role updated to {body.role_name}.",
        data=data,
    )


@router.delete(
    "/pim/projects/{project_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("pim", "team", "can_delete"))],
    summary="Remove a member from a PIM project",
)
async def remove_pim_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse:
    service = ProjectMemberService(session)
    await service.remove_member(
        project_id=project_id,
        workspace_type="pim",
        user_id=user_id,
        current_user=current_user,
    )
    # ← no commit needed, service already did it
    return SuccessResponse(success=True, message="Member removed from project.")


# ─────────────────────────────────────────────────────────────────────────────
# AIM PROJECT MEMBERS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/aim/projects/{project_id}/members",
    response_model=SuccessResponse[ProjectMemberListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_view"))],
    summary="List AIM project members",
)
async def list_aim_project_members(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
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
    project_id: uuid.UUID,
    body: InviteProjectMemberRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.invite_member(
        project_id=project_id,
        workspace_type="aim",
        email=body.email,
        role_name=body.role_name,
        current_user=current_user,
    )
    return SuccessResponse(
        success=True,
        message=f"{body.email} added to project as {body.role_name}.",
        data=data,
    )


@router.post(
    "/aim/projects/{project_id}/members/assign",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_create"))],
    summary="Assign a workspace member to AIM project by user_id (primary team flow)",
)
async def assign_aim_project_member(
    project_id: uuid.UUID,
    body: AssignWorkspaceMemberRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.assign_workspace_member(
        project_id=project_id,
        workspace_type="aim",
        user_id=body.user_id,
        role_name=body.role_name,
        current_user=current_user,
    )
    return SuccessResponse(
        success=True,
        message=f"Member assigned to project as {body.role_name}.",
        data=data,
    )


@router.post(
    "/aim/projects/{project_id}/members/bulk",
    response_model=SuccessResponse[BulkAssignResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_create"))],
    summary="Bulk assign workspace members to AIM project (new project setup)",
)
async def bulk_assign_aim_project_members(
    project_id: uuid.UUID,
    body: BulkAssignMembersRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[BulkAssignResponse]:
    service = ProjectMemberService(session)
    data = await service.bulk_assign_members(
        project_id=project_id,
        workspace_type="aim",
        members_input=body.members,
        current_user=current_user,
    )
    return SuccessResponse(
        success=True,
        message=f"{data.added} members added, {data.skipped} skipped.",
        data=data,
    )


@router.patch(
    "/aim/projects/{project_id}/members/{user_id}",
    response_model=SuccessResponse[ProjectMemberResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_edit"))],
    summary="Change a member's BIM role in an AIM project",
)
async def update_aim_project_member_role(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpdateProjectMemberRoleRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[ProjectMemberResponse]:
    service = ProjectMemberService(session)
    data = await service.update_member_role(
        project_id=project_id,
        workspace_type="aim",
        user_id=user_id,
        role_name=body.role_name,
        current_user=current_user,
    )
    return SuccessResponse(
        success=True,
        message=f"Member role updated to {body.role_name}.",
        data=data,
    )


@router.delete(
    "/aim/projects/{project_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(ProjectGuard("aim", "team", "can_delete"))],
    summary="Remove a member from an AIM project",
)
async def remove_aim_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse:
    service = ProjectMemberService(session)
    await service.remove_member(
        project_id=project_id,
        workspace_type="aim",
        user_id=user_id,
        current_user=current_user,
    )
    return SuccessResponse(success=True, message="Member removed from project.")
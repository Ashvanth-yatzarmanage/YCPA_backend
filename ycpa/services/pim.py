import asyncio
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from ycpa.models.roles import Role
from ycpa.models.user import User
from ycpa.models.workspace import PimProject, PimWorkspace
from ycpa.repositories.auth.users import UserRepository
from ycpa.repositories.pim import PimProjectRepository, PimWorkspaceRepository
from ycpa.schemas.requests.pim import (
    CreatePimProjectRequest,
    InviteMemberRequest,
    UpdatePimWorkspaceRequest,
    UpdateWorkspaceMemberRoleRequest,
)
from ycpa.schemas.responses.pim import (
    PimProjectResponse,
    PimWorkspaceDetailResponse,
    PimWorkspaceListResponse,
    PimWorkspaceMemberResponse,
    PimWorkspaceResponse,
)
from ycpa.services.base import BaseService
from ycpa.services.rbac import RBACService

logger = logging.getLogger(__name__)


class PimService(BaseService):

    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.ws_repo   = PimWorkspaceRepository(session)
        self.proj_repo = PimProjectRepository(session)
        self.user_repo = UserRepository(session)


    async def list_workspaces(self, current_user: User) -> PimWorkspaceListResponse:
        my_workspaces, shared = await asyncio.gather(
            self.ws_repo.get_my_workspaces(current_user.id),
            self.ws_repo.get_shared_workspaces(current_user.id),
        )

        mine_tasks   = [self._enrich_workspace(ws, role="owner") for ws in my_workspaces]
        shared_tasks = [self._enrich_shared_workspace(ws, current_user.id) for ws in shared]

        all_results = await asyncio.gather(*mine_tasks, *shared_tasks)

        enriched_mine   = list(all_results[:len(mine_tasks)])
        enriched_shared = list(all_results[len(mine_tasks):])

        return PimWorkspaceListResponse(
            my_workspaces=enriched_mine,
            shared_workspaces=enriched_shared,
            total=len(enriched_mine) + len(enriched_shared),
        )


    async def get_workspace(
        self, workspace_id: UUID, current_user: User, is_owner: bool = False
    ) -> PimWorkspaceDetailResponse:
        ws = await self.ws_repo.get_workspace_with_owner_check(workspace_id)
        if not ws:
            raise NotFoundException("PIM workspace not found")

        if is_owner or ws.owner_id == current_user.id:
            role = "owner"
        else:
            ws_member = await self.ws_repo.get_member(workspace_id, current_user.id)
            role = ws_member.role if ws_member else "member"

        projects, members_raw = await asyncio.gather(
            self.list_projects(workspace_id, current_user, is_owner=is_owner),
            self.ws_repo.get_members_with_users(workspace_id),
        )

        members = [
            PimWorkspaceMemberResponse(
                user_id=user.id, role=mem.role, joined_at=mem.joined_at,
                full_name=user.full_name, email=user.email, avatar_url=user.avatar_url,
            )
            for mem, user in members_raw
        ]
        if not any(m.user_id == ws.owner_id for m in members):
            owner = await self.user_repo.get_by_id(ws.owner_id)
            if owner:
                members.insert(0, PimWorkspaceMemberResponse(
                    user_id=owner.id, role="owner", joined_at=ws.created_at,
                    full_name=owner.full_name, email=owner.email, avatar_url=owner.avatar_url,
                ))

        base = await self._enrich_workspace(ws, role=role)
        return PimWorkspaceDetailResponse(**base.model_dump(), projects=projects, members=members)


    async def create_workspace(self, body, current_user):
        pim_sub, owned_count = await asyncio.gather(
            self.user_repo.get_pim_subscription(current_user.id),
            self.ws_repo.count_workspaces_owned(current_user.id),
        )
        if not pim_sub:
            raise BadRequestException("PIM subscription not found")
        if owned_count >= pim_sub.max_pim_workspaces:
            raise BadRequestException(
                f"Free plan allows {pim_sub.max_pim_workspaces} PIM workspace. Upgrade to create more."
            )

        ws = PimWorkspace(
            owner_id=current_user.id,
            name=body.name,
            description=body.description,
            is_active=True,
            created_by=current_user.id,
        )
        ws = await self.ws_repo.create(ws)

        await self.ws_repo.add_member(
            workspace_id=ws.id,
            user_id=current_user.id,
            role="admin",
            invited_by=current_user.id,
            created_by=current_user.id,
        )

        await self.log_audit(
            action="WORKSPACE_CREATED", resource_type="pim_workspace",
            resource_id=str(ws.id), user_id=current_user.id,
            workspace_type="pim", workspace_id=ws.id,
            payload={"name": ws.name},
        )

        result = await self.get_workspace(ws.id, current_user)
        await self.session.commit()
        return result


    async def update_workspace(
        self, workspace_id: UUID, body: UpdatePimWorkspaceRequest, current_user: User
    ) -> PimWorkspaceDetailResponse:
        ws = await self.ws_repo.get_workspace_with_owner_check(workspace_id)
        if not ws:
            raise NotFoundException("PIM workspace not found")
        values = {
            k: v for k, v in {
                "name": body.name,
                "description": body.description,
            }.items() if v is not None
        }
        if values:
            await self.ws_repo.update_by_id(workspace_id, values)
            await self.log_audit(
                action="WORKSPACE_UPDATED", resource_type="pim_workspace",
                resource_id=str(workspace_id), user_id=current_user.id,
                workspace_type="pim", workspace_id=workspace_id,
                payload={"updated_fields": list(values.keys())},
            )

        result = await self.get_workspace(workspace_id, current_user)
        if values:
            await self.session.commit()
        return result


    async def list_workspace_members(
        self, workspace_id: UUID, current_user: User
    ) -> list[PimWorkspaceMemberResponse]:
        ws = await self.ws_repo.get_workspace_with_owner_check(workspace_id)
        if not ws:
            raise NotFoundException("PIM workspace not found")

        members_raw = await self.ws_repo.get_members_with_users(workspace_id)
        members = [
            PimWorkspaceMemberResponse(
                user_id=user.id, role=mem.role, joined_at=mem.joined_at,
                full_name=user.full_name, email=user.email, avatar_url=user.avatar_url,
            )
            for mem, user in members_raw
        ]
        if not any(m.user_id == ws.owner_id for m in members):
            owner = await self.user_repo.get_by_id(ws.owner_id)
            if owner:
                members.insert(0, PimWorkspaceMemberResponse(
                    user_id=owner.id, role="owner", joined_at=ws.created_at,
                    full_name=owner.full_name, email=owner.email, avatar_url=owner.avatar_url,
                ))
        return members


    async def update_workspace_member_role(
        self, workspace_id: UUID, user_id: UUID,
        body: UpdateWorkspaceMemberRoleRequest, current_user: User,
    ) -> PimWorkspaceMemberResponse:
        ws = await self.ws_repo.get_workspace_with_owner_check(workspace_id)
        if not ws:
            raise NotFoundException("PIM workspace not found")
        if user_id == ws.owner_id:
            raise ForbiddenException("Cannot change the workspace owner's role")
        if body.role == "admin" and current_user.id != ws.owner_id:
            raise ForbiddenException("Only the workspace owner can assign the admin role")

        member = await self.ws_repo.get_member(workspace_id, user_id)
        if not member:
            raise NotFoundException("Member not found in this workspace")
        if member.role == body.role:
            user = await self.user_repo.get_by_id(user_id)
            return PimWorkspaceMemberResponse(
                user_id=user.id, role=member.role, joined_at=member.joined_at,
                full_name=user.full_name, email=user.email, avatar_url=user.avatar_url,
            )

        updated = await self.ws_repo.update_member_role(workspace_id, user_id, body.role)
        user    = await self.user_repo.get_by_id(user_id)
        await self.log_audit(
            action="MEMBER_ROLE_CHANGED", resource_type="pim_workspace",
            resource_id=str(workspace_id), user_id=current_user.id,
            workspace_type="pim", workspace_id=workspace_id,
            payload={"target_user_id": str(user_id), "old_role": member.role, "new_role": body.role},
        )
        await self.session.commit()
        return PimWorkspaceMemberResponse(
            user_id=user.id, role=updated.role, joined_at=updated.joined_at,
            full_name=user.full_name, email=user.email, avatar_url=user.avatar_url,
        )


    async def invite_member(
        self, workspace_id: UUID, body: InviteMemberRequest, current_user: User
    ) -> PimWorkspaceMemberResponse:
        ws, invitee = await asyncio.gather(
            self.ws_repo.get_workspace_with_owner_check(workspace_id),
            self.user_repo.get_by_email(body.email),
        )
        if not ws:      raise NotFoundException("PIM workspace not found")
        if not invitee: raise NotFoundException(f"No user found with email {body.email}")
        if invitee.id == ws.owner_id:
            raise ConflictException("Cannot invite the workspace owner")

        pim_sub, current_count, existing = await asyncio.gather(
            self.user_repo.get_pim_subscription(current_user.id),
            self.ws_repo.count_members(workspace_id),
            self.ws_repo.get_member(workspace_id, invitee.id),
        )
        if existing:
            raise ConflictException(f"{body.email} is already a workspace member")
        if pim_sub and current_count >= pim_sub.max_members_per_workspace:
            raise BadRequestException(
                f"Member limit reached ({pim_sub.max_members_per_workspace}). Upgrade to add more."
            )

        member = await self.ws_repo.add_member(
            workspace_id=workspace_id, user_id=invitee.id, role=body.role,
            invited_by=current_user.id, created_by=current_user.id,
        )
        await self.log_audit(
            action="MEMBER_INVITED", resource_type="pim_workspace",
            resource_id=str(workspace_id), user_id=current_user.id,
            workspace_type="pim", workspace_id=workspace_id,
            payload={"invitee_email": body.email, "role": body.role},
        )
        await self.session.commit()
        return PimWorkspaceMemberResponse(
            user_id=invitee.id, role=member.role, joined_at=member.joined_at,
            full_name=invitee.full_name, email=invitee.email, avatar_url=invitee.avatar_url,
        )


    async def remove_member(self, workspace_id: UUID, user_id: UUID, current_user: User) -> None:
        ws = await self.ws_repo.get_workspace_with_owner_check(workspace_id)
        if not ws:
            raise NotFoundException("PIM workspace not found")
        if user_id == ws.owner_id:
            raise ForbiddenException("Cannot remove the workspace owner")
        if not await self.ws_repo.remove_member(workspace_id, user_id):
            raise NotFoundException("Member not found in this workspace")
        await self.log_audit(
            action="MEMBER_REMOVED", resource_type="pim_workspace",
            resource_id=str(workspace_id), user_id=current_user.id,
            workspace_type="pim", workspace_id=workspace_id,
            payload={"removed_user_id": str(user_id)},
        )
        await self.session.commit()


    async def list_projects(
        self, workspace_id: UUID, current_user: User, is_owner: bool = False
    ) -> list[PimProjectResponse]:
        ws = await self.ws_repo.get_workspace_with_owner_check(workspace_id)
        if not ws:
            raise NotFoundException("PIM workspace not found")

        ws_member = await self.ws_repo.get_member(workspace_id, current_user.id)
        ws_role   = ws_member.role if ws_member else None
        is_admin_or_owner = is_owner or ws.owner_id == current_user.id or ws_role == "admin"

        if is_admin_or_owner:
            projects = await self.proj_repo.get_projects_by_workspace(workspace_id)
        else:
            projects = await self.proj_repo.get_projects_by_workspace_for_member(
                workspace_id, current_user.id
            )

        if not projects:
            return []

        project_ids = [p.id for p in projects]
        member_counts, file_counts = await asyncio.gather(
            self.proj_repo.batch_count_members(project_ids),
            self.proj_repo.batch_count_files(project_ids),
        )
        return [
            PimProjectResponse(
                id=p.id, workspace_id=p.workspace_id,
                name=p.name, description=p.description,
                location=p.location,
                project_code=getattr(p, "project_code", None),
                thumbnail_url=getattr(p, "thumbnail_url", None),
                status=p.status,
                import_locked=getattr(p, "import_locked", False),
                created_at=p.created_at, updated_at=p.updated_at,
                member_count=member_counts.get(p.id, 0),
                file_count=file_counts.get(p.id, 0),
            )
            for p in projects
        ]

    async def create_project(
        self, workspace_id: UUID, body: CreatePimProjectRequest, current_user: User
    ) -> PimProjectResponse:
        ws = await self.ws_repo.get_workspace_with_owner_check(workspace_id)
        if not ws:
            raise NotFoundException("PIM workspace not found")

        pim_sub = await self.user_repo.get_pim_subscription(current_user.id)
        if pim_sub:
            proj_count = await self.proj_repo.count_projects_in_workspace(workspace_id)
            if proj_count >= pim_sub.max_projects_per_pim_workspace:
                raise BadRequestException(
                    f"Free plan allows {pim_sub.max_projects_per_pim_workspace} project per workspace. Upgrade to create more."
                )

        project = PimProject(
            workspace_id=workspace_id, name=body.name,
            description=body.description, location=body.location,
            project_code=getattr(body, "project_code", None),
            status="active", created_by=current_user.id,
        )
        project = await self.proj_repo.create(project)

        bim_manager_role = await self.session.scalar(
            select(Role).where(Role.name == "BIM Manager", Role.is_active.is_(True), Role.deleted_at.is_(None))
        )
        if bim_manager_role:
            await self.proj_repo.add_project_member(
                project_id=project.id, user_id=current_user.id,
                role_id=bim_manager_role.id, invited_by=current_user.id, created_by=current_user.id,
            )

        await self.log_audit(
            action="PROJECT_CREATED", resource_type="pim_project",
            resource_id=str(project.id), user_id=current_user.id,
            workspace_type="pim", workspace_id=workspace_id,
            payload={"name": project.name},
        )
        result = await self._enrich_project(project)
        await self.session.commit()
        return result

    async def get_project(self, project_id: UUID, current_user: User) -> PimProjectResponse:
        project = await self.proj_repo.get_by_id(project_id)
        if not project:
            raise NotFoundException("PIM project not found")
        if current_user.platform_role != "super_admin":
            role = await RBACService.get_workspace_role(
                self.session, current_user.id, project.workspace_id, "pim"
            )
            if role is None:
                raise ForbiddenException("You don't have access to this project.")
        return await self._enrich_project(project)

    async def delete_project(self, project_id: UUID, current_user: User) -> None:
        project = await self.proj_repo.get_by_id(project_id)
        if not project:
            raise NotFoundException("Project not found")
        if current_user.platform_role != "super_admin":
            role = await RBACService.get_workspace_role(
                self.session, current_user.id, project.workspace_id, "pim"
            )
            if not RBACService.workspace_role_meets(role, "admin"):
                raise ForbiddenException(
                    "Only the workspace owner or an admin can delete a project."
                )
        await self.proj_repo.soft_delete(project_id, current_user.id)
        await self.session.commit()


    async def _enrich_workspace(self, ws: PimWorkspace, role: str) -> PimWorkspaceResponse:
        proj_count, member_count = await asyncio.gather(
            self.proj_repo.count_projects_in_workspace(ws.id),
            self.ws_repo.count_members(ws.id),
        )
        return PimWorkspaceResponse(
            id=ws.id, name=ws.name, description=ws.description,
            avatar_url=getattr(ws, "avatar_url", None),
            is_active=ws.is_active, created_at=ws.created_at, updated_at=ws.updated_at,
            role=role, owner_id=ws.owner_id,
            project_count=proj_count, member_count=member_count,
        )

    async def _enrich_shared_workspace(self, ws: PimWorkspace, user_id) -> PimWorkspaceResponse:
        member = await self.ws_repo.get_member(ws.id, user_id)
        role = member.role if member else "member"
        return await self._enrich_workspace(ws, role=role)

    async def _enrich_project(self, project: PimProject) -> PimProjectResponse:
        member_count = await self.proj_repo.count_members_in_project(project.id)
        return PimProjectResponse(
            id=project.id, workspace_id=project.workspace_id,
            name=project.name, description=project.description,
            location=project.location,
            project_code=getattr(project, "project_code", None),
            thumbnail_url=getattr(project, "thumbnail_url", None),
            status=project.status,
            import_locked=getattr(project, "import_locked", False),
            created_at=project.created_at, updated_at=project.updated_at,
            member_count=member_count, file_count=0,
        )

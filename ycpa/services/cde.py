import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.config import get_settings
from ycpa.core.email import build_share_email, send_email
from ycpa.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from ycpa.models.roles import Role
from ycpa.models.user import User
from ycpa.repositories.auth.users import UserRepository
from ycpa.repositories.cde import (
    CdeFileRepository,
    CdeFolderRepository,
    _get_accepted_folder_share,
)
from ycpa.schemas.requests.cde import (
    CreateFolderRequest,
    MoveFileRequest,
    RenameFolderRequest,
    ShareFileRequest,
    ShareFolderRequest,
)
from ycpa.schemas.responses.cde import (
    CdeBreadcrumbItem,
    CdeFileListResponse,
    CdeFileResponse,
    CdeFileShareResponse,
    CdeFileViewResponse,
    CdeFolderContentsResponse,
    CdeFolderResponse,
    CdeFolderShareResponse,
    SharedFileItem,
    SharedFolderItem,
    SharedWithMeResponse,
)
from ycpa.services.base import BaseService
from ycpa.services.rbac import RBACService

logger = logging.getLogger(__name__)
settings = get_settings()

DEFAULT_SHARE_ROLE = "BIM Member"

ROLE_DISCIPLINE_MAP: dict[str, str | None] = {
    "Structural Engineer": "Structural",
    "MEP Engineer": "MEP",
    "Architect": "Architecture",
    "Civil Engineer": "Civil",

    "BIM Manager": None,
    "Project Manager": None,

    "Cost Consultant": None,
    "Planning Engineer": None,

    "Client Representative": None,
    "Client Viewer": None,

    "Site Engineer": None,
    "Site Supervisor": None,

    "Facility Manager": None,
    "Maintenance Engineer": None,
}


class CdeService(BaseService):

    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.repo        = CdeFileRepository(session)
        self.folder_repo = CdeFolderRepository(session)


    async def _get_role(self, role_name: str) -> Optional[Role]:
        return await self.session.scalar(
            select(Role).where(
                Role.name == role_name,
                Role.is_active.is_(True),
                Role.deleted_at.is_(None),
            )
        )



    async def _ensure_project_membership(
        self,
        owner_type: str,
        owner_id: UUID,
        user_id: UUID,
        invited_by: UUID,
        role_name: str = DEFAULT_SHARE_ROLE,   # ← FIX: was ignored before
    ) -> None:

        if owner_type == "pim_project":
            from ycpa.models.workspace import PimProject, PimProjectMember
            member_model = PimProjectMember
        elif owner_type == "aim_project":
            from ycpa.models.workspace import AimProject, AimProjectMember
            member_model = AimProjectMember
        else:
            return

        existing = await self.session.scalar(
            select(member_model).where(
                member_model.project_id == owner_id,
                member_model.user_id == user_id,
            )
        )
        if existing:
            return

        role = await self._get_role(role_name) or await self._get_role(DEFAULT_SHARE_ROLE)

        new_member = member_model(
            project_id   = owner_id,
            user_id      = user_id,
            role_id      = role.id if role else None,
            is_share_only= True,
            invited_by   = invited_by,
            created_by   = invited_by,
        )
        self.session.add(new_member)
        await self.session.flush()


    async def _is_full_project_member(
        self, owner_type: str, owner_id: UUID, user_id: UUID
    ) -> bool:
        if owner_type == "pim_project":
            from ycpa.models.workspace import PimProjectMember
            member_model = PimProjectMember
        elif owner_type == "aim_project":
            from ycpa.models.workspace import AimProjectMember
            member_model = AimProjectMember
        else:
            return False

        member = await self.session.scalar(
            select(member_model).where(
                member_model.project_id == owner_id,
                member_model.user_id == user_id,
            )
        )
        if not member:
            return False
        return not getattr(member, "is_share_only", False)


    async def _get_accessible_folder_ids(
        self, owner_type: str, owner_id: UUID, user_id: UUID
    ) -> set[UUID]:
        from ycpa.models.cde import CdeFile, CdeFileShare, CdeFolderShare

        all_visible: set[UUID] = set()

        shared_folder_rows = await self.session.scalars(
            select(CdeFolderShare).where(
                CdeFolderShare.shared_with == user_id,
                CdeFolderShare.status == "accepted",
                CdeFolderShare.deleted_at.is_(None),
            )
        )
        for row in shared_folder_rows:
            folder = await self.folder_repo.get_by_id(row.folder_id)
            if folder and folder.owner_type == owner_type and folder.owner_id == owner_id:
                all_visible.add(row.folder_id)
                ancestors = await self.folder_repo.get_ancestors(row.folder_id)
                for anc in ancestors:
                    all_visible.add(anc.id)

        shared_file_rows = await self.session.scalars(
            select(CdeFileShare).where(
                CdeFileShare.shared_with == user_id,
                CdeFileShare.status == "accepted",
                CdeFileShare.deleted_at.is_(None),
            )
        )
        for row in shared_file_rows:
            file = await self.session.scalar(
                select(CdeFile).where(
                    CdeFile.id == row.file_id,
                    CdeFile.deleted_at.is_(None),
                )
            )
            if file and file.owner_type == owner_type and file.owner_id == owner_id:
                if file.folder_id:
                    all_visible.add(file.folder_id)
                    ancestors = await self.folder_repo.get_ancestors(file.folder_id)
                    for anc in ancestors:
                        all_visible.add(anc.id)

        return all_visible

    async def _get_accessible_subfolders(
        self, owner_type: str, owner_id: UUID, parent_id: UUID | None, user_id: UUID
    ) -> list:
        from ycpa.models.cde import CdeFolder

        accessible_ids = await self._get_accessible_folder_ids(owner_type, owner_id, user_id)
        if not accessible_ids:
            return []

        query = select(CdeFolder).where(
            CdeFolder.owner_type == owner_type,
            CdeFolder.owner_id == owner_id,
            CdeFolder.deleted_at.is_(None),
            CdeFolder.id.in_(accessible_ids),
        )
        if parent_id is None:
            query = query.where(CdeFolder.parent_id.is_(None))
        else:
            query = query.where(CdeFolder.parent_id == parent_id)

        query = query.order_by(CdeFolder.name)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _get_accessible_files(
        self, owner_type: str, owner_id: UUID, folder_id: UUID | None, user_id: UUID
    ) -> list:
        from ycpa.models.cde import CdeFile, CdeFileShare
        from ycpa.repositories.cde import _get_accepted_folder_share

        has_folder_access = False
        if folder_id:
            folder_share = await _get_accepted_folder_share(self.session, folder_id, user_id)
            has_folder_access = folder_share is not None

        if has_folder_access:
            return await self.repo.get_by_owner(owner_type, owner_id, folder_id)

        shared_file_rows = await self.session.scalars(
            select(CdeFileShare).where(
                CdeFileShare.shared_with == user_id,
                CdeFileShare.status == "accepted",
                CdeFileShare.deleted_at.is_(None),
            )
        )
        result_files = []
        for row in shared_file_rows:
            file = await self.session.scalar(
                select(CdeFile).where(
                    CdeFile.id == row.file_id,
                    CdeFile.deleted_at.is_(None),
                    CdeFile.owner_type == owner_type,
                    CdeFile.owner_id == owner_id,
                )
            )
            if not file:
                continue
            if file.folder_id == folder_id:
                result_files.append(file)

        return result_files

    async def share_file(
        self,
        file_id: UUID,
        body: ShareFileRequest,
        current_user: User,
        background_tasks: BackgroundTasks,       # ← FIX
    ) -> CdeFileShareResponse:
        file = await self.repo.get_by_id(file_id)
        if not file:
            raise NotFoundException("File not found")
        if file.uploaded_by != current_user.id:
            can_edit = await self.repo.can_edit(file_id, current_user.id)
            if not can_edit:
                raise ForbiddenException("You don't have permission to share this file")

        if body.email.lower() == current_user.email.lower():
            raise ConflictException(message="You cannot share a file with yourself")

        role_name = body.role_name or DEFAULT_SHARE_ROLE

        user_repo   = UserRepository(self.session)
        target_user = await user_repo.get_by_email(body.email.lower())

        if target_user:
            existing = await self.repo.get_share(file_id, target_user.id)
            if existing:
                raise ConflictException(
                    message=f"{body.email} already has access to this file"
                )

            share = await self.repo.add_share(
                file_id     = file_id,
                shared_with = target_user.id,
                shared_by   = current_user.id,
                can_edit    = body.can_edit,
            )

            await self._ensure_project_membership(
                owner_type = file.owner_type,
                owner_id   = file.owner_id,
                user_id    = target_user.id,
                invited_by = current_user.id,
                role_name  = role_name,
            )

            await self.log_audit(
                action        = "FILE_SHARED",
                resource_type = "cde_file",
                resource_id   = str(file_id),
                user_id       = current_user.id,
                payload       = {"shared_with_email": body.email, "can_edit": body.can_edit, "role": role_name},
            )
            await self.session.commit()

            workspace_type = "pim" if file.owner_type == "pim_project" else "aim"
            cde_link = f"{settings.FRONTEND_URL}/{workspace_type}/projects/{file.owner_id}"

            html = build_share_email(
                sharer_name    = current_user.full_name or current_user.email,
                recipient_name = target_user.full_name or body.email,
                item_type      = "file",
                item_name      = file.original_filename,
                can_edit       = body.can_edit,
                cde_link       = cde_link,
                is_new_user    = False,
            )
            background_tasks.add_task(
                send_email,
                to        = body.email,
                subject   = f"{current_user.full_name or 'Someone'} shared a file with you on YCPA",
                html_body = html,
            )

            return CdeFileShareResponse(
                id                 = share.id,
                shared_with_id     = target_user.id,
                shared_with_name   = target_user.full_name,
                shared_with_email  = target_user.email,
                can_edit           = share.can_edit,
                shared_at          = share.created_at,
                is_pending         = False,
            )

        else:
            existing_pending = await self.repo.get_pending_share(file_id, body.email.lower())
            if existing_pending:
                raise ConflictException(
                    message=f"An invitation has already been sent to {body.email}"
                )

            pending = await self.repo.add_pending_share(
                file_id  = file_id,
                email    = body.email.lower(),
                shared_by= current_user.id,
                can_edit = body.can_edit,
            )

            await self.log_audit(
                action        = "FILE_SHARED_PENDING",
                resource_type = "cde_file",
                resource_id   = str(file_id),
                user_id       = current_user.id,
                payload       = {"shared_with_email": body.email, "can_edit": body.can_edit, "pending": True},
            )
            await self.session.commit()

            signup_link = f"{settings.FRONTEND_URL}/sign-up?email={body.email}"
            html = build_share_email(
                sharer_name    = current_user.full_name or current_user.email,
                recipient_name = body.email,
                item_type      = "file",
                item_name      = file.original_filename,
                can_edit       = body.can_edit,
                cde_link       = signup_link,
                is_new_user    = True,
            )
            background_tasks.add_task(
                send_email,
                to        = body.email,
                subject   = f"{current_user.full_name or 'Someone'} shared a file with you on YCPA",
                html_body = html,
            )

            return CdeFileShareResponse(
                id                = None,
                shared_with_id    = None,
                shared_with_name  = None,
                shared_with_email = pending.email,
                can_edit          = pending.can_edit,
                shared_at         = pending.shared_at,
                is_pending        = True,
            )


    async def share_folder(
        self,
        folder_id: UUID,
        body: ShareFolderRequest,
        current_user: User,
        background_tasks: BackgroundTasks,
    ) -> CdeFolderShareResponse:
        folder = await self.folder_repo.get_by_id(folder_id)
        if not folder:
            raise NotFoundException("Folder not found")
        await self._assert_folder_access(folder, current_user, require_edit=True)

        if body.email.lower() == current_user.email.lower():
            raise ConflictException(message="You cannot share a folder with yourself")

        role_name = body.role_name or DEFAULT_SHARE_ROLE

        all_files = await self.repo.get_all_in_folder_recursive(
            folder.owner_type, folder.owner_id, folder_id
        )

        user_repo   = UserRepository(self.session)
        target_user = await user_repo.get_by_email(body.email.lower())

        if target_user:
            existing = await self.folder_repo.get_folder_share(folder_id, target_user.id)
            if existing:
                raise ConflictException(
                    message=f"{body.email} already has access to this folder"
                )

            folder_share = await self.folder_repo.add_folder_share(
                folder_id   = folder_id,
                shared_with = target_user.id,
                shared_by   = current_user.id,
                can_edit    = body.can_edit,
            )

            for f in all_files:
                existing_file_share = await self.repo.get_share(f.id, target_user.id)
                if not existing_file_share:
                    await self.repo.add_share(
                        file_id     = f.id,
                        shared_with = target_user.id,
                        shared_by   = current_user.id,
                        can_edit    = body.can_edit,
                    )

            await self._ensure_project_membership(
                owner_type = folder.owner_type,
                owner_id   = folder.owner_id,
                user_id    = target_user.id,
                invited_by = current_user.id,
                role_name  = role_name,
            )

            await self.log_audit(
                action        = "FOLDER_SHARED",
                resource_type = "cde_folder",
                resource_id   = str(folder_id),
                user_id       = current_user.id,
                payload       = {"shared_with_email": body.email, "can_edit": body.can_edit, "file_count": len(all_files), "role": role_name},
            )
            await self.session.commit()

            workspace_type = "pim" if folder.owner_type == "pim_project" else "aim"
            cde_link = f"{settings.FRONTEND_URL}/{workspace_type}/projects/{folder.owner_id}"

            html = build_share_email(
                sharer_name    = current_user.full_name or current_user.email,
                recipient_name = target_user.full_name or body.email,
                item_type      = "folder",
                item_name      = folder.name,
                can_edit       = body.can_edit,
                cde_link       = cde_link,
                is_new_user    = False,
            )
            background_tasks.add_task(
                send_email,
                to        = body.email,
                subject   = f"{current_user.full_name or 'Someone'} shared a folder with you on YCPA",
                html_body = html,
            )

            return CdeFolderShareResponse(
                id                = folder_share.id,
                shared_with_id    = target_user.id,
                shared_with_name  = target_user.full_name,
                shared_with_email = target_user.email,
                can_edit          = folder_share.can_edit,
                shared_at         = folder_share.created_at,
                is_pending        = False,
                file_count        = len(all_files),
            )

        else:
            existing_pending = await self.folder_repo.get_pending_folder_share(
                folder_id, body.email.lower()
            )
            if existing_pending:
                raise ConflictException(
                    message=f"An invitation has already been sent to {body.email}"
                )

            pending = await self.folder_repo.add_pending_folder_share(
                folder_id = folder_id,
                email     = body.email.lower(),
                shared_by = current_user.id,
                can_edit  = body.can_edit,
            )

            await self.log_audit(
                action        = "FOLDER_SHARED_PENDING",
                resource_type = "cde_folder",
                resource_id   = str(folder_id),
                user_id       = current_user.id,
                payload       = {"shared_with_email": body.email, "can_edit": body.can_edit, "file_count": len(all_files), "pending": True},
            )
            await self.session.commit()

            signup_link = f"{settings.FRONTEND_URL}/sign-up?email={body.email}"
            html = build_share_email(
                sharer_name    = current_user.full_name or current_user.email,
                recipient_name = body.email,
                item_type      = "folder",
                item_name      = folder.name,
                can_edit       = body.can_edit,
                cde_link       = signup_link,
                is_new_user    = True,
            )
            background_tasks.add_task(
                send_email,
                to        = body.email,
                subject   = f"{current_user.full_name or 'Someone'} shared a folder with you on YCPA",
                html_body = html,
            )

            return CdeFolderShareResponse(
                id                = None,
                shared_with_id    = None,
                shared_with_name  = None,
                shared_with_email = pending.email,
                can_edit          = pending.can_edit,
                shared_at         = pending.shared_at,
                is_pending        = True,
                file_count        = len(all_files),
            )


    async def get_shares(self, file_id: UUID, current_user: User) -> list[CdeFileShareResponse]:
        file = await self.repo.get_by_id(file_id)
        if not file:
            raise NotFoundException("File not found")
        can_view = await self.repo.can_view(file_id, current_user.id)
        if not can_view:
            raise ForbiddenException("You don't have access to this file")

        result: list[CdeFileShareResponse] = []
        for share, user in await self.repo.get_shares_with_users(file_id):
            result.append(CdeFileShareResponse(
                id=share.id, shared_with_id=user.id, shared_with_name=user.full_name,
                shared_with_email=user.email, can_edit=share.can_edit,
                shared_at=share.shared_at, is_pending=False,
            ))
        for pending in await self.repo.get_pending_shares_with_email(file_id):
            result.append(CdeFileShareResponse(
                id=None, shared_with_id=None, shared_with_name=None,
                shared_with_email=pending.email, can_edit=pending.can_edit,
                shared_at=pending.shared_at, is_pending=True,
            ))
        return result


    async def get_folder_shares(self, folder_id: UUID, current_user: User) -> list[CdeFolderShareResponse]:
        folder = await self.folder_repo.get_by_id(folder_id)
        if not folder:
            raise NotFoundException("Folder not found")
        await self._assert_folder_access(folder, current_user, require_edit=False)

        result: list[CdeFolderShareResponse] = []
        for share, user in await self.folder_repo.get_folder_shares_with_users(folder_id):
            result.append(CdeFolderShareResponse(
                id=share.id, shared_with_id=user.id, shared_with_name=user.full_name,
                shared_with_email=user.email, can_edit=share.can_edit,
                shared_at=share.created_at, is_pending=False,
            ))
        for pending in await self.folder_repo.get_pending_folder_shares(folder_id):
            result.append(CdeFolderShareResponse(
                id=None, shared_with_id=None, shared_with_name=None,
                shared_with_email=pending.email, can_edit=pending.can_edit,
                shared_at=pending.shared_at, is_pending=True,
            ))
        return result


    async def attach_pending_shares_for_user(self, email: str, user_id: UUID) -> int:
        total = 0

        from ycpa.models.cde import CdePendingFileShare
        file_pending_result = await self.session.execute(
            select(CdePendingFileShare).where(
                CdePendingFileShare.email == email.lower(),
                CdePendingFileShare.attached_at.is_(None),
            )
        )
        for ps in file_pending_result.scalars().all():
            existing = await self.repo.get_share(ps.file_id, user_id)
            if not existing:
                await self.repo.add_share(
                    file_id=ps.file_id, shared_with=user_id,
                    shared_by=ps.shared_by, can_edit=ps.can_edit,
                )
            file = await self.repo.get_by_id(ps.file_id)
            if file:
                await self._ensure_project_membership(
                    owner_type=file.owner_type, owner_id=file.owner_id,
                    user_id=user_id, invited_by=ps.shared_by,
                    role_name=DEFAULT_SHARE_ROLE,
                )
            ps.attached_at = datetime.now(timezone.utc)
            ps.attached_to = user_id
            total += 1

        from ycpa.models.cde import CdePendingFolderShare
        folder_pending_result = await self.session.execute(
            select(CdePendingFolderShare).where(
                CdePendingFolderShare.email == email.lower(),
                CdePendingFolderShare.attached_at.is_(None),
            )
        )
        for pf in folder_pending_result.scalars().all():
            existing_fs = await self.folder_repo.get_folder_share(pf.folder_id, user_id)
            if not existing_fs:
                await self.folder_repo.add_folder_share(
                    folder_id=pf.folder_id, shared_with=user_id,
                    shared_by=pf.shared_by, can_edit=pf.can_edit,
                )
            folder = await self.folder_repo.get_by_id(pf.folder_id)
            if folder:
                all_files = await self.repo.get_all_in_folder_recursive(
                    folder.owner_type, folder.owner_id, pf.folder_id
                )
                for f in all_files:
                    existing_file_share = await self.repo.get_share(f.id, user_id)
                    if not existing_file_share:
                        await self.repo.add_share(
                            file_id=f.id, shared_with=user_id,
                            shared_by=pf.shared_by, can_edit=pf.can_edit,
                        )
                await self._ensure_project_membership(
                    owner_type=folder.owner_type, owner_id=folder.owner_id,
                    user_id=user_id, invited_by=pf.shared_by,
                    role_name=DEFAULT_SHARE_ROLE,
                )
            pf.attached_at = datetime.now(timezone.utc)
            pf.attached_to = user_id
            total += 1

        if total:
            await self.session.flush()
        return total


    async def get_shared_with_me(self, current_user: User) -> dict:
        from ycpa.models.cde import CdeFile, CdeFileShare, CdeFolder, CdeFolderShare

        file_share_rows = await self.session.scalars(
            select(CdeFileShare).where(
                CdeFileShare.shared_with == current_user.id,
                CdeFileShare.status == "accepted",
                CdeFileShare.deleted_at.is_(None),
            )
        )
        shared_files = []
        for fs in file_share_rows:
            f = await self.session.scalar(
                select(CdeFile).where(CdeFile.id == fs.file_id, CdeFile.deleted_at.is_(None))
            )
            if not f:
                continue
            project_name, workspace_name = await self._resolve_owner_names(f.owner_type, f.owner_id)
            shared_files.append({
                "type": "file", "id": str(f.id), "name": f.original_filename,
                "file_extension": f.file_extension, "owner_type": f.owner_type,
                "owner_id": str(f.owner_id), "folder_id": str(f.folder_id) if f.folder_id else None,
                "can_edit": fs.can_edit, "shared_at": fs.shared_at.isoformat(),
                "project_name": project_name, "workspace_name": workspace_name,
            })

        folder_share_rows = await self.session.scalars(
            select(CdeFolderShare).where(
                CdeFolderShare.shared_with == current_user.id,
                CdeFolderShare.status == "accepted",
                CdeFolderShare.deleted_at.is_(None),
            )
        )
        shared_folders = []
        for fs in folder_share_rows:
            folder = await self.session.scalar(
                select(CdeFolder).where(CdeFolder.id == fs.folder_id, CdeFolder.deleted_at.is_(None))
            )
            if not folder:
                continue
            project_name, workspace_name = await self._resolve_owner_names(folder.owner_type, folder.owner_id)
            shared_folders.append({
                "type": "folder", "id": str(folder.id), "name": folder.name,
                "owner_type": folder.owner_type, "owner_id": str(folder.owner_id),
                "parent_id": str(folder.parent_id) if folder.parent_id else None,
                "can_edit": fs.can_edit, "shared_at": fs.shared_at.isoformat(),
                "project_name": project_name, "workspace_name": workspace_name,
            })

        return {
            "files": shared_files,
            "folders": shared_folders,
            "total": len(shared_files) + len(shared_folders),
        }

    async def _resolve_owner_names(
        self, owner_type: str, owner_id: UUID
    ) -> tuple[str | None, str | None]:
        if owner_type == "pim_project":
            from ycpa.models.workspace import PimProject, PimWorkspace
            project = await self.session.scalar(select(PimProject).where(PimProject.id == owner_id))
            if not project:
                return None, None
            workspace = await self.session.scalar(select(PimWorkspace).where(PimWorkspace.id == project.workspace_id))
            return project.name, (workspace.name if workspace else None)
        elif owner_type == "aim_project":
            from ycpa.models.workspace import AimProject, AimWorkspace
            project = await self.session.scalar(select(AimProject).where(AimProject.id == owner_id))
            if not project:
                return None, None
            workspace = await self.session.scalar(select(AimWorkspace).where(AimWorkspace.id == project.workspace_id))
            return project.name, (workspace.name if workspace else None)
        return None, None


    async def list_files(self, current_user: User) -> CdeFileListResponse:
        files     = await self.repo.get_all_visible(current_user.id)
        user_repo = UserRepository(self.session)
        items: list[CdeFileResponse] = []
        for f in files:
            uploader    = await user_repo.get_by_id(f.uploaded_by)
            frag        = await self.repo.get_frag_child(f.id)
            share_count = await self.repo.count_shares(f.id)
            can_edit    = await self.repo.can_edit(f.id, current_user.id)
            items.append(CdeFileResponse(
                id=f.id, filename=f.original_filename, file_extension=f.file_extension,
                mime_type=f.mime_type, status=f.status, s3_key=f.s3_key,
                frag_s3_key=frag.s3_key if frag else None, file_size_bytes=f.file_size_bytes,
                owner_type=f.owner_type, owner_id=f.owner_id, folder_id=f.folder_id,
                uploaded_by=f.uploaded_by, uploaded_by_name=uploader.full_name if uploader else None,
                discipline=f.discipline, description=f.description, is_demo=f.is_demo,
                version=f.version, created_at=f.created_at, updated_at=f.updated_at,
                can_edit=can_edit, share_count=share_count,
            ))
        return CdeFileListResponse(files=items, total=len(items))


    async def get_folder_contents(
            self,
            owner_type: str,
            owner_id: UUID,
            folder_id: UUID | None,
            current_user: User,
    ) -> CdeFolderContentsResponse:

        is_full_member = await self._is_full_project_member(
            owner_type, owner_id, current_user.id
        )

        if is_full_member:
            discipline_id = await self._get_user_discipline_id(
                owner_type, owner_id, current_user.id
            )
            sub_folders = await self.folder_repo.get_children_discipline_filtered(
                owner_type=owner_type,
                owner_id=owner_id,
                parent_id=folder_id,
                discipline_id=discipline_id,
            )
            raw_files = await self.repo.get_by_owner_discipline_filtered(
                owner_type=owner_type,
                owner_id=owner_id,
                folder_id=folder_id,
                discipline_id=discipline_id,
                user_id=current_user.id,
            )

        else:
            sub_folders = await self._get_accessible_subfolders(
                owner_type, owner_id, folder_id, current_user.id
            )
            raw_files = await self._get_accessible_files(
                owner_type, owner_id, folder_id, current_user.id
            )

        user_repo = UserRepository(self.session)
        file_items: list[CdeFileResponse] = []
        for f in raw_files:
            uploader = await user_repo.get_by_id(f.uploaded_by)
            frag = await self.repo.get_frag_child(f.id)
            share_count = await self.repo.count_shares(f.id)
            can_edit = await self.repo.can_edit(f.id, current_user.id)
            file_items.append(CdeFileResponse(
                id=f.id, filename=f.original_filename, file_extension=f.file_extension,
                mime_type=f.mime_type, status=f.status, s3_key=f.s3_key,
                frag_s3_key=frag.s3_key if frag else None,
                file_size_bytes=f.file_size_bytes,
                owner_type=f.owner_type, owner_id=f.owner_id, folder_id=f.folder_id,
                uploaded_by=f.uploaded_by,
                uploaded_by_name=uploader.full_name if uploader else None,
                discipline=f.discipline, description=f.description,
                is_demo=f.is_demo, version=f.version,
                created_at=f.created_at, updated_at=f.updated_at,
                can_edit=can_edit, share_count=share_count,
            ))

        breadcrumb: list[CdeBreadcrumbItem] = [CdeBreadcrumbItem(id=None, name="Root")]
        current_folder_obj = None
        if folder_id:
            ancestors = await self.folder_repo.get_ancestors(folder_id)
            for anc in ancestors:
                breadcrumb.append(CdeBreadcrumbItem(id=anc.id, name=anc.name))
            current_folder_obj = await self.folder_repo.get_by_id(folder_id)
            if current_folder_obj:
                breadcrumb.append(
                    CdeBreadcrumbItem(id=current_folder_obj.id, name=current_folder_obj.name)
                )

        folder_responses = [
            CdeFolderResponse(
                id=f.id, name=f.name, owner_type=f.owner_type, owner_id=f.owner_id,
                parent_id=f.parent_id, created_at=f.created_at,
                updated_at=f.updated_at, created_by=f.created_by,
            )
            for f in sub_folders
        ]
        current_folder_response = None
        if current_folder_obj:
            current_folder_response = CdeFolderResponse(
                id=current_folder_obj.id, name=current_folder_obj.name,
                owner_type=current_folder_obj.owner_type,
                owner_id=current_folder_obj.owner_id,
                parent_id=current_folder_obj.parent_id,
                created_at=current_folder_obj.created_at,
                updated_at=current_folder_obj.updated_at,
                created_by=current_folder_obj.created_by,
            )

        return CdeFolderContentsResponse(
            current_folder=current_folder_response,
            breadcrumb=breadcrumb,
            folders=folder_responses,
            files=file_items,
            total_folders=len(folder_responses),
            total_files=len(file_items),
        )


    async def _assert_owner_write_access(
        self, owner_type: str, owner_id: UUID, user: User
    ) -> None:
        """Caller must be allowed to add/modify CDE content under this owner."""
        if user.platform_role == "super_admin":
            return
        if owner_type == "user":
            if owner_id == user.id:
                return
            raise ForbiddenException("You don't have access to these files.")
        ws_type = "pim" if owner_type == "pim_project" else "aim"
        allowed = await RBACService.get_project_permission(
            db=self.session, user_id=user.id, project_id=owner_id,
            workspace_type=ws_type, module="cde", action="can_edit",
        )
        if not allowed:
            raise ForbiddenException(
                "You don't have permission to modify this project's files."
            )

    async def _assert_folder_access(
        self, folder, user: User, *, require_edit: bool
    ) -> None:
        """Caller must be able to view (or edit) this specific folder."""
        if user.platform_role == "super_admin":
            return
        if folder.owner_type == "user":
            if folder.owner_id == user.id:
                return
            raise ForbiddenException("You don't have access to this folder.")
        ws_type = "pim" if folder.owner_type == "pim_project" else "aim"
        action  = "can_edit" if require_edit else "can_view"
        allowed = await RBACService.get_project_permission(
            db=self.session, user_id=user.id, project_id=folder.owner_id,
            workspace_type=ws_type, module="cde", action=action,
        )
        if allowed:
            return
        share = await _get_accepted_folder_share(self.session, folder.id, user.id)
        if share and (not require_edit or share.can_edit):
            return
        raise ForbiddenException("You don't have access to this folder.")

    async def create_folder(
            self, body: CreateFolderRequest, owner_type: str, owner_id: UUID, current_user: User
    ) -> CdeFolderResponse:
        from ycpa.models.cde import CdeFolder

        await self._assert_owner_write_access(owner_type, owner_id, current_user)

        exists = await self.folder_repo.name_exists_in_parent(
            owner_type, owner_id, body.name, body.parent_id
        )
        if exists:
            raise ConflictException(
                message=f"A folder named '{body.name}' already exists at this level"
            )

        folder = CdeFolder(
            name=body.name,
            owner_type=owner_type,
            owner_id=owner_id,
            parent_id=body.parent_id,
            discipline_id=body.discipline_id,  # ← NEW
            created_by=current_user.id,
        )
        self.session.add(folder)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(folder)

        return CdeFolderResponse(
            id=folder.id,
            name=folder.name,
            owner_type=folder.owner_type,
            owner_id=folder.owner_id,
            parent_id=folder.parent_id,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
            created_by=folder.created_by,
        )


    async def rename_folder(
        self, folder_id: UUID, body: RenameFolderRequest, current_user: User
    ) -> CdeFolderResponse:
        folder = await self.folder_repo.get_by_id(folder_id)
        if not folder:
            raise NotFoundException("Folder not found")
        await self._assert_folder_access(folder, current_user, require_edit=True)
        exists = await self.folder_repo.name_exists_in_parent(
            folder.owner_type, folder.owner_id, body.name, folder.parent_id, exclude_id=folder_id
        )
        if exists:
            raise ConflictException(message=f"A folder named '{body.name}' already exists at this level")

        updated = await self.folder_repo.rename(folder_id, body.name, current_user.id)
        await self.session.commit()
        return CdeFolderResponse(
            id=updated.id, name=updated.name, owner_type=updated.owner_type,
            owner_id=updated.owner_id, parent_id=updated.parent_id,
            created_at=updated.created_at, updated_at=updated.updated_at, created_by=updated.created_by,
        )


    async def delete_folder(self, folder_id: UUID, current_user: User) -> None:
        folder = await self.folder_repo.get_by_id(folder_id)
        if not folder:
            raise NotFoundException("Folder not found")
        await self._assert_folder_access(folder, current_user, require_edit=True)
        if await self.folder_repo.count_children(folder_id):
            raise ConflictException(message="Cannot delete a folder that contains sub-folders.")
        files_in_folder = await self.repo.get_by_owner(folder.owner_type, folder.owner_id, folder_id)
        if files_in_folder:
            raise ConflictException(message="Cannot delete a folder that contains files.")
        await self.folder_repo.soft_delete(folder_id, current_user.id)
        await self.session.commit()


    async def move_file(self, file_id: UUID, body: MoveFileRequest, current_user: User) -> CdeFileResponse:
        file = await self.repo.get_by_id(file_id)
        if not file:
            raise NotFoundException("File not found")
        if file.uploaded_by != current_user.id:
            raise ForbiddenException("Only the file owner can move it")

        await self.repo.move_to_folder(file_id, body.folder_id, current_user.id)
        await self.session.commit()

        updated     = await self.repo.get_by_id(file_id)
        user_repo   = UserRepository(self.session)
        uploader    = await user_repo.get_by_id(updated.uploaded_by)
        frag        = await self.repo.get_frag_child(file_id)
        share_count = await self.repo.count_shares(file_id)

        return CdeFileResponse(
            id=updated.id, filename=updated.original_filename, file_extension=updated.file_extension,
            mime_type=updated.mime_type, status=updated.status, s3_key=updated.s3_key,
            frag_s3_key=frag.s3_key if frag else None, file_size_bytes=updated.file_size_bytes,
            owner_type=updated.owner_type, owner_id=updated.owner_id, folder_id=updated.folder_id,
            uploaded_by=updated.uploaded_by, uploaded_by_name=uploader.full_name if uploader else None,
            discipline=updated.discipline, description=updated.description, is_demo=updated.is_demo,
            version=updated.version, created_at=updated.created_at, updated_at=updated.updated_at,
            can_edit=True, share_count=share_count,
        )


    async def get_view_urls(self, file_id: UUID, current_user: User) -> CdeFileViewResponse:
        from ycpa.core.storage.s3 import generate_presigned_url

        file = await self.repo.get_by_id(file_id)
        if not file:
            raise NotFoundException("File not found")
        can_view = await self.repo.can_view(file_id, current_user.id)
        if not can_view:
            raise ForbiddenException("You don't have access to this file")

        resolved_key = "samples/sample_building.ifc" if file.is_demo else file.s3_key
        ifc_url  = generate_presigned_url(resolved_key) if file.file_extension == "ifc" else None
        frag_url = None
        frag = await self.repo.get_frag_child(file_id)
        if frag:
            frag_key = "samples/sample_building.frag" if file.is_demo else frag.s3_key
            frag_url = generate_presigned_url(frag_key)

        return CdeFileViewResponse(
            file_id=file.id, filename=file.original_filename,
            file_extension=file.file_extension, frag_url=frag_url, ifc_url=ifc_url,
        )


    async def _change_status(self, file_id: UUID, new_status: str, current_user: User) -> CdeFileResponse:
        file = await self.repo.get_by_id(file_id)
        if not file:
            raise NotFoundException("File not found")
        if file.uploaded_by != current_user.id:
            raise ForbiddenException("Only the file owner can change its status")

        await self.repo.update_by_id(file_id, {"status": new_status})
        await self.session.commit()

        updated     = await self.repo.get_by_id(file_id)
        user_repo   = UserRepository(self.session)
        uploader    = await user_repo.get_by_id(updated.uploaded_by)
        frag        = await self.repo.get_frag_child(file_id)
        share_count = await self.repo.count_shares(file_id)

        return CdeFileResponse(
            id=updated.id, filename=updated.original_filename, file_extension=updated.file_extension,
            mime_type=updated.mime_type, status=updated.status, s3_key=updated.s3_key,
            frag_s3_key=frag.s3_key if frag else None, file_size_bytes=updated.file_size_bytes,
            owner_type=updated.owner_type, owner_id=updated.owner_id, folder_id=updated.folder_id,
            uploaded_by=updated.uploaded_by, uploaded_by_name=uploader.full_name if uploader else None,
            discipline=updated.discipline, description=updated.description, is_demo=updated.is_demo,
            version=updated.version, created_at=updated.created_at, updated_at=updated.updated_at,
            can_edit=True, share_count=share_count,
        )

    async def publish_file(self, file_id: UUID, current_user: User) -> CdeFileResponse:
        return await self._change_status(file_id, "published", current_user)

    async def archive_file(self, file_id: UUID, current_user: User) -> CdeFileResponse:
        return await self._change_status(file_id, "archived", current_user)


    async def seed_sample_file(self, user: User) -> None:
        already = await self.repo.has_demo_file(user.id)
        if already:
            return
        from ycpa.models.cde import CdeFile as CdeFileModel
        demo = CdeFileModel(
            owner_type="user", owner_id=user.id, uploaded_by=user.id,
            filename="Sample Building.ifc", original_filename="Sample Building.ifc",
            s3_key=f"samples/{user.id}/sample_building.ifc",
            file_size_bytes=0, mime_type="application/x-step", file_extension="ifc",
            status="published", discipline="Architecture",
            description="Sample BIM model — explore the CDE viewer",
            is_demo=True, version=1, created_by=user.id,
        )
        self.session.add(demo)
        await self.session.flush()

    async def get_shared_with_me(self, current_user: User) -> SharedWithMeResponse:
        from ycpa.models.cde import CdeFileShare, CdeFolderShare, CdeFile, CdeFolder

        # ── Shared files ──────────────────────────────────────────────────────
        file_share_rows = await self.session.scalars(
            select(CdeFileShare).where(
                CdeFileShare.shared_with == current_user.id,
                CdeFileShare.status == "accepted",
                CdeFileShare.deleted_at.is_(None),
            )
        )

        shared_files: list[SharedFileItem] = []
        for fs in file_share_rows:
            f = await self.session.scalar(
                select(CdeFile).where(
                    CdeFile.id == fs.file_id,
                    CdeFile.deleted_at.is_(None),
                )
            )
            if not f:
                continue

            folder_name: str | None = None
            if f.folder_id:
                folder_obj = await self.folder_repo.get_by_id(f.folder_id)
                if folder_obj:
                    folder_name = folder_obj.name

            project_name, workspace_name = await self._resolve_owner_names(
                f.owner_type, f.owner_id
            )

            shared_files.append(SharedFileItem(
                id=f.id,
                name=f.original_filename,
                file_extension=f.file_extension,
                status=f.status,
                file_size_bytes=f.file_size_bytes,
                owner_type=f.owner_type,
                owner_id=f.owner_id,
                folder_id=f.folder_id,
                folder_name=folder_name,
                can_edit=fs.can_edit,
                shared_at=fs.shared_at,
                workspace_name=workspace_name,
                project_name=project_name,
            ))

        # ── Shared folders ────────────────────────────────────────────────────
        folder_share_rows = await self.session.scalars(
            select(CdeFolderShare).where(
                CdeFolderShare.shared_with == current_user.id,
                CdeFolderShare.status == "accepted",
                CdeFolderShare.deleted_at.is_(None),
            )
        )

        shared_folders: list[SharedFolderItem] = []
        for fs in folder_share_rows:
            folder = await self.session.scalar(
                select(CdeFolder).where(
                    CdeFolder.id == fs.folder_id,
                    CdeFolder.deleted_at.is_(None),
                )
            )
            if not folder:
                continue

            parent_folder_name: str | None = None
            if folder.parent_id:
                parent = await self.folder_repo.get_by_id(folder.parent_id)
                if parent:
                    parent_folder_name = parent.name

            all_files = await self.repo.get_all_in_folder_recursive(
                folder.owner_type, folder.owner_id, folder.id
            )

            project_name, workspace_name = await self._resolve_owner_names(
                folder.owner_type, folder.owner_id
            )

            shared_folders.append(SharedFolderItem(
                id=folder.id,
                name=folder.name,
                owner_type=folder.owner_type,
                owner_id=folder.owner_id,
                parent_id=folder.parent_id,
                parent_folder_name=parent_folder_name,
                can_edit=fs.can_edit,
                shared_at=fs.shared_at,
                file_count=len(all_files),
                workspace_name=workspace_name,
                project_name=project_name,
            ))

        return SharedWithMeResponse(
            files=shared_files,
            folders=shared_folders,
            total=len(shared_files) + len(shared_folders),
        )

    async def _get_user_discipline_id(
            self,
            owner_type: str,
            owner_id: UUID,
            user_id: UUID,
    ) -> UUID | None | bool:

        if owner_type == "pim_project":
            from ycpa.models.workspace import PimProjectMember
            member_model = PimProjectMember
        elif owner_type == "aim_project":
            from ycpa.models.workspace import AimProjectMember
            member_model = AimProjectMember
        else:
            return None

        member = await self.session.scalar(
            select(member_model).where(
                member_model.project_id == owner_id,
                member_model.user_id == user_id,
            )
        )
        if not member or not member.role_id:
            return None

        role = await self.session.scalar(
            select(Role).where(Role.id == member.role_id)
        )
        if not role:
            return None

        discipline_name = ROLE_DISCIPLINE_MAP.get(role.name)
        if discipline_name is None:
            return None

        from ycpa.models.workspace import PimScopeDiscipline
        discipline = await self.session.scalar(
            select(PimScopeDiscipline).where(
                PimScopeDiscipline.project_id == owner_id,
                PimScopeDiscipline.name == discipline_name,
                PimScopeDiscipline.deleted_at.is_(None),
            )
        )
        if not discipline:
            return None

        return discipline.id

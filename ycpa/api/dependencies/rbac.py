
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.auth.dependencies import get_current_user
from ycpa.core.database.session import get_async_session
from ycpa.models.user import User
from ycpa.services.rbac import RBACService, WorkspaceRole, WorkspaceType


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _get_path_uuid(request: Request, param: str) -> uuid.UUID:
    raw = request.path_params.get(param)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing path parameter: {param}",
        )
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID for path parameter: {param}",
        )


async def _get_accepted_folder_share_for_user(
    db: AsyncSession,
    folder_id: uuid.UUID,
    user_id: uuid.UUID,
):

    from ycpa.models.cde import CdeFolder, CdeFolderShare

    current_id = folder_id
    visited: set[uuid.UUID] = set()

    for _ in range(20):
        if current_id is None or current_id in visited:
            break
        visited.add(current_id)

        share = await db.scalar(
            select(CdeFolderShare).where(
                CdeFolderShare.folder_id == current_id,
                CdeFolderShare.shared_with == user_id,
                CdeFolderShare.status == "accepted",
                CdeFolderShare.deleted_at.is_(None),
            )
        )
        if share:
            return share

        folder = await db.scalar(
            select(CdeFolder).where(
                CdeFolder.id == current_id,
                CdeFolder.deleted_at.is_(None),
            )
        )
        if not folder or folder.parent_id is None:
            break
        current_id = folder.parent_id

    return None



def PlatformGuard(*allowed_roles: str):

    async def _guard(
        current_user: User = Depends(get_current_user),
    ) -> None:
        if not current_user.is_active:
            raise _forbidden("Your account is inactive.")
        if current_user.platform_role not in allowed_roles:
            raise _forbidden(
                f"This action requires one of these roles: {', '.join(allowed_roles)}. "
                f"Your role: {current_user.platform_role}."
            )
    return _guard



def WorkspaceGuard(workspace_type: WorkspaceType, min_role: WorkspaceRole):

    async def _guard(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_async_session),
    ) -> None:
        if not current_user.is_active:
            raise _forbidden("Your account is inactive.")

        if current_user.platform_role == "super_admin":
            return

        workspace_id = _get_path_uuid(request, "workspace_id")

        exists = await RBACService.workspace_exists(db, workspace_id, workspace_type)
        if not exists:
            raise _not_found(f"{workspace_type.upper()} workspace not found.")

        actual_role = await RBACService.get_workspace_role(
            db, current_user.id, workspace_id, workspace_type
        )

        if not RBACService.workspace_role_meets(actual_role, min_role):
            if actual_role is None:
                raise _forbidden("You are not a member of this workspace.")
            raise _forbidden(
                f"This action requires '{min_role}' role or above. "
                f"Your role: '{actual_role}'."
            )
    return _guard



def ProjectGuard(workspace_type: WorkspaceType, module: str, action: str):

    async def _guard(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_async_session),
    ) -> None:
        if not current_user.is_active:
            raise _forbidden("Your account is inactive.")

        if current_user.platform_role == "super_admin":
            return

        project_id = _get_path_uuid(request, "project_id")

        exists = await RBACService.project_exists(db, project_id, workspace_type)
        if not exists:
            raise _not_found(f"{workspace_type.upper()} project not found.")

        # Workspace owners/admins bypass project-level permission checks
        ws_role = await RBACService.get_workspace_role_for_project(
            db, current_user.id, project_id, workspace_type
        )
        if ws_role in ("owner", "admin"):
            return

        allowed = await RBACService.get_project_permission(
            db=db,
            user_id=current_user.id,
            project_id=project_id,
            workspace_type=workspace_type,
            module=module,
            action=action,
        )

        if not allowed:
            raise _forbidden(
                f"You don't have '{action}' permission on '{module}' in this project."
            )
    return _guard



def FileShareGuard(workspace_type: WorkspaceType, require_edit: bool = False):

    from ycpa.models.cde import CdeFile, CdeFileShare

    async def _guard(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_async_session),
    ) -> None:
        if not current_user.is_active:
            raise _forbidden("Your account is inactive.")

        if current_user.platform_role == "super_admin":
            return

        file_id = _get_path_uuid(request, "file_id")

        cde_file = await db.scalar(
            select(CdeFile).where(
                CdeFile.id == file_id,
                CdeFile.deleted_at.is_(None),
            )
        )
        if not cde_file:
            raise _not_found("File not found.")

        if cde_file.uploaded_by == current_user.id:
            return

        if cde_file.status == "published" and not require_edit:
            return

        file_share = await db.scalar(
            select(CdeFileShare).where(
                CdeFileShare.file_id == file_id,
                CdeFileShare.shared_with == current_user.id,
                CdeFileShare.status == "accepted",
                CdeFileShare.deleted_at.is_(None),
            )
        )
        if file_share:
            if require_edit and not file_share.can_edit:
                raise _forbidden("You have view-only access to this file.")
            return


        if cde_file.folder_id:
            folder_share = await _get_accepted_folder_share_for_user(
                db, cde_file.folder_id, current_user.id
            )
            if folder_share:
                if require_edit and not folder_share.can_edit:
                    raise _forbidden("You have view-only access to this file via folder share.")
                return

        raise _forbidden("You don't have access to this file.")

    return _guard



def FolderShareGuard(workspace_type: WorkspaceType, require_edit: bool = False):

    from ycpa.models.cde import CdeFolder, CdeFolderShare

    async def _guard(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_async_session),
    ) -> None:
        if not current_user.is_active:
            raise _forbidden("Your account is inactive.")

        if current_user.platform_role == "super_admin":
            return

        folder_id = _get_path_uuid(request, "folder_id")

        folder = await db.scalar(
            select(CdeFolder).where(
                CdeFolder.id == folder_id,
                CdeFolder.deleted_at.is_(None),
            )
        )
        if not folder:
            raise _not_found("Folder not found.")

        project_allowed = await RBACService.get_project_permission(
            db=db,
            user_id=current_user.id,
            project_id=folder.owner_id,
            workspace_type=workspace_type,
            module="cde",
            action="can_view",
        )
        if project_allowed:
            if require_edit:
                edit_allowed = await RBACService.get_project_permission(
                    db=db,
                    user_id=current_user.id,
                    project_id=folder.owner_id,
                    workspace_type=workspace_type,
                    module="cde",
                    action="can_edit",
                )
                if not edit_allowed:
                    raise _forbidden("You have view-only access to this folder.")
            return

        folder_share = await _get_accepted_folder_share_for_user(
            db, folder_id, current_user.id
        )
        if folder_share:
            if require_edit and not folder_share.can_edit:
                raise _forbidden("You have view-only access to this folder.")
            return

        raise _forbidden("You don't have access to this folder.")

    return _guard
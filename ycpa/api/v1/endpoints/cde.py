import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.auth.dependencies import CurrentUser, get_current_user
from ycpa.core.database import DatabaseSession
from ycpa.core.database.session import get_async_session
from ycpa.core.storage.s3 import get_object_bytes
from ycpa.repositories.cde import CdeFileRepository
from ycpa.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.models.user import User
from ycpa.schemas.requests.cde import (
    CreateDisciplineRequest,
    CreateFolderRequest,
    MoveFileRequest,
    RenameFolderRequest,
    ShareFileRequest,
    ShareFolderRequest,
    UpdateDisciplineRequest,
)
from ycpa.schemas.responses.cde import (
    CdeFileListResponse,
    CdeFileResponse,
    CdeFileShareResponse,
    CdeFileViewResponse,
    CdeFolderContentsResponse,
    CdeFolderResponse,
    CdeFolderShareResponse,
    SharedWithMeResponse,
)
from ycpa.services.cde import CdeService
from ycpa.services.rbac import RBACService

router = APIRouter(prefix="/cde", tags=["CDE"])
logger = logging.getLogger(__name__)


async def _assert_can_manage_disciplines(session, project_id: UUID, current_user: User) -> None:
    """Only super admins, workspace owners/admins, or a project's BIM Manager
    may create/rename/delete disciplines."""
    if current_user.platform_role == "super_admin":
        return
    from ycpa.models.roles import Role
    from ycpa.models.workspace import (
        PimProject,
        PimProjectMember,
        PimWorkspace,
        PimWorkspaceMember,
    )

    project = await session.scalar(
        select(PimProject).where(
            PimProject.id == project_id,
            PimProject.deleted_at.is_(None),
        )
    )
    if not project:
        raise NotFoundException("Project not found")

    workspace = await session.scalar(
        select(PimWorkspace).where(PimWorkspace.id == project.workspace_id)
    )
    is_ws_owner = bool(workspace and workspace.owner_id == current_user.id)
    ws_member = await session.scalar(
        select(PimWorkspaceMember).where(
            PimWorkspaceMember.workspace_id == project.workspace_id,
            PimWorkspaceMember.user_id == current_user.id,
            PimWorkspaceMember.role == "admin",
        )
    )
    proj_member = await session.scalar(
        select(PimProjectMember).where(
            PimProjectMember.project_id == project_id,
            PimProjectMember.user_id == current_user.id,
        )
    )
    is_bim_manager = False
    if proj_member and proj_member.role_id:
        role = await session.scalar(select(Role).where(Role.id == proj_member.role_id))
        is_bim_manager = bool(role and role.name == "BIM Manager")

    if not (is_ws_owner or ws_member or is_bim_manager):
        raise ForbiddenException(
            "Only workspace owner, admin, or BIM Manager can manage disciplines"
        )



@router.get("/folders/contents", response_model=SuccessResponse[CdeFolderContentsResponse])
async def get_folder_contents(
    owner_type:   str           = Query(..., description="pim_project | aim_project | user"),
    owner_id:     UUID          = Query(..., description="UUID of the project or user"),
    folder_id:    Optional[UUID]= Query(None, description="Folder to open; omit for root"),
    current_user: User          = Depends(get_current_user),
    session:      AsyncSession  = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.get_folder_contents(owner_type, owner_id, folder_id, current_user)
    return SuccessResponse(data=result)


@router.post("/folders", response_model=SuccessResponse[CdeFolderResponse], status_code=201)
async def create_folder(
    body:         CreateFolderRequest,
    owner_type:   str          = Query(...),
    owner_id:     UUID         = Query(...),
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.create_folder(body, owner_type, owner_id, current_user)
    return SuccessResponse(data=result)


@router.patch("/folders/{folder_id}", response_model=SuccessResponse[CdeFolderResponse])
async def rename_folder(
    folder_id:    UUID,
    body:         RenameFolderRequest,
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.rename_folder(folder_id, body, current_user)
    return SuccessResponse(data=result)


@router.delete("/folders/{folder_id}", response_model=SuccessResponse[None])
async def delete_folder(
    folder_id:    UUID,
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    await service.delete_folder(folder_id, current_user)
    return SuccessResponse(data=None)



@router.post(
    "/folders/{folder_id}/share",
    response_model=SuccessResponse[CdeFolderShareResponse],
    status_code=201,
    summary="Share a folder with an email address",
)
async def share_folder(
    folder_id:        UUID,
    body:             ShareFolderRequest,
    background_tasks: BackgroundTasks,               # ← FIX: injected here
    current_user:     User         = Depends(get_current_user),
    session:          AsyncSession = Depends(get_async_session),
):

    service = CdeService(session)
    result  = await service.share_folder(folder_id, body, current_user, background_tasks)
    return SuccessResponse(
        success=True,
        message=f"Folder shared with {body.email}.",
        data=result,
    )


@router.get(
    "/folders/{folder_id}/shares",
    response_model=SuccessResponse[list[CdeFolderShareResponse]],
    summary="List all shares for a folder (real + pending)",
)
async def get_folder_shares(
    folder_id:    UUID,
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.get_folder_shares(folder_id, current_user)
    return SuccessResponse(data=result)



@router.patch("/files/{file_id}/move", response_model=SuccessResponse[CdeFileResponse])
async def move_file(
    file_id:      UUID,
    body:         MoveFileRequest,
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.move_file(file_id, body, current_user)
    return SuccessResponse(data=result)



@router.get("/files", response_model=SuccessResponse[CdeFileListResponse])
async def list_files(
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.list_files(current_user)
    return SuccessResponse(data=result)


@router.get("/files/{file_id}/view", response_model=SuccessResponse[CdeFileViewResponse])
async def view_file(
    file_id:      UUID,
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.get_view_urls(file_id, current_user)
    return SuccessResponse(data=result)


@router.get(
    "/files/{file_id}/frag",
    summary="Stream the .frag render bytes for an IFC file (CORS-safe, for the 3D viewer)",
)
async def get_file_frag(
    file_id:      UUID,
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    # The viewer renders the lightweight .frag child, never the raw .ifc. Access
    # follows the parent IFC, so we authorize on it and stream the frag's bytes
    # through the backend (avoids S3 CORS, keeps RBAC).
    repo = CdeFileRepository(session)
    ifc  = await repo.get_by_id(file_id)
    if not ifc:
        raise NotFoundException("File not found")
    if not await repo.can_view(file_id, current_user.id):
        raise ForbiddenException("You don't have access to this file")

    frag = await repo.get_frag_child(file_id)
    if not frag:
        raise NotFoundException("This model has not been processed for viewing yet.")

    frag_key = "samples/sample_building.frag" if ifc.is_demo else frag.s3_key
    try:
        content, _ = await get_object_bytes(frag_key)
    except Exception as e:
        logger.error("Frag fetch failed", extra={"file_id": str(file_id)}, exc_info=True)
        raise NotFoundException("Rendered model could not be loaded.") from e

    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Length": str(len(content))},
    )


@router.post(
    "/files/{file_id}/share",
    response_model=SuccessResponse[CdeFileShareResponse],
    status_code=201,
    summary="Share a file with an email address",
)
async def share_file(
    file_id:          UUID,
    body:             ShareFileRequest,
    background_tasks: BackgroundTasks,               # ← FIX: injected here
    current_user:     User         = Depends(get_current_user),
    session:          AsyncSession = Depends(get_async_session),
):

    service = CdeService(session)
    result  = await service.share_file(file_id, body, current_user, background_tasks)
    return SuccessResponse(
        success=True,
        message=f"File shared with {body.email}.",
        data=result,
    )


@router.get(
    "/files/{file_id}/shares",
    response_model=SuccessResponse[list[CdeFileShareResponse]],
    summary="List all shares for a file (real + pending)",
)
async def get_shares(
    file_id:      UUID,
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.get_shares(file_id, current_user)
    return SuccessResponse(data=result)


@router.post("/files/{file_id}/publish", response_model=SuccessResponse[CdeFileResponse])
async def publish_file(
    file_id:      UUID,
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.publish_file(file_id, current_user)
    return SuccessResponse(data=result)


@router.post("/files/{file_id}/archive", response_model=SuccessResponse[CdeFileResponse])
async def archive_file(
    file_id:      UUID,
    current_user: User         = Depends(get_current_user),
    session:      AsyncSession = Depends(get_async_session),
):
    service = CdeService(session)
    result  = await service.archive_file(file_id, current_user)
    return SuccessResponse(data=result)


@router.get(
    "/shared-with-me",
    response_model=SuccessResponse[SharedWithMeResponse],
    summary="List all files and folders shared with the current user",
)
async def get_shared_with_me(
    current_user: CurrentUser,
    session:      DatabaseSession,
):
    service = CdeService(session)
    result  = await service.get_shared_with_me(current_user)
    return SuccessResponse(data=result)


@router.get(
    "/disciplines",
    summary="List disciplines for a project",
)
async def list_disciplines(

        current_user: CurrentUser,
        session: DatabaseSession,
        owner_type: str = Query(..., description="pim_project | aim_project"),
        owner_id: UUID = Query(..., description="project UUID"),
):
    if owner_type != "pim_project":
        return SuccessResponse(data=[])

    from ycpa.models.workspace import PimProject, PimScopeDiscipline

    project = await session.scalar(
        select(PimProject).where(
            PimProject.id == owner_id,
            PimProject.deleted_at.is_(None),
        )
    )
    if not project:
        raise NotFoundException("Project not found")
    if current_user.platform_role != "super_admin":
        role = await RBACService.get_workspace_role(
            session, current_user.id, project.workspace_id, "pim"
        )
        if role is None:
            raise ForbiddenException("You don't have access to this project.")

    rows = await session.execute(
        select(PimScopeDiscipline).where(
            PimScopeDiscipline.project_id == owner_id,
            PimScopeDiscipline.deleted_at.is_(None),
        ).order_by(PimScopeDiscipline.order, PimScopeDiscipline.name)
    )
    disciplines = rows.scalars().all()
    return SuccessResponse(data=[
        {"id": str(d.id), "name": d.name, "color": d.color}
        for d in disciplines
    ])


@router.post(
    "/disciplines",
    status_code=201,
    summary="Create a discipline for a project (BIM Manager / admin only)",
)
async def create_discipline(
        current_user: CurrentUser,
        session: DatabaseSession,
        body: CreateDisciplineRequest,
        owner_id: UUID = Query(..., description="project UUID"),

):
    from ycpa.models.workspace import PimScopeDiscipline

    await _assert_can_manage_disciplines(session, owner_id, current_user)

    existing = await session.scalar(
        select(PimScopeDiscipline).where(
            PimScopeDiscipline.project_id == owner_id,
            PimScopeDiscipline.name == body.name.strip(),
            PimScopeDiscipline.deleted_at.is_(None),
        )
    )
    if existing:
        raise ConflictException(message=f"Discipline '{body.name}' already exists in this project")

    from sqlalchemy import func
    max_order = await session.scalar(
        select(func.max(PimScopeDiscipline.order)).where(
            PimScopeDiscipline.project_id == owner_id,
            PimScopeDiscipline.deleted_at.is_(None),
        )
    ) or 0

    discipline = PimScopeDiscipline(
        project_id=owner_id,
        name=body.name.strip(),
        color=body.color or "#64748b",
        order=max_order + 1,
        created_by=current_user.id,
    )
    session.add(discipline)
    await session.commit()
    await session.refresh(discipline)

    return SuccessResponse(
        data={"id": str(discipline.id), "name": discipline.name, "color": discipline.color},
        message=f"Discipline '{discipline.name}' created.",
    )


@router.patch(
    "/disciplines/{discipline_id}",
    summary="Rename a discipline or change its color",
)
async def update_discipline(
        discipline_id: UUID,
        current_user: CurrentUser,
        session: DatabaseSession,
        body: UpdateDisciplineRequest,
):
    from datetime import datetime, timezone

    from ycpa.models.workspace import PimScopeDiscipline

    discipline = await session.scalar(
        select(PimScopeDiscipline).where(
            PimScopeDiscipline.id == discipline_id,
            PimScopeDiscipline.deleted_at.is_(None),
        )
    )
    if not discipline:
        raise NotFoundException("Discipline not found")

    await _assert_can_manage_disciplines(session, discipline.project_id, current_user)

    if body.name is not None:
        discipline.name = body.name.strip()
    if body.color is not None:
        discipline.color = body.color
    discipline.updated_by = current_user.id
    discipline.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(discipline)

    return SuccessResponse(
        data={"id": str(discipline.id), "name": discipline.name, "color": discipline.color}
    )


@router.delete(
    "/disciplines/{discipline_id}",
    summary="Delete a discipline (folders keep discipline_id but it becomes NULL via SET NULL)",
)
async def delete_discipline(
        discipline_id: UUID,
        current_user: CurrentUser,
        session: DatabaseSession,
):
    from datetime import datetime, timezone

    from ycpa.models.workspace import PimScopeDiscipline

    discipline = await session.scalar(
        select(PimScopeDiscipline).where(
            PimScopeDiscipline.id == discipline_id,
            PimScopeDiscipline.deleted_at.is_(None),
        )
    )
    if not discipline:
        raise NotFoundException("Discipline not found")

    await _assert_can_manage_disciplines(session, discipline.project_id, current_user)

    discipline.deleted_at = datetime.now(timezone.utc)
    discipline.deleted_by = current_user.id
    await session.commit()

    return SuccessResponse(data=None, message="Discipline deleted.")
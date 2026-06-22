import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from typing import List, Optional  # noqa: UP035

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel

from ycpa.core.auth.dependencies import CurrentUser
from ycpa.core.database.dependencies import DatabaseSession
from ycpa.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    StorageException,
)
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.core.storage.s3 import (
    ALLOWED_EXTENSIONS,
    S3_BUCKET,
    delete_file_from_s3,
    generate_presigned_url,
    get_object_bytes,
    list_files_from_s3,
    upload_file_to_s3,
)
from ycpa.models.cde import CdeFile
from ycpa.repositories.cde import CdeFileRepository
from ycpa.schemas.responses.cde import CdeFileResponse
from ycpa.services.rbac import RBACService

router = APIRouter(prefix="/upload", tags=["Upload"])


ALLOWED_OWNER_TYPES = {"user", "pim_project", "aim_project"}



class FileListItem(BaseModel):
    key: str
    filename: str
    size: int
    last_modified: str
    url: str
    content_type: Optional[str] = None


class FileListResponse(BaseModel):
    files: List[FileListItem]
    total_count: int
    total_size: int
    folder: str



logger = logging.getLogger(__name__)
def _get_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _get_mime(filename: str, fallback: str = "application/octet-stream") -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or fallback


def _build_response(
    cde_file: CdeFile,
    uploader_name: str | None,
    frag_s3_key: str | None = None,
) -> CdeFileResponse:
    return CdeFileResponse(
        id=cde_file.id,
        filename=cde_file.original_filename,
        file_extension=cde_file.file_extension,
        mime_type=cde_file.mime_type,
        status=cde_file.status,
        s3_key=cde_file.s3_key,
        frag_s3_key=frag_s3_key,
        file_size_bytes=cde_file.file_size_bytes,
        owner_type=cde_file.owner_type,
        owner_id=cde_file.owner_id,
        folder_id=cde_file.folder_id,
        uploaded_by=cde_file.uploaded_by,
        uploaded_by_name=uploader_name,
        discipline=cde_file.discipline,
        description=cde_file.description,
        is_demo=cde_file.is_demo,
        version=cde_file.version,
        created_at=cde_file.created_at,
        updated_at=cde_file.updated_at,
        can_edit=True,
        share_count=0,
    )



@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[CdeFileResponse],
    summary="Upload any CDE-supported file to S3 and register it in the database",
)
async def upload_file(
    current_user: CurrentUser,
    session: DatabaseSession,
    file: UploadFile = File(...),
    owner_type: str = Query(default="user", description="user | pim_project | aim_project"),
    owner_id: Optional[str] = Query(default=None),
    folder_id: Optional[str] = Query(default=None),
    discipline: Optional[str] = Query(default=None),
    description: Optional[str] = Query(default=None),
    parent_file_id: Optional[str] = Query(
        default=None,
        description="CdeFile UUID of parent IFC — set when uploading a .frag companion",
    ),
    upload_id: Optional[str] = Query(
        default=None,
        description="Shared UUID so paired IFC + frag files share the same stem",
    ),
):
    if not file.filename:
        raise BadRequestException("Filename is required")

    ext = _get_extension(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise BadRequestException(
            f"File type '.{ext}' is not supported. "
            f"Supported types: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    if owner_type not in ALLOWED_OWNER_TYPES:
        raise BadRequestException(
            f"Invalid owner_type. Must be one of: {', '.join(ALLOWED_OWNER_TYPES)}"
        )

    resolved_owner_id: uuid.UUID
    if owner_type == "user":
        resolved_owner_id = current_user.id
    else:
        if not owner_id:
            raise BadRequestException("owner_id is required when owner_type is not 'user'")
        try:
            resolved_owner_id = uuid.UUID(owner_id)
        except ValueError:
            raise BadRequestException("owner_id must be a valid UUID")

        # Authz: only project members with CDE edit rights may upload into a project,
        # otherwise any authenticated user could write files into another's project.
        if current_user.platform_role != "super_admin":
            ws_type = "pim" if owner_type == "pim_project" else "aim"
            allowed = await RBACService.get_project_permission(
                db=session,
                user_id=current_user.id,
                project_id=resolved_owner_id,
                workspace_type=ws_type,
                module="cde",
                action="can_edit",
            )
            if not allowed:
                raise ForbiddenException(
                    "You don't have permission to upload files to this project."
                )

    resolved_folder_id: uuid.UUID | None = None
    if folder_id:
        try:
            resolved_folder_id = uuid.UUID(folder_id)
        except ValueError:
            raise BadRequestException("folder_id must be a valid UUID")

    resolved_parent_id: uuid.UUID | None = None
    if parent_file_id:
        try:
            resolved_parent_id = uuid.UUID(parent_file_id)
        except ValueError:
            raise BadRequestException("parent_file_id must be a valid UUID")

        cde_repo = CdeFileRepository(session)
        parent   = await cde_repo.get_by_id(resolved_parent_id)
        if not parent:
            raise NotFoundException("Parent file not found")
        if parent.uploaded_by != current_user.id:
            raise ForbiddenException("You can only attach .frag files to your own IFC files")
        if parent.file_extension != "ifc":
            raise BadRequestException("parent_file_id must reference an IFC file")

    try:
        result = await upload_file_to_s3(file, folder="uploads", upload_id=upload_id or None)
    except Exception as e:
        logger.error("S3 upload failed", exc_info=True)
        raise StorageException(message="File upload failed", details={"error": str(e)})

    s3_key        = result["key"]
    file_size     = result["size"]
    original_name = result["original_filename"]
    content_type  = result.get("content_type") or _get_mime(file.filename)

    # ── Persist to DB ──────────────────────────────────────────────────────────
    cde_repo = CdeFileRepository(session)
    cde_file = CdeFile(
        owner_type=owner_type,
        owner_id=resolved_owner_id,
        uploaded_by=current_user.id,
        folder_id=resolved_folder_id,
        filename=original_name,
        original_filename=original_name,
        s3_key=s3_key,
        file_size_bytes=file_size,
        mime_type=content_type,
        file_extension=ext,
        status="wip",
        discipline=discipline,
        description=description,
        is_demo=False,
        parent_file_id=resolved_parent_id,
        created_by=current_user.id,
    )
    session.add(cde_file)
    await session.flush()
    await session.commit()
    await session.refresh(cde_file)

    logger.info(
        "File uploaded",
        extra={
            "user_id":        str(current_user.id),
            "cde_file_id":    str(cde_file.id),
            "s3_key":         s3_key,
            "ext":            ext,
            "folder_id":      str(resolved_folder_id) if resolved_folder_id else None,
            "parent_file_id": str(resolved_parent_id) if resolved_parent_id else None,
        },
    )

    frag_s3_key: str | None = None
    if ext == "ifc":
        frag_child  = await cde_repo.get_frag_child(cde_file.id)
        frag_s3_key = frag_child.s3_key if frag_child else None

    return SuccessResponse(
        success=True,
        message="File uploaded successfully",
        data=_build_response(cde_file, current_user.full_name, frag_s3_key),
    )


# ── DELETE /upload/{file_id} ───────────────────────────────────────────────────

@router.delete(
    "/{file_id}",
    response_model=SuccessResponse,
    summary="Delete a CDE file by DB UUID (soft-deletes row, hard-deletes from S3)",
)
async def delete_file(
    file_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
):
    cde_repo = CdeFileRepository(session)
    cde_file = await cde_repo.get_by_id(file_id)

    if not cde_file:
        raise NotFoundException("File not found")
    if cde_file.uploaded_by != current_user.id and current_user.platform_role != "super_admin":
        raise ForbiddenException("Only the file owner can delete it")

    # Also remove .frag child if this is an IFC file
    if cde_file.file_extension == "ifc":
        frag_child = await cde_repo.get_frag_child(file_id)
        if frag_child:
            try:
                await delete_file_from_s3(frag_child.s3_key)
            except Exception as e:
                logger.warning(f"S3 delete failed for frag key {frag_child.s3_key}: {e}")
            frag_child.deleted_at = datetime.now(timezone.utc)
            frag_child.deleted_by = current_user.id

    try:
        await delete_file_from_s3(cde_file.s3_key)
    except Exception as e:
        logger.warning(f"S3 delete failed for key {cde_file.s3_key}: {e}")

    cde_file.deleted_at = datetime.now(timezone.utc)
    cde_file.deleted_by = current_user.id
    await session.commit()

    return SuccessResponse(success=True, message="File deleted successfully")


# ── DELETE /upload/by-key ──────────────────────────────────────────────────────

@router.delete(
    "/by-key",
    response_model=SuccessResponse,
    summary="Delete a file directly by its raw S3 key (used by the frontend file list)",
)
async def delete_file_by_key(
    current_user: CurrentUser,
    session: DatabaseSession,
    s3_key: str = Query(..., description="Raw S3 key, e.g. uploads/abc123.ifc"),
):
    """
    Deletes both the S3 object and the matching DB row (if any).
    Useful when the frontend holds S3 keys from the /list endpoint
    rather than DB UUIDs.
    """
    # Require a matching DB record owned by the caller — otherwise this endpoint
    # would let any user delete arbitrary objects from the bucket by raw key.
    cde_repo = CdeFileRepository(session)
    db_file  = await cde_repo.get_by_field("s3_key", s3_key)

    if not db_file:
        raise NotFoundException("File not found")
    if db_file.uploaded_by != current_user.id and current_user.platform_role != "super_admin":
        raise ForbiddenException("Only the file owner can delete it")

    db_file.deleted_at = datetime.now(timezone.utc)
    db_file.deleted_by = current_user.id
    await session.commit()

    # Hard-delete from S3
    try:
        await delete_file_from_s3(s3_key)
    except Exception as e:
        logger.warning(f"S3 delete failed for key {s3_key}: {e}")
        raise StorageException(message="S3 deletion failed", details={"error": str(e)})

    return SuccessResponse(success=True, message="File deleted successfully")


# ── GET /upload/presigned/{file_id} ───────────────────────────────────────────

@router.get(
    "/presigned/{file_id}",
    response_model=SuccessResponse[dict],
    summary="Get a presigned download URL for a CDE file by DB UUID",
)
async def get_presigned_url(
    file_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
    expiration: int = Query(default=3600, ge=60, le=604800),
):
    cde_repo = CdeFileRepository(session)
    cde_file = await cde_repo.get_by_id(file_id)

    if not cde_file:
        raise NotFoundException("File not found")
    if not await cde_repo.can_view(file_id, current_user.id):
        raise ForbiddenException("You don't have access to this file")

    # ← was sync, now correctly awaited
    url = await generate_presigned_url(cde_file.s3_key, expiration)

    return SuccessResponse(
        success=True,
        message="Presigned URL generated",
        data={
            "url":        url,
            "expires_in": expiration,
            "file_id":    str(file_id),
            "filename":   cde_file.original_filename,
        },
    )


# ── GET /upload/presigned-by-key ──────────────────────────────────────────────

@router.get(
    "/presigned-by-key",
    response_model=SuccessResponse[dict],
    summary="Get a presigned URL by raw S3 key (used by the frontend file list)",
)
async def get_presigned_url_by_key(
    current_user: CurrentUser,
    session: DatabaseSession,
    s3_key: str = Query(..., description="Raw S3 key, e.g. uploads/abc.frag"),
    expiration: int = Query(default=3600, ge=60, le=604800),
):
    # A presigned URL grants download access, so the caller must be allowed to
    # view the file this key belongs to. Never mint a URL for an arbitrary key.
    cde_repo = CdeFileRepository(session)
    db_file  = await cde_repo.get_by_field("s3_key", s3_key)
    if not db_file:
        raise NotFoundException("File not found")

    # A .frag companion inherits the access of its parent IFC file, so the viewer
    # can fetch it whenever the user can view the model itself.
    check_id = db_file.parent_file_id or db_file.id
    if not await cde_repo.can_view(check_id, current_user.id):
        raise ForbiddenException("You don't have access to this file")

    url = await generate_presigned_url(s3_key, expiration)
    return SuccessResponse(
        success=True,
        message="Presigned URL generated",
        data={"url": url, "expires_in": expiration, "s3_key": s3_key},
    )


# ── GET /upload/proxy/{file_id} ───────────────────────────────────────────────

@router.get(
    "/proxy/{file_id}",
    summary="Proxy a file from S3 through the server (avoids browser CORS issues)",
)
async def proxy_file(
    file_id: uuid.UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
):
    cde_repo = CdeFileRepository(session)
    cde_file = await cde_repo.get_by_id(file_id)

    if not cde_file:
        raise NotFoundException("File not found")
    if not await cde_repo.can_view(file_id, current_user.id):
        raise ForbiddenException("You don't have access to this file")

    try:
        # ← was s3_client.get_object() (sync, blocks event loop)
        #   now fully async
        content, content_type = await get_object_bytes(cde_file.s3_key)
    except Exception as e:
        logger.error(
            "S3 proxy fetch failed",
            extra={"file_id": str(file_id), "key": cde_file.s3_key},
            exc_info=True,
        )
        raise StorageException(
            message="Failed to retrieve file from storage",
            details={"error": str(e), "file_id": str(file_id)},
        )

    mime_type = cde_file.mime_type or content_type or _get_mime(cde_file.original_filename)

    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{cde_file.original_filename}"',
            "Content-Length":      str(len(content)),
        },
    )


# ── GET /upload/list ──────────────────────────────────────────────────────────

@router.get(
    "/list",
    response_model=SuccessResponse[FileListResponse],
    summary="List files from S3 (optionally filter by extension)",
)
async def list_files(
    current_user: CurrentUser,
    session: DatabaseSession,
    folder: str = Query(default="uploads"),
    file_extension: Optional[str] = Query(default=None),
):
    files = await list_files_from_s3(folder=folder, file_extension=file_extension)

    # Never expose the whole bucket: restrict to keys the caller can actually see.
    if current_user.platform_role != "super_admin":
        cde_repo     = CdeFileRepository(session)
        visible      = await cde_repo.get_all_visible(current_user.id)
        allowed_keys = {f.s3_key for f in visible}
        files        = [f for f in files if f.get("key") in allowed_keys]

    total_count = len(files)
    total_size  = sum(f["size"] for f in files)

    return SuccessResponse(
        success=True,
        message=f"Found {total_count} file{'s' if total_count != 1 else ''}",
        data=FileListResponse(
            files=[FileListItem(**f) for f in files],
            total_count=total_count,
            total_size=total_size,
            folder=folder,
        ),
    )
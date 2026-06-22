from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CdeFileShareResponse(BaseModel):
    id: UUID | None = None
    shared_with_id: UUID | None = None
    shared_with_name: str | None = None
    shared_with_email: str
    can_edit: bool
    shared_at: datetime
    is_pending: bool = False

    model_config = {"from_attributes": True}


class CdeFolderShareResponse(BaseModel):
    id: UUID | None = None
    shared_with_id: UUID | None = None
    shared_with_name: str | None = None
    shared_with_email: str
    can_edit: bool
    shared_at: datetime
    is_pending: bool = False
    file_count: int = 0

    model_config = {"from_attributes": True}


class CdeFileResponse(BaseModel):
    id: UUID
    filename: str
    file_extension: str | None = None
    mime_type: str
    status: str
    s3_key: str
    frag_s3_key: str | None = None
    file_size_bytes: int
    owner_type: str
    owner_id: UUID
    folder_id: UUID | None = None
    uploaded_by: UUID
    uploaded_by_name: str | None = None
    discipline: str | None = None
    description: str | None = None
    is_demo: bool = False
    version: int = 1
    created_at: datetime
    updated_at: datetime
    can_edit: bool = False
    share_count: int = 0

    model_config = {"from_attributes": True}


class CdeFileListResponse(BaseModel):
    files: list[CdeFileResponse]
    total: int


class CdeFileViewResponse(BaseModel):
    file_id: UUID
    filename: str
    file_extension: str | None = None
    frag_url: str | None = None
    ifc_url: str | None = None
    expires_in: int = 3600


# ── Folder responses ──────────────────────────────────────────────────────────

class CdeFolderResponse(BaseModel):
    id: UUID
    name: str
    owner_type: str
    owner_id: UUID
    parent_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    created_by: UUID

    model_config = {"from_attributes": True}


class CdeBreadcrumbItem(BaseModel):
    id: UUID | None = None
    name: str


class CdeFolderContentsResponse(BaseModel):
    current_folder: CdeFolderResponse | None = None
    breadcrumb: list[CdeBreadcrumbItem]
    folders: list[CdeFolderResponse]
    files: list[CdeFileResponse]
    total_folders: int
    total_files: int


class SharedFileItem(BaseModel):
    type: str = "file"
    id: UUID
    name: str
    file_extension: str | None
    status: str
    file_size_bytes: int
    owner_type: str
    owner_id: UUID
    folder_id: UUID | None
    folder_name: str | None
    can_edit: bool
    shared_at: datetime
    workspace_name: str | None
    project_name: str | None

    model_config = {"from_attributes": True}


class SharedFolderItem(BaseModel):
    type: str = "folder"
    id: UUID
    name: str
    owner_type: str
    owner_id: UUID
    parent_id: UUID | None
    parent_folder_name: str | None
    can_edit: bool
    shared_at: datetime
    file_count: int = 0
    workspace_name: str | None
    project_name: str | None

    model_config = {"from_attributes": True}


class SharedWithMeResponse(BaseModel):
    files: list[SharedFileItem]
    folders: list[SharedFolderItem]
    total: int

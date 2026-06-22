from uuid import UUID

from pydantic import BaseModel, Field


class ShareFileRequest(BaseModel):
    email: str
    can_edit: bool = False
    role_name: str | None = None


class ShareFolderRequest(BaseModel):
    email: str
    can_edit: bool = False
    role_name: str | None = None


class UpdateFileStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(wip|shared|published|archived)$")


class UploadCdeFileRequest(BaseModel):
    name: str
    project_id: UUID | None = None



class CreateFolderRequest(BaseModel):
    name:          str            = Field(..., min_length=1, max_length=255)
    parent_id:     UUID | None = None
    discipline_id: UUID | None = None


class RenameFolderRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class MoveFileRequest(BaseModel):
    folder_id: UUID | None = None


class CreateDisciplineRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str | None = None


class UpdateDisciplineRequest(BaseModel):
    name: str | None = None
    color: str | None = None

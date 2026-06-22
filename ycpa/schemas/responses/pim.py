import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PimWorkspaceMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id:    uuid.UUID
    role:       str
    joined_at:  datetime
    full_name:  str | None = None
    email:      str | None = None
    avatar_url: str | None = None


class PimProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:            uuid.UUID
    workspace_id:  uuid.UUID
    name:          str
    description:   str | None = None
    location:      str | None = None
    project_code:  str | None = None
    thumbnail_url: str | None = None
    status:        str
    import_locked: bool
    created_at:    datetime
    updated_at:    datetime
    member_count:  int = 0
    file_count:    int = 0


class PimWorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:            uuid.UUID
    name:          str
    description:   str | None = None
    avatar_url:    str | None = None
    is_active:     bool
    created_at:    datetime
    updated_at:    datetime
    role:          str
    owner_id:      uuid.UUID
    project_count: int = 0
    member_count:  int = 0


class PimWorkspaceDetailResponse(PimWorkspaceResponse):
    projects: list[PimProjectResponse]         = []
    members:  list[PimWorkspaceMemberResponse] = []


class PimWorkspaceListResponse(BaseModel):

    my_workspaces:     list[PimWorkspaceResponse] = []
    shared_workspaces: list[PimWorkspaceResponse] = []
    total:             int                        = 0

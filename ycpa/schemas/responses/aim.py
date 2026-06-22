import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AimWorkspaceMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id:    uuid.UUID
    role:       str
    joined_at:  datetime
    full_name:  str | None = None
    email:      str | None = None
    avatar_url: str | None = None


class AimProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:            uuid.UUID
    workspace_id:  uuid.UUID
    name:          str
    description:   str | None = None
    location:      str | None = None
    asset_type:    str | None = None
    thumbnail_url: str | None = None
    status:        str
    created_at:    datetime
    updated_at:    datetime
    member_count:  int = 0
    file_count:    int = 0


class AimWorkspaceResponse(BaseModel):
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


class AimWorkspaceDetailResponse(AimWorkspaceResponse):
    projects: list[AimProjectResponse]         = []
    members:  list[AimWorkspaceMemberResponse] = []


class AimWorkspaceListResponse(BaseModel):
    my_workspaces:     list[AimWorkspaceResponse] = []
    shared_workspaces: list[AimWorkspaceResponse] = []
    total:             int                        = 0

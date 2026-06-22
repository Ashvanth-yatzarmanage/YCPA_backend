from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ProjectMemberResponse(BaseModel):
    user_id:    UUID
    role_id:    UUID
    role_name:  str
    full_name:  str
    email:      str
    avatar_url: str | None = None
    joined_at:  datetime
    is_share_only: bool = False

    model_config = {"from_attributes": True}


class ProjectMemberListResponse(BaseModel):
    members: list[ProjectMemberResponse]
    total:   int


class AssignableWorkspaceMemberResponse(BaseModel):

    user_id:        UUID
    full_name:      str
    email:          str
    avatar_url:     str | None = None
    workspace_role: str

    model_config = {"from_attributes": True}


class AssignableWorkspaceMemberListResponse(BaseModel):
    members: list[AssignableWorkspaceMemberResponse]
    total:   int


class BulkAssignResult(BaseModel):
    user_id:   UUID
    email:     str
    full_name: str
    status:    str
    role_name: str | None = None


class BulkAssignResponse(BaseModel):
    results: list[BulkAssignResult]
    added:   int
    skipped: int
    total:   int

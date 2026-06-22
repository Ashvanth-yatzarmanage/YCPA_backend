from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class InvitationDetailResponse(BaseModel):
    token:           str
    email:           str
    role_name:       str
    project_name:    str | None = None
    workspace_name:  str
    workspace_type:  str
    invited_by_name: str
    expires_at:      datetime
    status:          str
    invite_type:     str = "project"

    model_config = {"from_attributes": True}


class InvitationAcceptResponse(BaseModel):
    workspace_id:   UUID
    workspace_type: str
    workspace_name: str
    role_name:      str
    invite_type:    str
    project_id:   UUID | None = None
    project_name: str | None  = None

    model_config = {"from_attributes": True}

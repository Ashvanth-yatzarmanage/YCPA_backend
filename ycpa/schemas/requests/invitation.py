from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr

WorkspaceRole = Literal["member"]


class SendInvitationRequest(BaseModel):
    email:      EmailStr
    project_id: UUID | None = None
    role_name:  str = "BIM Member"


class SendWorkspaceInvitationRequest(BaseModel):
    email: EmailStr


class AcceptInvitationRequest(BaseModel):
    token: str

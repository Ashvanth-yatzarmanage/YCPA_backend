from typing import List, Literal  # noqa: UP035
from uuid import UUID

from pydantic import BaseModel, EmailStr


class InviteProjectMemberRequest(BaseModel):
    email:     EmailStr
    role_name: str = "BIM Member"


class AssignWorkspaceMemberRequest(BaseModel):

    user_id:   UUID
    role_name: str = "BIM Member"


class BulkAssignMembersRequest(BaseModel):

    members: list[AssignWorkspaceMemberRequest]


class UpdateProjectMemberRoleRequest(BaseModel):
    role_name: str

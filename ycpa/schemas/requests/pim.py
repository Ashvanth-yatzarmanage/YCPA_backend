from typing import Optional
from uuid import UUID as _UUID

from pydantic import BaseModel, field_validator


class CreatePimWorkspaceRequest(BaseModel):
    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Workspace name cannot be empty")
        if len(v) > 100:
            raise ValueError("Workspace name cannot exceed 100 characters")
        return v


class UpdatePimWorkspaceRequest(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Workspace name cannot be empty")
        return v


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"  # admin | member

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("admin", "member"):
            raise ValueError("Role must be 'admin' or 'member'")
        return v

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or "@" not in v:
            raise ValueError("Invalid email address")
        return v


class UpdateWorkspaceMemberRoleRequest(BaseModel):
    role: str  # admin | member

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("admin", "member"):
            raise ValueError("Role must be 'admin' or 'member'")
        return v


class CreatePimProjectRequest(BaseModel):
    name: str
    description: str | None = None
    location: str | None = None
    project_code: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Project name cannot be empty")
        if len(v) > 100:
            raise ValueError("Project name cannot exceed 100 characters")
        return v


class UpdatePimProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    location: str | None = None
    project_code: str | None = None
    status: str | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("active", "on_hold", "completed", "archived"):
            raise ValueError("Invalid status")
        return v


class CreateWorkspaceRoleRequest(BaseModel):
    name: str
    description: str | None = None
    product_type: str = "both"


class UpdateWorkspaceRoleRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class CloneRoleRequest(BaseModel):
    new_name: str


class BulkPermissionItemRequest(BaseModel):
    module_id: _UUID
    submodule_id: _UUID | None = None
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_approve: bool = False
    can_share: bool = False


class BulkPermissionsRequest(BaseModel):
    permissions: list[BulkPermissionItemRequest]

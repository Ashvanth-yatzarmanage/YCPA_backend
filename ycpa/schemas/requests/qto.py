from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class QtoExtractRequest(BaseModel):
    file_id: UUID
    project_id: UUID
    owner_type: Literal["pim_project", "aim_project"]

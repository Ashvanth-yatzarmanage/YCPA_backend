from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class BaseResponse(BaseModel, Generic[DataT]):
    success:    bool         = True
    message:    str  | None  = None
    data:       DataT | None = None
    request_id: str  | None  = None


SuccessResponse = BaseResponse


class PaginatedResponse(BaseModel, Generic[DataT]):
    success:    bool       = True
    data:       list[DataT]
    request_id: str | None = None
    pagination: "PaginationMeta"



class FileUploadData(BaseModel):
    filename: str
    url: str
    key: str
    size: int
    content_type: str

class PaginationMeta(BaseModel):
    page:        int
    page_size:   int
    total_items: int
    total_pages: int
    has_next:    bool
    has_prev:    bool


PaginatedResponse.model_rebuild()


from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class QtoElementResponse(BaseModel):
    internal_id:        str
    global_id:          str
    name:               str | None  = None
    family:             str | None  = None
    material:           str | None  = None
    length:             float | None = None
    width:              float | None = None
    height:             float | None = None
    net_surface_area:   float | None = None
    outer_surface_area: float | None = None
    net_volume:         float | None = None


class QtoFamilyResponse(BaseModel):
    name:               str
    count:              int
    net_surface_area:   float | None = None
    outer_surface_area: float | None = None
    net_volume:         float | None = None
    elements:           list[QtoElementResponse]


class QtoGroupResponse(BaseModel):
    category:           str
    count:              int
    net_surface_area:   float | None = None
    outer_surface_area: float | None = None
    net_volume:         float | None = None
    families:           list[Any]


class QtoLevelResponse(BaseModel):
    level:      str
    count:      int
    categories: list[QtoGroupResponse]


class QtoResultResponse(BaseModel):
    file_id:        UUID
    filename:       str
    extracted_at:   datetime
    levels:         list[QtoLevelResponse]
    total_elements: int

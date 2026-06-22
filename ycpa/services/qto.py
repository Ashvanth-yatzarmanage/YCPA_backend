from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from ycpa.core.storage.s3 import get_object_bytes
from ycpa.models.user import User
from ycpa.repositories.cde import CdeFileRepository
from ycpa.schemas.responses.qto import (
    QtoElementResponse,
    QtoGroupResponse,
    QtoLevelResponse,
    QtoResultResponse,
)

logger = logging.getLogger(__name__)

IFC_CATEGORY_LABELS: dict[str, str] = {
    "IfcWall":                 "Walls",
    "IfcWallStandardCase":     "Walls",
    "IfcSlab":                 "Slabs",
    "IfcColumn":               "Columns",
    "IfcBeam":                 "Beams",
    "IfcDoor":                 "Doors",
    "IfcWindow":               "Windows",
    "IfcStair":                "Stairs",
    "IfcRoof":                 "Roofs",
    "IfcFooting":              "Footings",
    "IfcPile":                 "Piles",
    "IfcRailing":              "Railings",
    "IfcCovering":             "Coverings",
    "IfcMember":               "Members",
    "IfcPlate":                "Plates",
    "IfcBuildingElementProxy": "Other Elements",
    "IfcFlowTerminal":         "Equipment",
    "IfcPipeSegment":          "Pipes",
    "IfcDuctSegment":          "Ducts",
    "IfcFurnishingElement":    "Furniture",
}

SUPPORTED_IFC_CLASSES = list(IFC_CATEGORY_LABELS.keys())


def _get_storey(element) -> str:
    try:
        for rel in getattr(element, "ContainedInStructure", []):
            container = rel.RelatingStructure
            if container.is_a("IfcBuildingStorey"):
                return container.Name or "Unknown Level"
            if container.is_a("IfcSpace"):
                for rel2 in getattr(container, "Decomposes", []):
                    obj = rel2.RelatingObject
                    if obj.is_a("IfcBuildingStorey"):
                        return obj.Name or "Unknown Level"
    except Exception:
        pass
    return "Unknown Level"


def _get_family(element) -> str:
    try:
        import ifcopenshell.util.element as ifc_util
        el_type = ifc_util.get_type(element)
        if el_type and getattr(el_type, "Name", None):
            return el_type.Name
    except Exception:
        pass
    return getattr(element, "Name", None) or element.is_a()


def _get_material(element) -> str | None:
    try:
        for assoc in getattr(element, "HasAssociations", []):
            if assoc.is_a("IfcRelAssociatesMaterial"):
                mat = assoc.RelatingMaterial
                if mat.is_a("IfcMaterial"):
                    return mat.Name
                if mat.is_a("IfcMaterialLayerSetUsage"):
                    layers = mat.ForLayerSet.MaterialLayers
                    if layers:
                        return layers[0].Material.Name
                if mat.is_a("IfcMaterialList") and mat.Materials:
                    return mat.Materials[0].Name
    except Exception:
        pass
    return None


def _get_quantities(element) -> dict:
    result: dict = {}
    try:
        for rel in getattr(element, "IsDefinedBy", []):
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pdef = rel.RelatingPropertyDefinition
            if not pdef.is_a("IfcElementQuantity"):
                continue
            for qty in pdef.Quantities:
                n = qty.Name.lower()
                if qty.is_a("IfcQuantityLength"):
                    if "length" in n:
                        result.setdefault("length", round(qty.LengthValue, 6))
                    elif "width" in n:
                        result.setdefault("width", round(qty.LengthValue, 6))
                    elif "height" in n or "depth" in n:
                        result.setdefault("height", round(qty.LengthValue, 6))
                elif qty.is_a("IfcQuantityArea"):
                    if "net" in n and ("side" in n or "surface" in n or "area" in n):
                        result.setdefault("net_surface_area", round(qty.AreaValue, 6))
                    elif "outer" in n or ("gross" in n and "side" in n):
                        result.setdefault("outer_surface_area", round(qty.AreaValue, 6))
                elif qty.is_a("IfcQuantityVolume"):
                    if "net" in n:
                        result.setdefault("net_volume", round(qty.VolumeValue, 6))
                    elif "gross" in n:
                        result.setdefault("gross_volume", round(qty.VolumeValue, 6))
    except Exception:
        pass
    if "net_volume" not in result and "gross_volume" in result:
        result["net_volume"] = result.pop("gross_volume")
    return result


def _run_extraction(ifc_bytes: bytes) -> list[QtoLevelResponse]:
    import ifcopenshell

    with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as tmp:
        tmp.write(ifc_bytes)
        tmp_path = tmp.name

    try:
        ifc_file = ifcopenshell.open(tmp_path)

        # level → category → family → [elements]
        tree: dict[str, dict[str, dict[str, list[QtoElementResponse]]]] = {}

        for ifc_class in SUPPORTED_IFC_CLASSES:
            elements = ifc_file.by_type(ifc_class)
            if not elements:
                continue
            category = IFC_CATEGORY_LABELS[ifc_class]

            for el in elements:
                try:
                    elem = QtoElementResponse(
                        internal_id        = str(el.id()),
                        global_id          = el.GlobalId,
                        name               = getattr(el, "Name", None) or ifc_class,
                        family             = _get_family(el),
                        material           = _get_material(el),
                        **_get_quantities(el),
                    )
                    storey = _get_storey(el)
                    tree.setdefault(storey, {})
                    tree[storey].setdefault(category, {})
                    tree[storey][category].setdefault(elem.family or ifc_class, [])
                    tree[storey][category][elem.family or ifc_class].append(elem)
                except Exception as e:
                    logger.warning(f"QTO: skipped {getattr(el, 'GlobalId', '?')}: {e}")

        level_responses: list[QtoLevelResponse] = []

        for level_name in sorted(tree.keys()):
            cat_map = tree[level_name]
            group_responses: list[QtoGroupResponse] = []

            for cat_name in sorted(cat_map.keys()):
                fam_map = cat_map[cat_name]
                families = []
                tot_count = tot_nsa = tot_osa = tot_vol = 0
                has_nsa = has_osa = has_vol = False

                for fam_name in sorted(fam_map.keys()):
                    els   = fam_map[fam_name]
                    f_nsa = sum(e.net_surface_area   or 0 for e in els)
                    f_osa = sum(e.outer_surface_area or 0 for e in els)
                    f_vol = sum(e.net_volume         or 0 for e in els)
                    f_has_nsa = any(e.net_surface_area   is not None for e in els)
                    f_has_osa = any(e.outer_surface_area is not None for e in els)
                    f_has_vol = any(e.net_volume         is not None for e in els)

                    families.append({
                        "name":               fam_name,
                        "count":              len(els),
                        "net_surface_area":   round(f_nsa, 4) if f_has_nsa else None,
                        "outer_surface_area": round(f_osa, 4) if f_has_osa else None,
                        "net_volume":         round(f_vol, 4) if f_has_vol else None,
                        "elements":           els,
                    })
                    tot_count += len(els)
                    tot_nsa   += f_nsa;  tot_osa += f_osa;  tot_vol += f_vol
                    if f_has_nsa: has_nsa = True  # noqa: E701
                    if f_has_osa: has_osa = True  # noqa: E701
                    if f_has_vol: has_vol = True  # noqa: E701

                group_responses.append(QtoGroupResponse(
                    category           = cat_name,
                    count              = tot_count,
                    net_surface_area   = round(tot_nsa, 4) if has_nsa else None,
                    outer_surface_area = round(tot_osa, 4) if has_osa else None,
                    net_volume         = round(tot_vol, 4) if has_vol else None,
                    families           = families,
                ))

            level_responses.append(QtoLevelResponse(
                level      = level_name,
                count      = sum(g.count for g in group_responses),
                categories = group_responses,
            ))

        return level_responses

    finally:
        os.unlink(tmp_path)


class QtoService:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def extract(
        self,
        file_id:      UUID,
        project_id:   UUID,
        owner_type:   str,
        current_user: User,
    ) -> QtoResultResponse:

        repo     = CdeFileRepository(self.session)
        cde_file = await repo.get_by_id(file_id)

        if not cde_file:
            raise NotFoundException("IFC file not found")
        if cde_file.file_extension != "ifc":
            raise BadRequestException("Only .ifc files are supported for QTO extraction")
        if not await repo.can_view(file_id, current_user.id):
            raise ForbiddenException("You don't have access to this file")

        logger.info(f"QTO: downloading {cde_file.s3_key}")
        ifc_bytes, _ = await get_object_bytes(cde_file.s3_key)

        logger.info(f"QTO: extracting from {cde_file.original_filename}")
        loop   = asyncio.get_event_loop()
        levels = await loop.run_in_executor(None, _run_extraction, ifc_bytes)

        total = sum(g.count for lv in levels for g in lv.categories)
        logger.info(f"QTO: done — {total} elements in {len(levels)} levels")

        return QtoResultResponse(
            file_id        = file_id,
            filename       = cde_file.original_filename,
            extracted_at   = datetime.now(timezone.utc),
            levels         = levels,
            total_elements = total,
        )

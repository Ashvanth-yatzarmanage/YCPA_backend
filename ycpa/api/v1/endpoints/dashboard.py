import asyncio
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ycpa.core.auth.dependencies import get_current_user
from ycpa.core.database.session import get_async_session
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.models.user import User
from ycpa.services.aim import AimService
from ycpa.services.pim import PimService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
logger = logging.getLogger(__name__)


@router.get("", response_model=SuccessResponse)
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    pim_service = PimService(session)
    aim_service = AimService(session)

    pim_result, aim_result = await asyncio.gather(
        pim_service.list_workspaces(current_user),
        aim_service.list_workspaces(current_user),
    )

    pim_workspaces = []
    for ws in pim_result.my_workspaces:
        pim_workspaces.append({**ws.model_dump(), "type": "pim"})
    for ws in pim_result.shared_workspaces:
        pim_workspaces.append({**ws.model_dump(), "type": "pim"})

    aim_workspaces = []
    for ws in aim_result.my_workspaces:
        aim_workspaces.append({**ws.model_dump(), "type": "aim"})
    for ws in aim_result.shared_workspaces:
        aim_workspaces.append({**ws.model_dump(), "type": "aim"})

    total = len(pim_workspaces) + len(aim_workspaces)
    logger.info("Dashboard loaded", extra={"user_id": str(current_user.id), "total_workspaces": total})

    return SuccessResponse(
        data={
            "pim_workspaces": pim_workspaces,
            "aim_workspaces": aim_workspaces,
            "total_workspaces": total,
        }
    )
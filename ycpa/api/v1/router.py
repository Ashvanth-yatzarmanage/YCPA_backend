from fastapi import APIRouter

from ycpa.api.v1.endpoints import (
    aim,
    auth,
    billing,
    cde,
    cognito,
    dashboard,
    health,
    invitation,
    pim,
    project_members,
    qto,
    rbac,
    upload,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(cognito.router)
api_router.include_router(users.router)
api_router.include_router(dashboard.router)
api_router.include_router(pim.router)
api_router.include_router(aim.router)
api_router.include_router(cde.router)
api_router.include_router(upload.router)
api_router.include_router(project_members.router)
api_router.include_router(invitation.router)
api_router.include_router(rbac.router)
api_router.include_router(billing.router)
api_router.include_router(qto.router)


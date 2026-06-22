# ycpa/api/v1/endpoints/cognito.py
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from passlib.context import CryptContext
from jose import jwt
from pydantic import BaseModel, EmailStr

from ycpa.core.config import get_settings
from ycpa.core.database.dependencies import DatabaseSession
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.models.user import User
from ycpa.models.storage_usage import StorageUsage
from ycpa.models.subscription import AimSubscription, PimSubscription
from ycpa.repositories.auth.users import UserRepository

logger = logging.getLogger(__name__)
settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/auth", tags=["Auth"])


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


class LocalLoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post(
    "/cognito-signup",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
async def signup(body: SignupRequest, session: DatabaseSession) -> SuccessResponse:
    repo = UserRepository(session)

    existing = await repo.get_by_email(body.email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(
        cognito_sub=str(uuid.uuid4()),   # placeholder — no longer used for auth
        email=body.email,
        full_name=body.full_name,
        password_hash=_hash_password(body.password),
        email_verified=True,
        platform_role="customer",
        is_active=True,
        is_onboarded=False,
        login_count=0,
    )
    session.add(user)
    await session.flush()

    session.add(StorageUsage(user_id=user.id, bytes_used=0, bytes_limit=5_368_709_120, file_count=0))
    session.add(PimSubscription(
        user_id=user.id, plan="free", status="active",
        max_pim_workspaces=1, max_projects_per_pim_workspace=1,
        max_members_per_workspace=10, max_members_per_project=10,
        can_use_4d=False, can_use_5d=False, can_use_clash_detection=False,
        can_export_bcf=True, can_use_api=False,
    ))
    session.add(AimSubscription(
        user_id=user.id, plan="free", status="active",
        max_aim_workspaces=1, max_projects_per_aim_workspace=1,
        max_members_per_workspace=10, max_members_per_project=10,
        can_use_ai=False, can_use_api=False,
        can_use_maintenance=True, can_use_facility=True,
    ))
    await session.commit()

    logger.info("New user registered", extra={"user_id": str(user.id), "email": user.email})
    return SuccessResponse(success=True, message="Account created. You can now sign in.")


@router.post(
    "/cognito-login",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Login and get JWT tokens",
)
async def local_login(body: LocalLoginRequest, session: DatabaseSession) -> SuccessResponse:
    repo = UserRepository(session)
    user = await repo.get_by_email(body.email)

    if not user or not user.password_hash or not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Your account has been deactivated.")

    token = _create_token(str(user.id))

    return SuccessResponse(
        success=True,
        message="Login successful.",
        data={"id_token": token, "access_token": token},
    )
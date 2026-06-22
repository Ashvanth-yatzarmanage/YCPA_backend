# ycpa/core/auth/jwt_verifier.py
import logging
from typing import Any

from jose import JWTError, jwt

from ycpa.core.config import get_settings

logger = logging.getLogger(__name__)


class LocalJWTVerifier:

    def __init__(self) -> None:
        self.settings = get_settings()

    async def preload(self) -> None:
        # Nothing to preload for local JWT
        logger.info("Local JWT verifier ready (no JWKS needed)")

    async def verify_token(self, token: str, *, expected_use: str = "id") -> dict[str, Any]:
        settings = self.settings
        secret = settings.JWT_SECRET.get_secret_value()
        try:
            claims = jwt.decode(token, secret, algorithms=[settings.JWT_ALGORITHM])
        except JWTError as e:
            raise ValueError(f"Token verification failed: {e}") from e
        return claims


_jwt_verifier: LocalJWTVerifier | None = None


def get_jwt_verifier() -> LocalJWTVerifier:
    global _jwt_verifier
    if _jwt_verifier is None:
        _jwt_verifier = LocalJWTVerifier()
    return _jwt_verifier
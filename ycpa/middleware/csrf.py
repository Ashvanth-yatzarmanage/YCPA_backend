# # ycpa/middleware/csrf.py
# import secrets
# import logging
# from starlette.middleware.base import BaseHTTPMiddleware
# from starlette.requests import Request
# from starlette.responses import JSONResponse
# from ycpa.core.config import get_settings
#
# logger = logging.getLogger(__name__)
# settings = get_settings()
#
# CSRF_COOKIE_NAME    = "ycpa_csrf_token"
# CSRF_HEADER_NAME    = "x-csrf-token"
# CSRF_COOKIE_MAX_AGE = 60 * 60 * 24  # 1 day
#
# PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
#
# CSRF_EXEMPT_PATHS = frozenset([
#     "/docs",
#     "/redoc",
#     "/openapi.json",
#     "/api/v1/auth/csrf"
#     "/api/v1/auth/cognito-signup",
#     "/api/v1/auth/cognito-verify",
#     "/api/v1/auth/cognito-login",
#     "/api/v1/auth/cognito-resend-code",
#     "/api/v1/auth/login",
# ])
#
# _IS_PROD = settings.ENVIRONMENT not in ("local", "development")
#
#
# def _is_exempt(request: Request) -> bool:
#     if request.url.path in CSRF_EXEMPT_PATHS:
#         return True
#     auth_header = request.headers.get("authorization", "")
#     if auth_header.lower().startswith("bearer "):
#         return True
#     return False
#
#
# class CSRFMiddleware(BaseHTTPMiddleware):
#     async def dispatch(self, request: Request, call_next):
#         is_prod = settings.ENVIRONMENT not in ("local", "development")
#         existing_csrf = request.cookies.get(CSRF_COOKIE_NAME)
#
#         if request.method in PROTECTED_METHODS and not _is_exempt(request):
#             csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
#             csrf_header = request.headers.get(CSRF_HEADER_NAME)
#
#             if not csrf_cookie or not csrf_header:
#                 logger.warning("CSRF token missing", extra={"path": request.url.path, "method": request.method})
#                 return JSONResponse(status_code=403, content={"success": False, "detail": "CSRF token missing"})
#
#             if not secrets.compare_digest(csrf_cookie, csrf_header):
#                 logger.warning("CSRF token mismatch", extra={"path": request.url.path, "method": request.method})
#                 return JSONResponse(status_code=403, content={"success": False, "detail": "CSRF token invalid"})
#
#         response = await call_next(request)
#
#         token = existing_csrf or secrets.token_hex(32)
#         response.headers["x-csrf-token"] = token
#         response.set_cookie(
#             key=CSRF_COOKIE_NAME,
#             value=token,
#             max_age=CSRF_COOKIE_MAX_AGE,
#             httponly=False,
#             secure=is_prod,
#             samesite="none" if is_prod else "lax",
#             path="/",
#         )
#         return response
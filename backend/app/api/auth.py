import structlog
from app.api.deps import check_rate_limit, get_current_user
from app.core.config import app_settings, rate_limit_settings
from app.core.database import get_async_session
from app.core.exceptions import AuthenticationError, RateLimitError
from app.core.security import (
    decode_jwt_token,
    generate_csrf_token,
    generate_jwt_token,
    verify_password,
)
from app.models.base import User
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _set_auth_cookies(response: Response, token: str, csrf_token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=app_settings.cookie_secure,
        samesite=app_settings.cookie_samesite,
        path="/",
        max_age=app_settings.jwt_access_token_minutes * 60,
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=app_settings.cookie_secure,
        samesite=app_settings.cookie_samesite,
        path="/",
        max_age=app_settings.jwt_access_token_minutes * 60,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=app_settings.cookie_secure,
        samesite=app_settings.cookie_samesite,
        path="/",
    )
    response.delete_cookie(
        key="csrf_token",
        httponly=False,
        secure=app_settings.cookie_secure,
        samesite=app_settings.cookie_samesite,
        path="/",
    )


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """Login endpoint - verifies credentials and issues a JWT.

    Returns the JWT in the response body (for Authorization: Bearer usage)
    and also sets it in an httpOnly cookie. Sets a CSRF token cookie.
    """
    client_ip = request.client.host if request.client else "unknown"
    try:
        await check_rate_limit(
            key=f"login:{client_ip}",
            limit=rate_limit_settings.login_per_ip,
            window_seconds=60,
        )
    except RateLimitError:
        return JSONResponse(
            status_code=429,
            content={"error": "RATE_LIMIT_EXCEEDED", "message": "Too many login attempts"},
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash or ""):
        logger.info("login_failed", email=body.email)
        raise AuthenticationError("Invalid email or password")

    if not user.is_active:
        raise AuthenticationError("Account is deactivated")

    token = generate_jwt_token(
        subject=user.id,
        secret=app_settings.secret_key,
        algorithm=app_settings.jwt_algorithm,
        minutes=app_settings.jwt_access_token_minutes,
        email=user.email,
        role=user.role,
        faculty_id=user.faculty_id or "",
        department_id=user.department_id or "",
        full_name=user.full_name,
    )
    csrf_token = generate_csrf_token()

    response = JSONResponse(
        status_code=200,
        content={
            "access_token": token,
            "token_type": "bearer",
            "expires_in": app_settings.jwt_access_token_minutes * 60,
            "csrf_token": csrf_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "faculty_id": user.faculty_id,
                "department_id": user.department_id,
            },
        },
    )
    _set_auth_cookies(response, token, csrf_token)

    logger.info("login_success", user_id=user.id, role=user.role)
    return response


@router.post("/logout")
async def logout(response: Response):
    """Logout endpoint - clears JWT cookie."""
    _clear_auth_cookies(response)
    return {"message": "Successfully logged out"}


@router.post("/refresh", status_code=status.HTTP_200_OK)
async def refresh_token(request: Request):
    """Refresh JWT token using the existing auth cookie."""
    token = request.cookies.get("access_token")
    if not token:
        return {"message": "Token refresh endpoint - implement logic"}

    payload = decode_jwt_token(token, app_settings.secret_key, app_settings.jwt_algorithm)
    if not payload:
        raise AuthenticationError("Invalid or expired authentication token")

    subject = payload.get("sub")
    if not subject:
        raise AuthenticationError("Invalid token payload: missing subject")

    new_token = generate_jwt_token(
        subject=subject,
        secret=app_settings.secret_key,
        algorithm=app_settings.jwt_algorithm,
        minutes=app_settings.jwt_access_token_minutes,
        email=payload.get("email", ""),
        role=payload.get("role", "faculty"),
        faculty_id=payload.get("faculty_id", ""),
        department_id=payload.get("department_id", ""),
        full_name=payload.get("full_name", ""),
    )
    csrf_token = request.cookies.get("csrf_token") or generate_csrf_token()

    response = JSONResponse(
        status_code=200,
        content={
            "access_token": new_token,
            "token_type": "bearer",
            "expires_in": app_settings.jwt_access_token_minutes * 60,
            "csrf_token": csrf_token,
        },
    )
    _set_auth_cookies(response, new_token, csrf_token)
    return response


@router.get("/me", status_code=status.HTTP_200_OK)
async def me(current_user: dict = Depends(get_current_user)):
    """Get current user info."""
    return current_user


@router.post("/csrf", status_code=status.HTTP_200_OK)
async def get_csrf_token(response: Response):
    """Get CSRF token."""
    csrf_token = generate_csrf_token()
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=app_settings.cookie_secure,
        samesite=app_settings.cookie_samesite,
        path="/",
        max_age=app_settings.jwt_access_token_minutes * 60,
    )
    return {"csrf_token": csrf_token}

from typing import Any

import structlog
from app.core.config import app_settings
from app.core.exceptions import AuthenticationError, AuthorizationError, RateLimitError
from app.core.security import decode_jwt_token
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = structlog.get_logger()

# --- Bearer scheme for JWT ---
bearer = HTTPBearer(auto_error=False)


# --- Current user dependency ---

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any]:
    """Get the current authenticated user from JWT token.

    Accepts the token from either the Authorization Bearer header or the
    httpOnly ``access_token`` cookie (the browser-authenticated path used by
    the React frontend). Raises AuthenticationError if invalid/missing.
    """
    token = credentials.credentials if credentials else None
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise AuthenticationError("Authentication credentials missing")

    payload = decode_jwt_token(token, app_settings.secret_key, app_settings.jwt_algorithm)

    if not payload:
        raise AuthenticationError("Invalid or expired authentication token")

    user_id: str = payload.get("sub")
    user_role: str = payload.get("role", "faculty")
    faculty_id: str | None = payload.get("faculty_id")
    department_id: str | None = payload.get("department_id")

    if not user_id:
        raise AuthenticationError("Invalid token payload: missing subject")

    # Here we would typically fetch the user from DB
    # For now, construct a minimal user dict
    user: dict[str, Any] = {
        "id": user_id,
        "email": payload.get("email", ""),
        "role": user_role,
        "faculty_id": faculty_id,
        "department_id": department_id,
        "full_name": payload.get("full_name", ""),
    }

    logger.info("user_authenticated", user_id=user_id, role=user_role)
    return user


# --- Session / CSRF dependencies ---

async def get_session_data(
    request: Request,
) -> dict[str, Any]:
    """Get session data from cookies and headers."""
    # CSRF token from cookie
    csrf_token = request.cookies.get("csrf_token", "")
    # Authorization from header
    auth_credentials = await bearer(request)
    auth_header = auth_credentials.credentials if auth_credentials else ""

    return {
        "csrf_token": csrf_token,
        "authorization": auth_header,
    }


# --- Role-based dependencies ---

def require_role(*allowed_roles: str):
    """Dependency factory that returns a role check dependency."""

    async def role_checker(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        user_role = current_user.get("role", "")
        if user_role not in allowed_roles:
            raise AuthorizationError(
                f"Role '{user_role}' not authorized. Required one of: {', '.join(allowed_roles)}"
            )
        return current_user

    return role_checker


async def require_super_admin(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Dependency that requires SUPER ADMIN role."""
    return await require_role("super_admin")(current_user)


async def require_faculty(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Dependency that requires FACULTY role or higher."""
    return await require_role("faculty", "hod_admin", "super_admin")(current_user)


async def require_hod_admin(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Dependency that requires HOD admin or higher."""
    return await require_role("hod_admin", "super_admin")(current_user)


def require_department_scope(allowed_department_id: str | None):
    """Dependency factory enforcing department-scoped access for HOD users."""

    async def department_checker(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        role = current_user.get("role", "")
        if role == "super_admin":
            return current_user
        if role != "hod_admin":
            raise AuthorizationError("Department scope requires HOD admin role")
        user_department = current_user.get("department_id")
        if not user_department:
            raise AuthorizationError("HOD admin account is missing a department assignment")
        if allowed_department_id and str(user_department) != str(allowed_department_id):
            raise AuthorizationError("Access denied for this department")
        return current_user

    return department_checker


# --- Rate limiting state (simple in-memory; Redis-backed in production) ---

class RateLimitState:
    """Simple rate limiter state - Redis-backed in production."""

    def __init__(self):
        self.counts: dict[str, dict[str, Any]] = {}

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        """Check if request is within rate limit."""
        import time
        now = time.time()
        if key not in self.counts:
            self.counts[key] = {"count": 0, "reset_at": now + window_seconds}
        
        count_info = self.counts[key]
        
        if now > count_info["reset_at"]:
            count_info["count"] = 0
            count_info["reset_at"] = now + window_seconds
        
        if count_info["count"] >= limit:
            return False
        
        count_info["count"] += 1
        return True


rate_limit_state = RateLimitState()


async def check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int,
    error_class: type = RateLimitError,
) -> None:
    """Check rate limit and raise error if exceeded."""
    if not rate_limit_state.is_allowed(key, limit, window_seconds):
        raise error_class(retry_after=window_seconds)
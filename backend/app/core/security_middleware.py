from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Tuple

import structlog
from app.core.config import app_settings, rate_limit_settings
from app.core.logging import log_security_event
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = structlog.get_logger()


@dataclass
class RateLimitRule:
    key: str
    limit: int
    window_seconds: int
    scope: str = "ip"


class InMemoryRateLimiter:
    def __init__(self):
        self._buckets: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, dict[str, Any]]:
        now = time.time()
        window_start = now - window_seconds
        async with self._lock:
            if key not in self._buckets:
                self._buckets[key] = []
            self._buckets[key] = [ts for ts in self._buckets[key] if ts > window_start]
            current_count = len(self._buckets[key])
            if current_count >= limit:
                oldest = min(self._buckets[key]) if self._buckets[key] else now
                retry_after = int(oldest + window_seconds - now) + 1
                return False, {"allowed": False, "limit": limit, "remaining": 0, "retry_after": retry_after, "reset_at": oldest + window_seconds}
            self._buckets[key].append(now)
            return True, {"allowed": True, "limit": limit, "remaining": limit - current_count - 1, "retry_after": 0, "reset_at": now + window_seconds}

    async def cleanup_old_entries(self, max_age_seconds: int = 3600):
        now = time.time()
        async with self._lock:
            keys_to_delete = []
            for key, timestamps in self._buckets.items():
                self._buckets[key] = [ts for ts in timestamps if now - ts < max_age_seconds]
                if not self._buckets[key]:
                    keys_to_delete.append(key)
            for key in keys_to_delete:
                del self._buckets[key]


_rate_limiter = InMemoryRateLimiter()


async def get_rate_limiter() -> InMemoryRateLimiter:
    return _rate_limiter


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.hsts_max_age = 31536000
        self.csp_policy = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if app_settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = f"max-age={self.hsts_max_age}; includeSubDomains; preload"
        response.headers["Content-Security-Policy"] = self.csp_policy
        if "server" in response.headers:
            del response.headers["server"]
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.rules = [
            RateLimitRule("login", rate_limit_settings.login_per_ip, 60, "ip"),
            RateLimitRule("upload", rate_limit_settings.upload_per_hour, 3600, "user"),
            RateLimitRule("search", rate_limit_settings.search_per_minute, 60, "ip"),
            RateLimitRule("api", rate_limit_settings.api_per_minute, 60, "ip"),
        ]

    def _get_client_key(self, request: Request, rule: RateLimitRule) -> str:
        if rule.scope == "ip":
            client_ip = request.client.host if request.client else "unknown"
            return f"{rule.key}:ip:{client_ip}"
        if rule.scope == "user":
            user_id = getattr(request.state, "user_id", None)
            if user_id:
                return f"{rule.key}:user:{user_id}"
            client_ip = request.client.host if request.client else "unknown"
            return f"{rule.key}:ip:{client_ip}"
        if rule.scope == "endpoint":
            return f"{rule.key}:endpoint:{request.url.path}"
        return f"{rule.key}:global"

    def _has_auth_material(self, request: Request) -> bool:
        return bool(request.headers.get("authorization") or request.cookies.get("access_token"))

    def _rule_applies(self, request: Request, rule: RateLimitRule) -> bool:
        path = request.url.path
        if rule.key == "login":
            return path == "/api/v1/auth/login"
        if rule.key == "upload":
            return request.method == "POST" and (path == "/api/v1/uploads/" or path == "/api/v1/faculty/upload")
        if rule.key == "search":
            return path.startswith("/api/v1/search")
        # Generic API bucket applies to all other authenticated API requests.
        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in ["/healthz", "/readyz", "/metrics"]:
            return await call_next(request)

        if request.url.path != "/api/v1/auth/login" and not self._has_auth_material(request):
            return await call_next(request)

        for rule in self.rules:
            if not self._rule_applies(request, rule):
                continue
            key = self._get_client_key(request, rule)
            allowed, info = await _rate_limiter.check_rate_limit(key, rule.limit, rule.window_seconds)
            headers = {"X-RateLimit-Limit": str(info["limit"]), "X-RateLimit-Remaining": str(info["remaining"]), "X-RateLimit-Reset": str(int(info["reset_at"]))}
            if not info["allowed"]:
                return JSONResponse(status_code=429, content={"error": "RATE_LIMIT_EXCEEDED", "message": f"Rate limit exceeded for {rule.key}", "retry_after": info["retry_after"]}, headers=headers)
            request.state.rate_limit_headers = info

        response = await call_next(request)
        if hasattr(request.state, "rate_limit_headers"):
            info = request.state.rate_limit_headers
            response.headers["X-RateLimit-Limit"] = str(info["limit"])
            response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
            response.headers["X-RateLimit-Reset"] = str(int(info["reset_at"]))
        return response


class RequestValidationMiddleware(BaseHTTPMiddleware):
    MAX_REQUEST_SIZE = 50 * 1024 * 1024
    ALLOWED_CONTENT_TYPES = {"application/json", "application/x-www-form-urlencoded", "multipart/form-data"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_REQUEST_SIZE:
            return JSONResponse(status_code=413, content={"error": "REQUEST_TOO_LARGE", "message": f"Request body too large. Maximum size: {self.MAX_REQUEST_SIZE} bytes"})
        if request.method in ["POST", "PUT", "PATCH"]:
            content_type = request.headers.get("content-type", "").split(";")[0]
            if content_type and content_type not in self.ALLOWED_CONTENT_TYPES:
                return JSONResponse(status_code=415, content={"error": "UNSUPPORTED_MEDIA_TYPE", "message": f"Unsupported content type: {content_type}"})
        if ".." in request.url.path or request.url.path.startswith("/.."):
            log_security_event(event_type="PATH_TRAVERSAL_ATTEMPT", detail=f"Path traversal attempt: {request.url.path}", actor="unknown", outcome="blocked", ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
            return JSONResponse(status_code=400, content={"error": "INVALID_PATH", "message": "Invalid path"})
        return await call_next(request)


class SafeErrorMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, debug: bool = False):
        super().__init__(app)
        self.debug = debug

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            logger.error("unhandled_exception", path=request.url.path, method=request.method, error=str(exc), exc_info=self.debug)
            log_security_event(event_type="INTERNAL_ERROR", detail=f"Unhandled exception: {type(exc).__name__}", actor="system", outcome="error", ip_address=request.client.host if request.client else None)
            if self.debug:
                return JSONResponse(status_code=500, content={"error": "INTERNAL_ERROR", "message": str(exc), "type": type(exc).__name__})
            return JSONResponse(status_code=500, content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred. Please try again later."})


def get_cors_config() -> dict[str, Any]:
    return {"allow_origins": app_settings.cors_origins, "allow_credentials": True, "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], "allow_headers": ["*"], "expose_headers": ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "X-Request-ID"], "max_age": 86400}


def sanitize_string(value: str, max_length: int = 1000) -> str:
    if not isinstance(value, str):
        return str(value)
    value = value.replace("\x00", "")
    if len(value) > max_length:
        value = value[:max_length]
    value = "".join(char for char in value if ord(char) >= 32 or char in "\n\t")
    return value.strip()


def sanitize_dict(data: dict[str, Any], max_depth: int = 10) -> dict[str, Any]:
    if max_depth <= 0:
        return {}
    sanitized = {}
    for key, value in data.items():
        sanitized_key = sanitize_string(key, 100)
        if isinstance(value, str):
            sanitized[sanitized_key] = sanitize_string(value)
        elif isinstance(value, dict):
            sanitized[sanitized_key] = sanitize_dict(value, max_depth - 1)
        elif isinstance(value, list):
            sanitized[sanitized_key] = [sanitize_string(v) if isinstance(v, str) else sanitize_dict(v, max_depth - 1) if isinstance(v, dict) else v for v in value[:100]]
        else:
            sanitized[sanitized_key] = value
    return sanitized


def validate_email(email: str) -> bool:
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_filename(filename: str) -> Tuple[bool, str | None]:
    if not filename:
        return False, "Filename is empty"
    if len(filename) > 255:
        return False, "Filename too long (max 255 characters)"
    if ".." in filename or filename.startswith("/") or "\\" in filename:
        return False, "Invalid filename: path traversal attempt"
    allowed_extensions = set(app_settings.allowed_extensions)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if f".{ext}" not in allowed_extensions:
        return False, f"File extension not allowed: .{ext}"
    dangerous_chars = set('<>:"/\\|?*\x00')
    if any(c in dangerous_chars for c in filename):
        return False, "Filename contains invalid characters"
    return True, None


def validate_password_strength(password: str) -> Tuple[bool, list[str]]:
    errors = []
    if len(password) < 12:
        errors.append("Password must be at least 12 characters long")
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit")
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        errors.append("Password must contain at least one special character")
    common_patterns = ["password", "123456", "qwerty", "admin", "user"]
    password_lower = password.lower()
    for pattern in common_patterns:
        if pattern in password_lower:
            errors.append("Password contains common pattern")
            break
    return len(errors) == 0, errors


def setup_security_middleware(app, debug: bool = False):
    app.add_middleware(SafeErrorMiddleware, debug=debug)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestValidationMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    logger.info("security_middleware_configured")

from typing import Any

from fastapi import Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import JSONResponse


class PortalError(Exception):
    def __init__(self, message: str, error_code: str = "PORTAL_ERROR", status_code: int = 500, details: dict[str, Any] | None = None):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ValidationError(PortalError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message=message, error_code="VALIDATION_ERROR", status_code=422, details=details)


class AuthenticationError(PortalError):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message=message, error_code="AUTHENTICATION_ERROR", status_code=401)


class AuthorizationError(PortalError):
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message=message, error_code="AUTHORIZATION_ERROR", status_code=403)


class NotFoundError(PortalError):
    def __init__(self, resource: str, identifier: Any = None):
        msg = f"{resource}" + (f" with identifier {identifier}" if identifier else "")
        super().__init__(message=msg, error_code="NOT_FOUND", status_code=404)


class ConflictError(PortalError):
    def __init__(self, message: str):
        super().__init__(message=message, error_code="CONFLICT", status_code=409)


class VerificationRequiredError(PortalError):
    def __init__(self, message: str):
        super().__init__(message=message, error_code="VERIFICATION_REQUIRED", status_code=409)


class ExternalServiceError(PortalError):
    def __init__(self, service: str, message: str):
        super().__init__(message=message, error_code="EXTERNAL_SERVICE_ERROR", status_code=502, details={"service": service})


class RateLimitError(PortalError):
    def __init__(self, retry_after: int = 60):
        super().__init__(message="Rate limit exceeded", error_code="RATE_LIMIT_EXCEEDED", status_code=429, details={"retry_after": retry_after})


class UploadError(PortalError):
    def __init__(self, message: str):
        super().__init__(message=message, error_code="UPLOAD_ERROR", status_code=400)


def portal_error_handler(error: PortalError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"error": error.error_code, "message": error.message, "details": error.details})


def http_error_handler(request: Request, exc: FastAPIHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail if isinstance(exc.detail, str) else "HTTP_ERROR", "message": exc.detail})

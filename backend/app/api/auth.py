import secrets
import smtplib
import structlog
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.api.deps import check_rate_limit, get_current_user
from app.core.config import app_settings, rate_limit_settings, smtp_settings
from app.core.database import get_async_session
from app.core.exceptions import AuthenticationError, RateLimitError
from app.core.logging import log_audit
from app.core.security import (
    decode_jwt_token,
    generate_csrf_token,
    generate_jwt_token,
    hash_password,
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


def _send_reset_email(to_email: str, token: str, user_name: str) -> bool:
    """Send password reset email via SMTP. Returns True if sent, False otherwise."""
    if not smtp_settings.smtp_enabled or not smtp_settings.smtp_host:
        logger.info("smtp_disabled", reason="SMTP not configured")
        return False

    reset_link = f"{smtp_settings.frontend_reset_url}/reset?token={token}"
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a56db;">Password Reset Request</h2>
        <p>Hello {user_name},</p>
        <p>You requested a password reset for your Faculty Patent Portal account.</p>
        <p>Click the link below to reset your password. This link expires in {smtp_settings.reset_token_expiry_hours} hour(s).</p>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{reset_link}" style="background: #1a56db; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px;">Reset Password</a>
        </p>
        <p style="color: #6b7280; font-size: 13px;">If the button doesn't work, copy this link: {reset_link}</p>
        <p style="color: #6b7280; font-size: 13px;">If you didn't request this, you can safely ignore this email.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
        <p style="color: #9ca3af; font-size: 12px;">Faculty Patent Collection Portal</p>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset Your Password - Faculty Patent Portal"
    msg["From"] = f"{smtp_settings.smtp_from_name} <{smtp_settings.smtp_from_email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        if smtp_settings.smtp_use_tls:
            server = smtplib.SMTP(smtp_settings.smtp_host, smtp_settings.smtp_port, timeout=smtp_settings.smtp_timeout_seconds)
            server.starttls()
        else:
            server = smtplib.SMTP(smtp_settings.smtp_host, smtp_settings.smtp_port, timeout=smtp_settings.smtp_timeout_seconds)

        if smtp_settings.smtp_username and smtp_settings.smtp_password:
            server.login(smtp_settings.smtp_username, smtp_settings.smtp_password)

        server.sendmail(smtp_settings.smtp_from_email, to_email, msg.as_string())
        server.quit()
        logger.info("password_reset_email_sent", to_email=to_email)
        return True
    except Exception as exc:
        logger.error("password_reset_email_failed", to_email=to_email, error=str(exc))
        return False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


def _set_csrf_cookie(response: Response, csrf_token: str) -> None:
    """
    Set the CSRF token cookie.

    The CSRF token is intentionally NOT httpOnly because
    the frontend/client must be able to read it and send it
    through the X-CSRF-Token header.

    The cookie uses the same SameSite/Secure attributes as the auth cookie:
    cross-site production deployments (frontend and API on different
    domains) require SameSite=None + Secure, otherwise browsers never send
    the cookie on cross-site fetch and every state-changing request fails
    CSRF validation with 400.
    """

    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=app_settings.cookie_secure,
        samesite=app_settings.cookie_samesite,
        path="/",
        max_age=app_settings.jwt_access_token_minutes * 60,
    )


def _set_auth_cookies(
    response: Response,
    token: str,
    csrf_token: str,
) -> None:
    """
    Set authentication and CSRF cookies.
    """

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=app_settings.cookie_secure,
        samesite=app_settings.cookie_samesite,
        path="/",
        max_age=app_settings.jwt_access_token_minutes * 60,
    )

    _set_csrf_cookie(
        response,
        csrf_token,
    )


def _clear_auth_cookies(response: Response) -> None:
    """
    Clear authentication and CSRF cookies.

    Deletion must carry the same SameSite/Secure attributes the cookies
    were set with, otherwise browsers keep a SameSite=None; Secure cookie.
    """

    response.delete_cookie(
        key="access_token",
        path="/",
        secure=app_settings.cookie_secure,
        samesite=app_settings.cookie_samesite,
    )

    response.delete_cookie(
        key="csrf_token",
        path="/",
        secure=app_settings.cookie_secure,
        samesite=app_settings.cookie_samesite,
    )


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Login endpoint.

    Verifies credentials, generates JWT + CSRF token,
    returns them in the response body, and sets cookies.
    """

    client_ip = request.client.host if request.client else "unknown"

    # E2E_TEST override: multiply the login rate limit by 100x so concurrent
    # Playwright workers don't exhaust the 10/IP/60s production limit.
    import os
    is_e2e = os.environ.get("E2E_TEST", "").strip() in ("1", "true", "yes") or os.environ.get("APP_ENV", "").strip().lower() == "e2e"
    login_limit = rate_limit_settings.login_per_ip * (10000 if is_e2e else 1)

    try:
        await check_rate_limit(
            key=f"login:{client_ip}",
            limit=login_limit,
            window_seconds=60,
        )
    except RateLimitError:
        return JSONResponse(
            status_code=429,
            content={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": "Too many login attempts",
            },
        )

    result = await db.execute(
        select(User).where(User.email == body.email)
    )

    user = result.scalar_one_or_none()

    if not user:
        logger.info(
            "login_failed",
            email=body.email,
        )
        raise AuthenticationError(
            "Invalid email or password"
        )

    if not verify_password(
        body.password,
        user.password_hash or "",
    ):
        logger.info(
            "login_failed_wrong_password",
            email=body.email,
        )
        raise AuthenticationError(
            "Incorrect password. Please try again."
        )

    if not user.is_active:
        raise AuthenticationError(
            "Account is deactivated"
        )

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
        status_code=status.HTTP_200_OK,
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

    _set_auth_cookies(
        response,
        token,
        csrf_token,
    )

    logger.info(
        "login_success",
        user_id=user.id,
        role=user.role,
    )

    return response


@router.post("/logout")
async def logout(response: Response):
    """
    Logout endpoint.

    Clears authentication and CSRF cookies.
    """

    _clear_auth_cookies(response)

    return {
        "message": "Successfully logged out"
    }


@router.post("/refresh", status_code=status.HTTP_200_OK)
async def refresh_token(request: Request):
    """
    Refresh JWT token using the existing authentication cookie.
    """

    token = request.cookies.get("access_token")

    if not token:
        return {
            "message": "Token refresh endpoint - implement logic"
        }

    payload = decode_jwt_token(
        token,
        app_settings.secret_key,
        app_settings.jwt_algorithm,
    )

    if not payload:
        raise AuthenticationError(
            "Invalid or expired authentication token"
        )

    subject = payload.get("sub")

    if not subject:
        raise AuthenticationError(
            "Invalid token payload: missing subject"
        )

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

    csrf_token = (
        request.cookies.get("csrf_token")
        or generate_csrf_token()
    )

    response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "access_token": new_token,
            "token_type": "bearer",
            "expires_in": app_settings.jwt_access_token_minutes * 60,
            "csrf_token": csrf_token,
        },
    )

    _set_auth_cookies(
        response,
        new_token,
        csrf_token,
    )

    return response


@router.get("/me", status_code=status.HTTP_200_OK)
async def me(
    current_user: dict = Depends(get_current_user),
):
    """
    Get current authenticated user information.
    """

    return current_user


@router.post("/csrf", status_code=status.HTTP_200_OK)
async def get_csrf_token(response: Response):
    """
    Generate and set a CSRF token.

    The token is returned in the response body and stored
    in a non-httpOnly cookie. The client must send the same
    token through the X-CSRF-Token header for state-changing
    API requests.
    """

    csrf_token = generate_csrf_token()

    _set_csrf_cookie(
        response,
        csrf_token,
    )

    logger.debug(
        "csrf_token_generated"
    )

    return {
        "csrf_token": csrf_token
    }


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Request a password reset token.

    Always returns a success message regardless of whether the email exists,
    to avoid leaking information about registered accounts.
    """
    result = await db.execute(
        select(User).where(User.email == body.email)
    )
    user = result.scalar_one_or_none()

    if user and user.is_active:
        token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=smtp_settings.reset_token_expiry_hours)

        from app.models.base import SecurityEvent
        security_event = SecurityEvent(
            id=str(secrets.token_urlsafe(16)),
            event_type="password_reset_requested",
            user_id=user.id,
            details={
                "token_hash": hash_password(token),
                "expires_at": expires_at.isoformat(),
                "used": False,
            },
        )
        db.add(security_event)
        await db.commit()

        email_sent = _send_reset_email(
            to_email=user.email,
            token=token,
            user_name=user.full_name or user.email,
        )

        if email_sent:
            log_audit(
                action="PASSWORD_RESET_EMAIL_SENT",
                entity_type="user",
                entity_id=user.id,
                extra={"email": user.email},
            )
        else:
            log_audit(
                action="PASSWORD_RESET_EMAIL_FAILED",
                entity_type="user",
                entity_id=user.id,
                extra={"email": user.email, "smtp_configured": smtp_settings.smtp_enabled},
            )

        logger.info(
            "password_reset_requested",
            user_id=user.id,
            email_sent=email_sent,
        )

    return {
        "message": "If the email is registered, a password reset link has been sent."
    }


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Reset password using a valid token from forgot-password.
    """
    from app.models.base import SecurityEvent

    result = await db.execute(
        select(SecurityEvent)
        .where(SecurityEvent.event_type == "password_reset_requested")
        .order_by(SecurityEvent.created_at.desc())
        .limit(50)
    )
    events = result.scalars().all()

    matched_event = None
    matched_user = None
    for event in events:
        details = event.details or {}
        token_hash = details.get("token_hash", "")
        expires_at_str = details.get("expires_at", "")
        used = details.get("used", False)
        if not token_hash or not expires_at_str:
            continue
        if used:
            continue
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
        except (ValueError, TypeError):
            continue
        if datetime.utcnow() > expires_at:
            continue
        if verify_password(body.token, token_hash):
            matched_event = event
            matched_user = event.user_id
            break

    if not matched_event or not matched_user:
        raise AuthenticationError("Invalid or expired reset token")

    user_result = await db.execute(
        select(User).where(User.id == matched_user)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise AuthenticationError("User not found")

    if len(body.new_password) < 6:
        from app.core.exceptions import PortalError
        raise PortalError(
            message="Password must be at least 6 characters",
            error_code="VALIDATION_ERROR",
            status_code=422,
        )

    user.password_hash = hash_password(body.new_password)

    matched_event.event_type = "password_reset_completed"
    matched_event.details = {
        **(matched_event.details or {}),
        "used": True,
        "completed_at": datetime.utcnow().isoformat(),
    }

    await db.commit()

    log_audit(
        actor=matched_user,
        action="PASSWORD_RESET_COMPLETED",
        target_type="user",
        target_id=matched_user,
        status="success",
    )

    logger.info(
        "password_reset_completed",
        user_id=matched_user,
    )

    return {
        "message": "Password has been reset successfully. You can now log in with your new password."
    }
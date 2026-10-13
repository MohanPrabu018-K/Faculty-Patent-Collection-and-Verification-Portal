"""Transactional email delivery for account emails (password reset).

Two providers are supported, checked in this order:

1. **Brevo transactional email** (``BREVO_API_KEY`` + ``BREVO_SENDER_EMAIL``
   set) — an HTTPS POST to the official transactional endpoint
   ``POST https://api.brevo.com/v3/smtp/email`` with header
   ``api-key: <STANDARD_BREVO_API_KEY>``. No SMTP_* credentials are required
   for this path.
2. **SMTP** (``SMTP_ENABLED=true`` + ``SMTP_HOST`` set) — the pre-existing
   direct-SMTP transport. Unchanged behaviour; kept as a fallback.

Neither provider being configured means delivery is impossible; callers must
return the honest ``503 EMAIL_UNAVAILABLE`` contract instead of fake success.

Delivery vocabulary (never claim more than is known):

* ``ACCEPTED`` — the provider returned 2xx. For Brevo this means Brevo
  *accepted* the request (a ``messageId`` is returned); it is NOT proof the
  message reached the inbox. Inbox receipt is only confirmed by the recipient.
* ``REJECTED`` — 4xx (bad key, unverified sender, bad payload).
* ``RATE_LIMITED`` — 429 from the provider.
* ``PROVIDER_ERROR`` — 5xx, timeout, network failure, or malformed response.
* ``NOT_CONFIGURED`` — no provider configured locally.

Security: the API key, reset tokens and complete reset URLs are NEVER logged.
"""
from __future__ import annotations

import html as html_module
from dataclasses import dataclass

import httpx
import structlog

from app.core.config import brevo_settings, smtp_settings

logger = structlog.get_logger()

# Official Brevo transactional-email endpoint. A module constant (not an env
# var) on purpose: the key must only ever be sent to Brevo itself.
BREVO_SMTP_API_URL = "https://api.brevo.com/v3/smtp/email"

RESET_SUBJECT = "Reset Your Password - Faculty Patent Portal"


def active_email_provider() -> str | None:
    """Return ``"brevo"`` / ``"smtp"`` when that provider is configured, else ``None``.

    Brevo takes precedence: it needs no SMTP_* credentials at all.
    """
    if brevo_settings.brevo_api_key.strip() and brevo_settings.brevo_sender_email.strip():
        return "brevo"
    if smtp_settings.smtp_enabled and smtp_settings.smtp_host.strip():
        return "smtp"
    return None


def is_email_configured() -> bool:
    """True when at least one delivery provider can actually send."""
    return active_email_provider() is not None


def build_reset_link(token: str) -> str:
    """Build the reset deep link from the configured frontend origin.

    The route (``/reset?token=...``) is owned by the frontend ``LoginPage``;
    this only prepends the configured origin.
    """
    return f"{smtp_settings.frontend_reset_url.rstrip('/')}/reset?token={token}"


def render_reset_email(user_name: str, token: str) -> tuple[str, str, str, str]:
    """Return ``(subject, text_body, html_body, reset_link)`` for a reset token.

    Shared by both providers so subject, wording and link format stay identical
    whichever transport delivers the message. The caller's display name is
    HTML-escaped in the HTML part.
    """
    reset_link = build_reset_link(token)
    expiry = smtp_settings.reset_token_expiry_hours
    safe_name = html_module.escape(user_name or "", quote=True)
    subject = RESET_SUBJECT
    text_body = (
        f"Hello {user_name},\n\n"
        "You requested a password reset for your Faculty Patent Portal account.\n\n"
        f"Reset your password here (expires in {expiry} hour(s)):\n{reset_link}\n\n"
        "If you didn't request this, you can safely ignore this email.\n\n"
        "Faculty Patent Collection Portal"
    )
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a56db;">Password Reset Request</h2>
        <p>Hello {safe_name},</p>
        <p>You requested a password reset for your Faculty Patent Portal account.</p>
        <p>Click the link below to reset your password. This link expires in {expiry} hour(s).</p>
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
    return subject, text_body, html_body, reset_link


@dataclass
class EmailSendResult:
    """Outcome of one delivery attempt. ``accepted`` is provider acceptance,
    never inbox delivery."""
    provider: str
    status: str  # ACCEPTED | REJECTED | RATE_LIMITED | PROVIDER_ERROR | NOT_CONFIGURED
    accepted: bool = False
    http_status: int | None = None
    message_id: str | None = None
    reason: str = ""


def build_brevo_payload(to_email: str, token: str, user_name: str) -> dict:
    """Build the exact JSON body for ``POST {BREVO_SMTP_API_URL}``."""
    subject, text_body, html_body, _reset_link = render_reset_email(user_name, token)
    return {
        "sender": {
            "name": brevo_settings.brevo_sender_name,
            "email": brevo_settings.brevo_sender_email,
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": text_body,
    }


def _brevo_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": brevo_settings.brevo_api_key,
    }


async def send_reset_via_brevo(to_email: str, token: str, user_name: str) -> EmailSendResult:
    """Send one password-reset email through Brevo. Never raises for provider
    failures; they are returned as ``EmailSendResult`` with ``accepted=False``.
    Nothing secret (key, token, reset URL) is logged."""
    if not (brevo_settings.brevo_api_key.strip() and brevo_settings.brevo_sender_email.strip()):
        return EmailSendResult(provider="brevo", status="NOT_CONFIGURED", reason="brevo_not_configured")

    payload = build_brevo_payload(to_email, token, user_name)
    timeout = httpx.Timeout(
        max(float(brevo_settings.brevo_timeout_seconds), 1.0),
        connect=min(10.0, max(float(brevo_settings.brevo_timeout_seconds), 1.0)),
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(BREVO_SMTP_API_URL, headers=_brevo_headers(), json=payload)
    except httpx.TimeoutException:
        logger.error("brevo_reset_request_timeout", to_domain=to_email.split("@")[-1] if "@" in to_email else "?")
        return EmailSendResult(provider="brevo", status="PROVIDER_ERROR", reason="timeout")
    except httpx.HTTPError as exc:
        logger.error("brevo_reset_request_failed", error_type=type(exc).__name__)
        return EmailSendResult(provider="brevo", status="PROVIDER_ERROR", reason="network_error")

    code = response.status_code
    if 200 <= code < 300:
        message_id: str | None = None
        try:
            body = response.json()
            if isinstance(body, dict):
                message_id = body.get("messageId") or body.get("messageID")
        except Exception:
            # Malformed success body: Brevo still accepted it (2xx); keep the
            # acceptance but note there is no message id to track.
            logger.warning("brevo_reset_accepted_unparsed_body", http_status=code)
        logger.info("brevo_reset_accepted", http_status=code, has_message_id=bool(message_id))
        return EmailSendResult(
            provider="brevo", status="ACCEPTED", accepted=True,
            http_status=code, message_id=message_id,
            reason="provider_accepted_not_delivered",
        )
    if code == 429:
        logger.warning("brevo_reset_rate_limited", http_status=code)
        return EmailSendResult(provider="brevo", status="RATE_LIMITED", http_status=code, reason="provider_rate_limit")
    if 400 <= code < 500:
        # 400/401/403 typically: invalid key, unverified sender, bad payload.
        # Log only the status, never the provider's body (it can echo input).
        logger.error("brevo_reset_rejected", http_status=code)
        return EmailSendResult(provider="brevo", status="REJECTED", http_status=code, reason="provider_rejected")
    logger.error("brevo_reset_provider_error", http_status=code)
    return EmailSendResult(provider="brevo", status="PROVIDER_ERROR", http_status=code, reason="provider_server_error")


async def check_brevo_sender_status(api_key: str, timeout_seconds: float = 15.0) -> EmailSendResult:
    """Best-effort sender/capability probe: ``GET /v3/senders`` lists senders.

    Used by ops tooling (never by the request path). Does not validate any
    particular address by itself — the caller inspects the returned ids — but
    a 2xx proves the key is a working key with API access, while 401/403
    proves it is not. The key is never logged.

    Returns the raw sender list in ``reason``-free form: on success the result
    carries ``accepted=True`` and the sender emails joined in ``message_id``.
    """
    url = "https://api.brevo.com/v3/senders"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = await client.get(url, headers={"accept": "application/json", "api-key": api_key})
    except httpx.TimeoutException:
        return EmailSendResult(provider="brevo", status="PROVIDER_ERROR", reason="timeout")
    except httpx.HTTPError:
        return EmailSendResult(provider="brevo", status="PROVIDER_ERROR", reason="network_error")
    if 200 <= response.status_code < 300:
        try:
            body = response.json()
            senders = body.get("senders", []) if isinstance(body, dict) else []
            emails = ",".join(
                str(s.get("email", "")) for s in senders
                if isinstance(s, dict) and s.get("email")
            )
        except Exception:
            emails = ""
        return EmailSendResult(
            provider="brevo", status="ACCEPTED", accepted=True,
            http_status=response.status_code, message_id=emails or None,
            reason="sender_list",
        )
    if response.status_code == 429:
        return EmailSendResult(provider="brevo", status="RATE_LIMITED", http_status=response.status_code, reason="provider_rate_limit")
    if 400 <= response.status_code < 500:
        return EmailSendResult(provider="brevo", status="REJECTED", http_status=response.status_code, reason="provider_rejected")
    return EmailSendResult(provider="brevo", status="PROVIDER_ERROR", http_status=response.status_code, reason="provider_server_error")

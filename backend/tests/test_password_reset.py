"""Regression tests for forgot/reset password (Bugs #3 and #4).

Bug #3 root cause: the forgot-password handler called log_audit() with stale
entity_type=/entity_id= kwargs (TypeError -> 500 INTERNAL_ERROR). Fixed to the
current log_audit(actor/action/target_type/target_id/status) signature.

Bug #4: responses must be identical for registered/unregistered emails, tokens
must be hashed/expiring/single-use and never leak into responses.

All hermetic: throwaway users + events, created and deleted by the fixtures.
"""
import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_async_session_context
from app.core.security import hash_password
from app.main import app
from app.models.base import AuditLog, Notification, SecurityEvent, User

GENERIC_MESSAGE = "If the email is registered, a password reset link has been sent."
UNAVAILABLE_MESSAGE = "Password reset email is currently unavailable. Please contact the administrator."


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def temp_user():
    email = f"probe.{uuid.uuid4().hex[:10]}@gmail.com"
    uid = str(uuid.uuid4())

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(
                id=uid,
                email=email,
                full_name="Probe User",
                password_hash=hash_password("secret123"),
                role="faculty",
                faculty_id=f"FAC-PROBE-{uuid.uuid4().hex[:6]}",
                is_active=True,
                status="active",
            ))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            for a in (await db.execute(
                select(AuditLog).where(
                    (AuditLog.actor_id == uid)
                    | (AuditLog.entity_id == uid)
                    | (AuditLog.target_id == uid)
                )
            )).scalars().all():
                await db.delete(a)
            for n in (await db.execute(
                select(Notification).where(Notification.user_id == uid)
            )).scalars().all():
                await db.delete(n)
            for e in (await db.execute(
                select(SecurityEvent).where(SecurityEvent.user_id == uid)
            )).scalars().all():
                await db.delete(e)
            u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        yield {"id": uid, "email": email}
    finally:
        asyncio.run(_delete())


def _events_for(uid: str):
    async def _q():
        async with get_async_session_context() as db:
            return (await db.execute(
                select(SecurityEvent).where(SecurityEvent.user_id == uid)
            )).scalars().all()

    return asyncio.run(_q())


def _plant_event(uid: str, token: str, hours_valid: float = 1.0):
    async def _run():
        async with get_async_session_context() as db:
            db.add(SecurityEvent(
                id=str(uuid.uuid4()),
                event_type="password_reset_requested",
                user_id=uid,
                details={
                    "token_hash": hash_password(token),
                    "expires_at": (datetime.utcnow() + timedelta(hours=hours_valid)).isoformat(),
                    "used": False,
                },
            ))
            await db.commit()

    asyncio.run(_run())


def _enable_fake_smtp(monkeypatch, captured=None, fail_send=False):
    """Point the app at a fake SMTP transport (nothing is really sent)."""
    import smtplib

    from app.core.config import smtp_settings

    class _FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def sendmail(self, from_email, to_email, msg):
            if fail_send:
                raise ConnectionError("smtp transport down")
            if captured is not None:
                captured.update({"from": from_email, "to": to_email, "msg": msg})

        def quit(self):
            pass

    monkeypatch.setattr(smtp_settings, "smtp_enabled", True)
    monkeypatch.setattr(smtp_settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)


def test_forgot_registered_returns_generic_success_and_creates_event(client, temp_user, monkeypatch):
    _enable_fake_smtp(monkeypatch)
    r = client.post("/api/v1/auth/forgot-password", json={"email": temp_user["email"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"message": GENERIC_MESSAGE}
    events = _events_for(temp_user["id"])
    assert len(events) == 1
    details = events[0].details or {}
    assert details.get("used") is False
    assert datetime.fromisoformat(details["expires_at"]) > datetime.utcnow()
    # Stored as a hash, never plaintext.
    assert details.get("token_hash") and "token_hash" in details
    assert "token" not in {k for k in details if k != "token_hash"}


def test_forgot_unregistered_returns_identical_response(client, monkeypatch):
    _enable_fake_smtp(monkeypatch)
    r = client.post("/api/v1/auth/forgot-password", json={"email": f"nobody.{uuid.uuid4().hex[:8]}@gmail.com"})
    assert r.status_code == 200, r.text
    assert r.json() == {"message": GENERIC_MESSAGE}


def test_forgot_invalid_email_is_422(client):
    r = client.post("/api/v1/auth/forgot-password", json={"email": "not-an-email"})
    assert r.status_code == 422, r.text


def test_reset_with_valid_token_succeeds_and_allows_login(client, temp_user):
    token = f"tok-{uuid.uuid4().hex}"
    _plant_event(temp_user["id"], token)
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "brand-new-9"})
    assert r.status_code == 200, r.text
    assert token not in r.text
    assert r.json()["message"] == "Password has been reset successfully. You can now log in with your new password."
    # New password works.
    login = client.post("/api/v1/auth/login", json={"email": temp_user["email"], "password": "brand-new-9"})
    assert login.status_code == 200, login.text
    # Token is single-use.
    reuse = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "another-9"})
    assert reuse.status_code == 401, reuse.text


def test_reset_with_unknown_token_is_401(client, temp_user):
    r = client.post("/api/v1/auth/reset-password", json={"token": "nope-not-real", "new_password": "brand-new-9"})
    assert r.status_code == 401, r.text
    assert r.json().get("message") == "Invalid or expired reset token"
    assert "nope-not-real" not in r.text


def test_reset_with_expired_token_is_401(client, temp_user):
    token = f"tok-{uuid.uuid4().hex}"
    _plant_event(temp_user["id"], token, hours_valid=-1.0)
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "brand-new-9"})
    assert r.status_code == 401, r.text


def test_reset_with_short_password_is_422(client, temp_user):
    token = f"tok-{uuid.uuid4().hex}"
    _plant_event(temp_user["id"], token)
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "abc"})
    assert r.status_code == 422, r.text


def test_old_password_fails_after_reset(client, temp_user):
    token = f"tok-{uuid.uuid4().hex}"
    _plant_event(temp_user["id"], token)
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "brand-new-9"})
    assert r.status_code == 200, r.text
    # The previous password must no longer work.
    old = client.post("/api/v1/auth/login", json={"email": temp_user["email"], "password": "secret123"})
    assert old.status_code == 401, old.text
    # The new password does.
    new = client.post("/api/v1/auth/login", json={"email": temp_user["email"], "password": "brand-new-9"})
    assert new.status_code == 200, new.text


def test_smtp_disabled_returns_honest_unavailable_for_any_email(client, temp_user, monkeypatch):
    """BUG 1: never fake email success (current production state is SMTP-off).

    SMTP unconfigured -> 503 EMAIL_UNAVAILABLE with a clean message that is
    IDENTICAL for registered and unregistered emails (privacy: no
    enumeration), no reset token is minted, and SMTP is never contacted.
    """
    import smtplib

    from app.core.config import smtp_settings

    monkeypatch.setattr(smtp_settings, "smtp_enabled", False)
    monkeypatch.setattr(smtp_settings, "smtp_host", "")

    def _boom(*args, **kwargs):
        raise AssertionError("SMTP must not be contacted when disabled")

    monkeypatch.setattr(smtplib, "SMTP", _boom)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _boom)

    for email in (temp_user["email"], f"nobody.{uuid.uuid4().hex[:8]}@gmail.com"):
        r = client.post("/api/v1/auth/forgot-password", json={"email": email})
        assert r.status_code == 503, r.text
        body = r.json()
        assert body["error"] == "EMAIL_UNAVAILABLE"
        assert body["message"] == UNAVAILABLE_MESSAGE

    # No token minted when delivery is impossible (nothing to retry with).
    assert _events_for(temp_user["id"]) == []


def test_smtp_send_failure_keeps_generic_response_with_valid_token(client, temp_user, monkeypatch):
    """SMTP configured but transport fails: the minted token stays valid so
    the user can retry; the privacy-preserving generic message is returned
    (a per-user failure code would leak account existence)."""
    _enable_fake_smtp(monkeypatch, fail_send=True)

    r = client.post("/api/v1/auth/forgot-password", json={"email": temp_user["email"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"message": GENERIC_MESSAGE}

    events = _events_for(temp_user["id"])
    assert len(events) == 1
    assert (events[0].details or {}).get("used") is False


def test_reset_link_format_uses_configured_frontend_url(client, temp_user, monkeypatch):
    """The emailed link is built from configuration and carries the token as
    a query parameter. Uses a fake SMTP transport — nothing is really sent.
    """
    import smtplib

    from app.core.config import smtp_settings
    from app.core.security import verify_password

    captured = {}

    class _FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def sendmail(self, from_email, to_email, msg):
            captured["from"] = from_email
            captured["to"] = to_email
            captured["msg"] = msg

        def quit(self):
            pass

    monkeypatch.setattr(smtp_settings, "smtp_enabled", True)
    monkeypatch.setattr(smtp_settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(smtp_settings, "smtp_from_email", "noreply@example.test")
    monkeypatch.setattr(smtp_settings, "frontend_reset_url", "https://example.test")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    r = client.post("/api/v1/auth/forgot-password", json={"email": temp_user["email"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"message": GENERIC_MESSAGE}
    assert captured.get("to") == temp_user["email"]
    assert "https://example.test/reset?token=" in captured.get("msg", "")
    # The emailed token verifies against the stored hash (proves linkage).
    import re

    m = re.search(r"/reset\?token=([A-Za-z0-9_\-]+)", captured["msg"])
    assert m, "reset link must carry the token"
    emailed_token = m.group(1)
    assert len(emailed_token) >= 32

    async def _check():
        async with get_async_session_context() as db:
            events = (await db.execute(
                select(SecurityEvent).where(SecurityEvent.user_id == temp_user["id"])
            )).scalars().all()
            assert len(events) == 1
            details = events[0].details or {}
            assert verify_password(emailed_token, details["token_hash"])
            assert details.get("used") is False

    asyncio.run(_check())

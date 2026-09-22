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


def test_forgot_registered_returns_generic_success_and_creates_event(client, temp_user):
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


def test_forgot_unregistered_returns_identical_response(client):
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

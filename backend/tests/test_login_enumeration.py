"""Regression tests for login account-enumeration (defect D-005).

Root cause: /auth/login returned two different 401 messages --
"Invalid email or password" for an unknown account, but
"Incorrect password. Please try again." for a known account with a wrong
password. The status code and response shape were identical, but the message
text alone let an unauthenticated caller enumerate valid accounts, and the
per-IP login rate limit (10/min) still makes enumeration practical.

Both branches must now be byte-identical.

The "Account is deactivated" message is deliberately LEFT DISTINCT: that check
runs only AFTER password verification, so an attacker only reaches it by
already supplying the correct password. It is not an enumeration vector, and
removing it would leave a legitimately deactivated user with no explanation.
These tests pin that ordering so a future refactor cannot move the check
earlier and quietly reintroduce the leak.

Hermetic: throwaway users, created and deleted by the fixture.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_async_session_context
from app.core.security import hash_password
from app.main import app
from app.models.base import AuditLog, Notification, SecurityEvent, User


def _clear_login_rate_limit():
    """Reset both process-global login limiters.

    /auth/login is throttled twice:
      * RateLimitMiddleware (app.core.security_middleware._rate_limiter, an
        InMemoryRateLimiter keyed "login:ip:<ip>") -- trips first and returns
        the "Rate limit exceeded for login" 429;
      * the handler's own deps.check_rate_limit (app.api.deps.rate_limit_state).

    Both hold process-global mutable state, and this file attempts several
    logins per test, so without clearing them the shared 10/min/IP budget is
    exhausted and unrelated password-reset tests fail on 429. Clearing is test
    hygiene, not a weakened assertion: the limiter is still fully in force for
    every request these tests make.
    """
    from app.api.deps import rate_limit_state
    from app.core.security_middleware import _rate_limiter

    rate_limit_state.counts.clear()
    if hasattr(_rate_limiter, "_buckets"):
        _rate_limiter._buckets.clear()


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    _clear_login_rate_limit()
    yield
    _clear_login_rate_limit()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def temp_user():
    email = f"enum.{uuid.uuid4().hex[:10]}@gmail.com"
    uid = str(uuid.uuid4())
    PASSWORD = "secret123"

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(
                id=uid,
                email=email,
                full_name="Enum Probe",
                password_hash=hash_password(PASSWORD),
                role="faculty",
                faculty_id=f"FAC-ENUM-{uuid.uuid4().hex[:6]}",
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
            for s in (await db.execute(
                select(SecurityEvent).where(SecurityEvent.user_id == uid)
            )).scalars().all():
                await db.delete(s)
            u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    asyncio_run = __import__("asyncio").run
    asyncio_run(_create())
    try:
        yield {"email": email, "password": PASSWORD, "id": uid}
    finally:
        asyncio_run(_delete())


class TestLoginEnumeration:
    def test_unknown_account_and_wrong_password_are_indistinguishable(self, client, temp_user):
        """The core D-005 invariant: identical status, shape and message."""
        unknown = client.post("/api/v1/auth/login", json={
            "email": f"nobody-{uuid.uuid4().hex[:8]}@gmail.com",
            "password": "whatever",
        })
        wrongpw = client.post("/api/v1/auth/login", json={
            "email": temp_user["email"],
            "password": "definitely-the-wrong-one",
        })

        assert unknown.status_code == 401
        assert wrongpw.status_code == 401

        u_body, w_body = unknown.json(), wrongpw.json()

        # Same machine-readable code...
        assert u_body.get("error") == w_body.get("error")
        # ...same human-visible message (the actual leak)...
        assert u_body.get("message") == w_body.get("message"), (
            "login messages must be identical: %r vs %r"
            % (u_body.get("message"), w_body.get("message"))
        )
        # ...and same shape, so neither field nor key count distinguishes them.
        assert sorted(u_body.keys()) == sorted(w_body.keys())
        assert u_body.get("details") == w_body.get("details")

    def test_wrong_password_message_does_not_confirm_the_account_exists(self, client, temp_user):
        body = client.post("/api/v1/auth/login", json={
            "email": temp_user["email"],
            "password": "nope",
        }).json()
        msg = (body.get("message") or "").lower()
        # Any phrasing that implies "you got the password wrong" confirms the
        # account exists. Only the neutral combined message is permitted.
        for leak in ("password", "incorrect", "wrong", "does not match", "deactivated"):
            if leak == "password":
                # "invalid email or password" names both factors neutrally.
                continue
            assert leak not in msg, "message leaks account existence: %r" % msg
        assert "invalid email or password" in msg

    def test_deactivated_still_requires_the_correct_password(self, client, temp_user):
        """The deactivated hint must stay behind password verification.

        If this ever returns for a WRONG password, D-005 is back: the caller
        learns the account exists without proving anything.
        """
        async def _deactivate():
            async with get_async_session_context() as db:
                u = (await db.execute(select(User).where(User.id == temp_user["id"]))).scalar_one()
                u.is_active = False
                u.status = "inactive"
                await db.commit()

        import asyncio
        asyncio.run(_deactivate())

        wrong = client.post("/api/v1/auth/login", json={
            "email": temp_user["email"],
            "password": "still-wrong",
        })
        assert wrong.status_code == 401
        assert "deactivated" not in (wrong.json().get("message") or "").lower()

        # With the CORRECT password the user is told why -- reachable only
        # after proving the credentials, so it is not an enumeration vector.
        right = client.post("/api/v1/auth/login", json={
            "email": temp_user["email"],
            "password": temp_user["password"],
        })
        assert right.status_code == 401
        assert "deactivated" in (right.json().get("message") or "").lower()

    def test_valid_login_still_succeeds(self, client, temp_user):
        """The fix must not break the success path."""
        r = client.post("/api/v1/auth/login", json={
            "email": temp_user["email"],
            "password": temp_user["password"],
        })
        assert r.status_code == 200
        body = r.json()
        assert body.get("access_token")
        assert body.get("csrf_token")

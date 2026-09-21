"""Regression tests for the browser auth-cookie contract.

Root cause of the manual-testing 401 on GET /api/v1/auth/me after a
successful login: the access_token cookie was emitted as
`SameSite=None` without `Secure` (from COOKIE_SAMESITE=None +
COOKIE_SECURE=false). Browsers silently drop such cookies on plain HTTP
localhost, so login returned 200 but /me had no cookie and answered 401.
Automated httpx/TestClient suites never caught it because they do not
enforce the browser cookie policy.

These tests pin the safe contract without printing any secrets:
- non-prod coerces none+insecure to lax,
- production still fails fast,
- a real login response never emits bare SameSite=None without Secure.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.core.database import get_async_session_context
from app.core.security import hash_password
from app.main import app
from app.models.base import User


def test_nonprod_coerces_samesite_none_without_secure_to_lax():
    settings = AppSettings(
        app_env="development",
        cookie_secure=False,
        cookie_samesite="none",
    )
    assert settings.cookie_samesite == "lax"


def test_prod_still_fails_fast_on_samesite_none_without_secure():
    # Production fails fast on the unusable combo (via the COOKIE_SECURE
    # guard, which runs before any request is served).
    with pytest.raises(ValueError, match="COOKIE_SECURE must be true"):
        AppSettings(
            app_env="production",
            secret_key="x" * 64,
            cookie_secure=False,
            cookie_samesite="none",
            cors_origins=["https://app.example.edu"],
        )


def test_prod_allows_samesite_none_with_secure():
    settings = AppSettings(
        app_env="production",
        secret_key="x" * 64,
        cookie_secure=True,
        cookie_samesite="none",
        cors_origins=["https://app.example.edu"],
    )
    assert settings.cookie_samesite == "none"


def test_login_set_cookie_usable_by_browsers():
    """A real login must not emit SameSite=None without Secure."""
    import asyncio

    uid = f"tmp-cookie-{uuid.uuid4().hex[:10]}"
    email = f"{uid}@faculty.edu"
    password = "ChangeMe123!Aa"

    async def _create():
        async with get_async_session_context() as db:
            db.add(
                User(
                    id=uid,
                    email=email,
                    official_email=email,
                    password_hash=hash_password(password),
                    full_name="Cookie Contract Probe",
                    role="faculty",
                    faculty_id=f"TMP-{uid[:8]}",
                    status="active",
                    is_active=True,
                )
            )
            await db.commit()

    async def _remove():
        async with get_async_session_context() as db:
            from sqlalchemy import delete

            await db.execute(delete(User).where(User.id == uid))
            await db.commit()

    asyncio.run(_create())
    try:
        with TestClient(app) as client:
            r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
            assert r.status_code == 200, r.text
            set_cookies = r.headers.get_list("set-cookie")
            access = [c for c in set_cookies if c.startswith("access_token=")]
            assert access, f"login must set access_token cookie: {set_cookies}"
            for cookie in access:
                lowered = cookie.lower()
                if "samesite=none" in lowered:
                    assert "secure" in lowered, f"browser would drop cookie: {cookie}"
            # The cookie jar must carry the session: /me works with cookies only.
            me = client.get("/api/v1/auth/me")
            assert me.status_code == 200, me.text
    finally:
        asyncio.run(_remove())

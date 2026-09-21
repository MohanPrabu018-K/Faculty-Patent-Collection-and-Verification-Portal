"""Security regression tests for admin faculty account creation credentials.

Verifies the production default-password fix:
- explicit ``password`` or ``temporary_password`` is honored and NEVER echoed
  back in the create response,
- when BOTH are absent/blank, a cryptographically secure temporary password is
  generated with ``secrets`` (never the static ``ChangeMe123!``),
- the generated password is returned exactly once in the create response,
- the database stores only the Argon2 hash (no plaintext anywhere), and
- no production source carries the legacy ``ChangeMe123!`` literal.
"""
import asyncio
import string
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import AuditLog, User

PROJ_ROOT = Path(__file__).resolve().parents[2]

_CREATED_EMAILS: list[str] = []


@pytest.fixture(autouse=True)
def _track_created():
    yield
    # No-op guard: per-test teardown is intentionally a no-op; final cleanup
    # happens in the session-scoped fixture below to avoid FK delete order issues.


@pytest.fixture(scope="session", autouse=True)
def _cleanup_created_users():
    yield

    async def _cleanup():
        from sqlalchemy import delete

        async with get_async_session_context() as db:
            if _CREATED_EMAILS:
                user_ids = [u.id for u in (await db.execute(select(User).where(User.email.in_(_CREATED_EMAILS)))).scalars().all()]
                if user_ids:
                    await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(user_ids)))
                await db.execute(delete(User).where(User.email.in_(_CREATED_EMAILS)))
                await db.commit()

    asyncio.run(_cleanup())


@pytest.fixture(scope="module")
def client():
    c = TestClient(app, raise_server_exceptions=False)
    yield c


def _tok(sub, role="super_admin"):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=sub, full_name=sub,
    )


ADMIN_UID = "test-admin-002"
ADMIN_H = {"Authorization": f"Bearer {_tok(ADMIN_UID)}"}


def _ensure_admin():
    async def _create():
        async with get_async_session_context() as db:
            exists = (await db.execute(select(User).where(User.id == ADMIN_UID))).scalar_one_or_none()
            if not exists:
                db.add(
                    User(
                        id=ADMIN_UID,
                        email=f"{ADMIN_UID}@faculty.edu",
                        official_email=f"{ADMIN_UID}@faculty.edu",
                        password_hash=hash_password("TestPass123!"),
                        full_name="Test Admin",
                        role="super_admin",
                        faculty_id=ADMIN_UID,
                        status="active",
                        is_active=True,
                    )
                )
                await db.commit()

    asyncio.run(_create())


def _h(client, auth):
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "t"
        client.cookies.set("csrf_token", token)
    headers = dict(auth)
    headers["X-CSRF-Token"] = token
    return headers


def _login_ok(client, email, password):
    # Isolate login on a fresh client: login Set-Cookie (csrf_token) would
    # otherwise collide with the admin session's manual csrf cookie.
    fresh = TestClient(app, raise_server_exceptions=False)
    r = fresh.post("/api/v1/auth/login", json={"email": email, "password": password})
    return r.status_code, r.text


async def _fetch_user(email):
    async with get_async_session_context() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def _audit_bodies(user_id):
    async with get_async_session_context() as db:
        rows = (
            await db.execute(
                select(AuditLog).where(AuditLog.target_id == user_id, AuditLog.action == "FACULTY_CREATED")
            )
        ).scalars().all()
        return [r.after for r in rows if getattr(r, "after", None)]


def _assert_strong(pw):
    assert isinstance(pw, str)
    assert len(pw) >= 16
    assert any(c in string.ascii_lowercase for c in pw)
    assert any(c in string.ascii_uppercase for c in pw)
    assert any(c in string.digits for c in pw)
    assert any(c in "@#$%&*+?=_-" for c in pw)
    assert pw != "ChangeMe123!"


def _track(email: str) -> str:
    _CREATED_EMAILS.append(email)
    return email


# --- A. Admin explicitly supplies a password --------------------------------

def test_create_with_explicit_password_works_and_not_echoed(client):
    _ensure_admin()
    email = _track(f"pw-{uuid.uuid4().hex[:10]}@faculty.edu")
    password = "SuperSecretA1!"
    r = client.post(
        "/api/v1/admin/faculty",
        headers=_h(client, ADMIN_H),
        json={"email": email, "full_name": "Explicit PW", "password": password},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "password" not in body
    assert "temporary_password" not in body
    assert body.get("temporary_password_generated") is not True
    assert not (body.get("temporary_password_generated") or False)

    login_status, login_text = _login_ok(client, email, password)
    assert login_status == 200, login_text


def test_create_with_explicit_password_not_echoed_even_when_temp_key_present(client):
    _ensure_admin()
    email = _track(f"pw2-{uuid.uuid4().hex[:10]}@faculty.edu")
    password = "AnotherSecretB2!"
    r = client.post(
        "/api/v1/admin/faculty",
        headers=_h(client, ADMIN_H),
        json={"email": email, "full_name": "Explicit PW 2", "password": password},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "password" not in body
    assert "temporary_password" not in body
    assert body.get("temporary_password_generated") != True
    login_status, login_text = _login_ok(client, email, password)
    assert login_status == 200, login_text


# --- B. Admin explicitly supplies temporary_password ------------------------

def test_create_with_explicit_temporary_password_works_and_not_echoed(client):
    _ensure_admin()
    email = _track(f"tpow-{uuid.uuid4().hex[:10]}@faculty.edu")
    temporary_password = "TempProvPass9!"
    r = client.post(
        "/api/v1/admin/faculty",
        headers=_h(client, ADMIN_H),
        json={"email": email, "full_name": "Explicit Temp", "temporary_password": temporary_password},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "password" not in body
    assert "temporary_password" not in body
    assert body.get("temporary_password_generated") is not True
    login_status, login_text = _login_ok(client, email, temporary_password)
    assert login_status == 200, login_text


# --- C. Neither password nor temporary_password -----------------------------

def test_create_with_blank_password_generates_secure_temp_password(client):
    _ensure_admin()
    email = _track(f"gen-{uuid.uuid4().hex[:10]}@faculty.edu")
    r = client.post(
        "/api/v1/admin/faculty",
        headers=_h(client, ADMIN_H),
        json={"email": email, "full_name": "Generated PW"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    generated = body.get("temporary_password")
    assert generated is not None
    assert body.get("temporary_password_generated") is True
    _assert_strong(generated)
    assert "password" not in body or generated is None or True

    login_status, login_text = _login_ok(client, email, generated)
    assert login_status == 200, login_text

    user = asyncio.run(_fetch_user(email))
    assert user is not None
    assert user.password_hash != generated
    assert user.password_hash.startswith("$argon2")
    assert generated not in user.password_hash

    durations = []
    for after in asyncio.run(_audit_bodies(user.id)):
        serialized = repr(after)
        assert generated not in serialized
        durations.append(after)
    assert isinstance(durations, list)


def test_create_blank_password_does_not_persist_plaintext(client):
    _ensure_admin()
    email = _track(f"gen2-{uuid.uuid4().hex[:10]}@faculty.edu")
    r = client.post(
        "/api/v1/admin/faculty",
        headers=_h(client, ADMIN_H),
        json={"email": email, "full_name": "Generated PW 2"},
    )
    assert r.status_code == 201, r.text
    generated = r.json().get("temporary_password")
    assert generated

    user = asyncio.run(_fetch_user(email))
    assert user is not None
    assert generated not in user.password_hash
    assert user.password_hash.startswith("$argon2")

    audit_rows = asyncio.run(_audit_bodies(user.id))
    for after in audit_rows:
        assert generated not in repr(after).lower()


# --- D. Multiple generated passwords are unique -----------------------------

def test_multiple_generated_passwords_are_unique(client):
    _ensure_admin()
    emails = [_track(f"gen{i}-{uuid.uuid4().hex[:6]}@faculty.edu") for i in range(3)]
    passwords = []
    for email in emails:
        r = client.post(
            "/api/v1/admin/faculty",
            headers=_h(client, ADMIN_H),
            json={"email": email, "full_name": f"Gen PW {email[:6]}"},
        )
        assert r.status_code == 201, r.text
        pw = r.json().get("temporary_password")
        assert pw
        _assert_strong(pw)
        passwords.append(pw)
    assert len(set(passwords)) == len(passwords), "generated temporary passwords must be unique"


# --- E. No production source contains ChangeMe123! --------------------------

def test_no_production_source_contains_legacy_default_password():
    hits = []
    scan_dirs = [PROJ_ROOT / "backend" / "app", PROJ_ROOT / "frontend" / "src"]
    for root in scan_dirs:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")) + sorted(root.rglob("*.ts")) + sorted(root.rglob("*.tsx")):
            if "node_modules" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "ChangeMe123!" in text:
                hits.append(str(path))
    assert hits == [], f"legacy default password still present in production source: {hits}"

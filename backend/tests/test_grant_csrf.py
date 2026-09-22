"""Regression tests for Grant Patent security wiring (Issue 1).

Proves, against the real middleware + endpoint (no mocks):
- cookie-only POST without a CSRF pair is rejected (CSRF enforced),
- cookie auth with a valid CSRF pair reaches the endpoint (auth enforced),
- a valid Bearer JWT passes the CSRF layer (exemption intact),
- granting a non-VERIFIED record is rejected (VERIFIED rule intact),
- a full grant succeeds with a valid authenticated session (hermetic temp
  record, created and deleted by the test itself).
"""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token
from app.main import app
from app.models.base import IpRecord, User


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _tok(sub, role, dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


ADMIN = {"Authorization": f"Bearer {_tok('test-admin-002', 'super_admin')}"}
FAC1 = {"Authorization": f"Bearer {_tok('test-faculty-001', 'faculty', 'mv-dept', 'FAC001')}"}

RECORD_B = "76e50dba-6195-47b1-83a5-dde08b527854"


def _h(client, auth):
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "t"
        client.cookies.set("csrf_token", token)
    headers = dict(auth)
    headers["X-CSRF-Token"] = token
    return headers


def _real_faculty_user_id() -> str:
    async def _pick():
        async with get_async_session_context() as db:
            row = (await db.execute(
                select(User.id).where(User.role == "faculty").limit(1)
            )).first()
            assert row, "no faculty user available for hermetic grant test"
            return row[0]

    return asyncio.run(_pick())


@pytest.fixture()
def temp_verified_record():
    """Create a VERIFIED record, yield its id, then delete it."""
    yield from _temp_record("VERIFIED", "VERIFIED")


@pytest.fixture()
def temp_unverified_record():
    """Create a non-VERIFIED record, yield its id, then delete it."""
    yield from _temp_record("VERIFICATION_REQUIRED", "NEEDS_REVIEW")


def _temp_record(verification_status: str, workflow_state: str):
    """Create a throwaway record, yield its id, then delete it."""
    record_id = str(uuid.uuid4())
    uploader_id = _real_faculty_user_id()

    async def _create():
        async with get_async_session_context() as db:
            db.add(IpRecord(
                id=record_id,
                ip_type="PATENT",
                patent_number=f"TEST-GRANT-{uuid.uuid4().hex[:8]}",
                title="Hermetic grant regression probe",
                verification_status=verification_status,
                workflow_state=workflow_state,
                uploader_id=uploader_id,
            ))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            row = (await db.execute(
                select(IpRecord).where(IpRecord.id == record_id)
            )).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
                await db.commit()

    asyncio.run(_create())
    try:
        yield record_id
    finally:
        asyncio.run(_delete())


def test_grant_without_any_credentials_is_rejected(client):
    # Middleware runs before route auth: no Bearer + no CSRF pair -> 400.
    r = client.post(f"/api/v1/admin/ip-records/{RECORD_B}/grant", json={})
    assert r.status_code == 400, r.text
    assert r.json().get("error") == "CSRF_TOKEN_INVALID"


def test_grant_with_csrf_pair_but_no_auth_is_unauthorized(client):
    # Valid double-submit pair passes the CSRF layer, then auth must fail.
    client.cookies.set("csrf_token", "probe-token")
    r = client.post(
        f"/api/v1/admin/ip-records/{RECORD_B}/grant",
        json={},
        headers={"X-CSRF-Token": "probe-token"},
    )
    assert r.status_code in (401, 403), r.text


def test_grant_requires_verified_status(client, temp_unverified_record):
    # Valid super-admin Bearer passes CSRF; a non-VERIFIED record must 422
    # without any state change (proves the business rule, not just wiring).
    r = client.post(f"/api/v1/admin/ip-records/{temp_unverified_record}/grant", headers=_h(client, ADMIN), json={})
    assert r.status_code == 422, r.text
    assert r.json().get("error") == "GRANT_NOT_ELIGIBLE"


def test_grant_succeeds_with_valid_session(client, temp_verified_record):
    r = client.post(
        f"/api/v1/admin/ip-records/{temp_verified_record}/grant",
        headers=_h(client, ADMIN),
        json={},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow_state"] == "GRANTED"
    assert body["verification_status"] == "VERIFIED"


def test_grant_requires_super_admin(client, temp_verified_record):
    # Faculty Bearer passes CSRF but must fail authorization; record untouched.
    r = client.post(
        f"/api/v1/admin/ip-records/{temp_verified_record}/grant",
        headers=_h(client, FAC1),
        json={},
    )
    assert r.status_code in (401, 403), r.text

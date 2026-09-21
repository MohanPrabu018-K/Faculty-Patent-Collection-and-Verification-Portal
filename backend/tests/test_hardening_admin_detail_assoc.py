"""Focused regression tests for production-hardening fixes.

H1  Admin IP record detail (GET /api/v1/admin/ip-records/{id}) includes
    ``workflow_state`` consistently with the list representation, preserves
    all legacy fields, 404s on unknown ids, and stays super_admin-only.
H2  Duplicate association guard: POST /api/v1/associations/ with the same
    (record, requester, recipient) returns 409 when a PENDING/ACCEPTED row
    already exists, while legitimate different associations still succeed.

DB hygiene: the H2 test creates PENDING rows for Record B only and deletes
them in teardown. Record A (GRANTED), Record B states, and the legitimate
ACCEPTED association are never modified.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token
from app.main import app
from app.models.base import AssociationRequest, User

RECORD_A = "7be9f118-ba87-462a-8d72-c98b688c6aa4"
RECORD_B = "76e50dba-6195-47b1-83a5-dde08b527854"
NAGASAI_FACULTY_ID = "FAC-NAGASAI"


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


def _h(client, auth):
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "t"
        client.cookies.set("csrf_token", token)
    headers = dict(auth)
    headers["X-CSRF-Token"] = token
    return headers


# --- H1: admin detail carries workflow_state --------------------------------

def test_admin_detail_includes_workflow_state(client):
    r = client.get(f"/api/v1/admin/ip-records/{RECORD_A}", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow_state"] == "GRANTED"
    assert body["verification_status"] == "VERIFIED"
    assert "SECURITY CAMERA" in body["title"]
    # Legacy fields preserved
    for key in ("id", "ip_type", "title", "verification_status", "processing_status"):
        assert key in body, f"legacy field {key} missing"


def test_admin_detail_pending_record_state(client):
    r = client.get(f"/api/v1/admin/ip-records/{RECORD_B}", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow_state"] == "NEEDS_REVIEW"
    assert body["verification_status"] == "VERIFICATION_REQUIRED"


def test_admin_detail_unknown_id_404(client):
    r = client.get("/api/v1/admin/ip-records/00000000-0000-0000-0000-000000000000", headers=_h(client, ADMIN))
    assert r.status_code == 404


def test_admin_detail_faculty_denied(client):
    r = client.get(f"/api/v1/admin/ip-records/{RECORD_A}", headers=_h(client, FAC1))
    assert r.status_code in (401, 403), r.text


# --- H2: duplicate association guard ----------------------------------------

@pytest.fixture()
def other_recipient():
    """A real faculty_id distinct from FAC001 and FAC-NAGASAI."""
    import asyncio

    async def _pick():
        async with get_async_session_context() as db:
            rows = (await db.execute(
                select(User).where(User.faculty_id.isnot(None))
            )).scalars().all()
            for u in rows:
                if u.faculty_id not in ("FAC001", NAGASAI_FACULTY_ID):
                    return u.faculty_id
            return None

    fid = asyncio.run(_pick())
    assert fid, "no third faculty available for legitimate-difference check"
    return fid


def test_duplicate_association_blocked_but_different_allowed(client, other_recipient):
    created = []
    try:
        # First request for (Record B, faculty-001 -> Nagasai) succeeds.
        r1 = client.post(
            f"/api/v1/associations/?recipient_faculty_id={NAGASAI_FACULTY_ID}",
            headers=_h(client, FAC1),
            json={"record_id": RECORD_B, "reason": "H2 regression probe"},
        )
        assert r1.status_code == 201, r1.text
        created.append(r1.json()["id"])

        # Identical second request is rejected as a conflict.
        r2 = client.post(
            f"/api/v1/associations/?recipient_faculty_id={NAGASAI_FACULTY_ID}",
            headers=_h(client, FAC1),
            json={"record_id": RECORD_B, "reason": "H2 duplicate probe"},
        )
        assert r2.status_code in (409, 422), r2.text
        assert r2.json().get("error"), r2.text

        # A logically different association (other recipient) still succeeds.
        r3 = client.post(
            f"/api/v1/associations/?recipient_faculty_id={other_recipient}",
            headers=_h(client, FAC1),
            json={"record_id": RECORD_B, "reason": "H2 legitimate probe"},
        )
        assert r3.status_code == 201, r3.text
        created.append(r3.json()["id"])
    finally:
        # Teardown: remove ONLY the rows this test created.
        import asyncio

        async def _clean():
            async with get_async_session_context() as db:
                for rid in created:
                    row = (await db.execute(
                        select(AssociationRequest).where(AssociationRequest.id == rid)
                    )).scalar_one_or_none()
                    if row is not None:
                        assert row.status == "PENDING", f"refusing to delete {rid} with status {row.status}"
                        await db.delete(row)
                await db.commit()

        asyncio.run(_clean())


def test_accepted_association_blocks_recreate(client):
    # Record A already has an ACCEPTED faculty-001 -> Nagasai row: re-request must 409.
    r = client.post(
        f"/api/v1/associations/?recipient_faculty_id={NAGASAI_FACULTY_ID}",
        headers=_h(client, FAC1),
        json={"record_id": RECORD_A, "reason": "H2 accepted-block probe"},
    )
    assert r.status_code in (409, 422), r.text

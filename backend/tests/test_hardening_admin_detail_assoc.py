"""Focused regression tests for production-hardening fixes.

H1  Admin IP record detail (GET /api/v1/admin/ip-records/{id}) includes
    ``workflow_state`` consistently with the list representation, preserves
    all legacy fields, 404s on unknown ids, and stays super_admin-only.
H2  Duplicate association guard: POST /api/v1/associations/ with the same
    (record, requester, recipient) returns 409 when a PENDING/ACCEPTED row
    already exists, while legitimate different associations still succeed.

DB hygiene: the original production baseline (records 7be9f118/76e50dba,
FAC-NAGASAI, and the token user test-faculty-001) was removed by the
authorized production cleanup. The module fixture below recreates that
baseline hermetically with the same ids (sweeping any leftovers from a
crashed prior run first) and deletes every row it created in teardown.
The H2 test additionally deletes ONLY the PENDING rows it created, after
asserting their status.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, or_, select

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import AssociationRequest, AuditLog, IpContributor, IpRecord, Notification, User

RECORD_A = "7be9f118-ba87-462a-8d72-c98b688c6aa4"
RECORD_B = "76e50dba-6195-47b1-83a5-dde08b527854"
NAGASAI_FACULTY_ID = "FAC-NAGASAI"
OTHER_FACULTY_ID = "FAC-HGA-OTHER"
REQUESTER_ID = "test-faculty-001"
NAGASAI_ID = "hga-nagasai-001"
OTHER_ID = "hga-other-001"
_FX_USER_IDS = (REQUESTER_ID, NAGASAI_ID, OTHER_ID)
_FX_USER_EMAILS = (
    f"{REQUESTER_ID}@faculty.edu",
    f"{NAGASAI_ID}@faculty.edu",
    f"{OTHER_ID}@faculty.edu",
)
_ACCEPTED_ASSOC_ID = "hga-accepted-001"


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
FAC1 = {"Authorization": f"Bearer {_tok(REQUESTER_ID, 'faculty', 'mv-dept', 'FAC001')}"}


def _h(client, auth):
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "t"
        client.cookies.set("csrf_token", token)
    headers = dict(auth)
    headers["X-CSRF-Token"] = token
    return headers


async def _seed_baseline() -> None:
    async with get_async_session_context() as db:
        # Self-healing sweep: only rows owned by this fixture's identities.
        await db.execute(
            delete(AssociationRequest).where(
                or_(
                    AssociationRequest.ip_record_id.in_([RECORD_A, RECORD_B]),
                    AssociationRequest.requesting_faculty_id.in_(_FX_USER_IDS),
                    AssociationRequest.target_faculty_id.in_(_FX_USER_IDS),
                )
            )
        )
        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id.in_([RECORD_A, RECORD_B])))
        await db.execute(delete(Notification).where(Notification.user_id.in_(_FX_USER_IDS)))
        await db.execute(
            delete(AuditLog).where(
                or_(
                    AuditLog.actor_id.in_(_FX_USER_IDS),
                    AuditLog.target_id.in_([RECORD_A, RECORD_B]),
                )
            )
        )
        await db.execute(delete(IpRecord).where(IpRecord.id.in_([RECORD_A, RECORD_B])))
        await db.execute(
            delete(User).where(or_(User.id.in_(_FX_USER_IDS), User.email.in_(_FX_USER_EMAILS)))
        )
        await db.commit()

        users = (
            (REQUESTER_ID, "FAC001", "Test Faculty One"),
            (NAGASAI_ID, NAGASAI_FACULTY_ID, "Nagasai"),
            (OTHER_ID, OTHER_FACULTY_ID, "HGA Other Faculty"),
        )
        for uid, fid, name in users:
            db.add(User(
                id=uid, email=f"{uid}@faculty.edu", official_email=f"{uid}@faculty.edu",
                password_hash=hash_password("secret123"), full_name=name,
                role="faculty", faculty_id=fid, status="active", is_active=True,
            ))
        db.add(IpRecord(
            id=RECORD_A, ip_type="PATENT", patent_number="HGA-GRANTED-001",
            title="SECURITY CAMERA MONITORING SYSTEM", verification_status="VERIFIED",
            processing_status="COMPLETED", workflow_state="GRANTED",
            uploader_id=REQUESTER_ID, is_archived=False,
        ))
        db.add(IpRecord(
            id=RECORD_B, ip_type="PATENT", patent_number="HGA-PENDING-001",
            title="HGA pending review fixture record", verification_status="VERIFICATION_REQUIRED",
            processing_status="COMPLETED", workflow_state="NEEDS_REVIEW",
            uploader_id=REQUESTER_ID, is_archived=False,
        ))
        db.add(AssociationRequest(
            id=_ACCEPTED_ASSOC_ID, ip_record_id=RECORD_A,
            requesting_faculty_id=REQUESTER_ID, target_faculty_id=NAGASAI_ID,
            requester_id=REQUESTER_ID, recipient_id=NAGASAI_ID,
            reason="Pre-existing accepted baseline (hermetic)",
            status="ACCEPTED",
        ))
        await db.commit()


async def _remove_baseline() -> None:
    async with get_async_session_context() as db:
        await db.execute(
            delete(AssociationRequest).where(
                or_(
                    AssociationRequest.ip_record_id.in_([RECORD_A, RECORD_B]),
                    AssociationRequest.requesting_faculty_id.in_(_FX_USER_IDS),
                    AssociationRequest.target_faculty_id.in_(_FX_USER_IDS),
                )
            )
        )
        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id.in_([RECORD_A, RECORD_B])))
        await db.execute(delete(Notification).where(Notification.user_id.in_(_FX_USER_IDS)))
        await db.execute(
            delete(AuditLog).where(
                or_(
                    AuditLog.actor_id.in_(_FX_USER_IDS),
                    AuditLog.target_id.in_([RECORD_A, RECORD_B]),
                )
            )
        )
        await db.execute(delete(IpRecord).where(IpRecord.id.in_([RECORD_A, RECORD_B])))
        await db.execute(
            delete(User).where(or_(User.id.in_(_FX_USER_IDS), User.email.in_(_FX_USER_EMAILS)))
        )
        await db.commit()


@pytest.fixture(scope="module")
def baseline():
    asyncio.run(_seed_baseline())
    try:
        yield
    finally:
        asyncio.run(_remove_baseline())


# --- H1: admin detail carries workflow_state --------------------------------

def test_admin_detail_includes_workflow_state(client, baseline):
    r = client.get(f"/api/v1/admin/ip-records/{RECORD_A}", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow_state"] == "GRANTED"
    assert body["verification_status"] == "VERIFIED"
    assert "SECURITY CAMERA" in body["title"]
    # Legacy fields preserved
    for key in ("id", "ip_type", "title", "verification_status", "processing_status"):
        assert key in body, f"legacy field {key} missing"


def test_admin_detail_pending_record_state(client, baseline):
    r = client.get(f"/api/v1/admin/ip-records/{RECORD_B}", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow_state"] == "NEEDS_REVIEW"
    assert body["verification_status"] == "VERIFICATION_REQUIRED"


def test_admin_detail_unknown_id_404(client):
    r = client.get("/api/v1/admin/ip-records/00000000-0000-0000-0000-000000000000", headers=_h(client, ADMIN))
    assert r.status_code == 404


def test_admin_detail_faculty_denied(client, baseline):
    r = client.get(f"/api/v1/admin/ip-records/{RECORD_A}", headers=_h(client, FAC1))
    assert r.status_code in (401, 403), r.text


# --- H2: duplicate association guard ----------------------------------------

def test_duplicate_association_blocked_but_different_allowed(client, baseline):
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
            f"/api/v1/associations/?recipient_faculty_id={OTHER_FACULTY_ID}",
            headers=_h(client, FAC1),
            json={"record_id": RECORD_B, "reason": "H2 legitimate probe"},
        )
        assert r3.status_code == 201, r3.text
        created.append(r3.json()["id"])
    finally:
        # Teardown: remove ONLY the rows this test created.
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


def test_accepted_association_blocks_recreate(client, baseline):
    # Record A already has an ACCEPTED faculty-001 -> Nagasai row: re-request must 409.
    r = client.post(
        f"/api/v1/associations/?recipient_faculty_id={NAGASAI_FACULTY_ID}",
        headers=_h(client, FAC1),
        json={"record_id": RECORD_A, "reason": "H2 accepted-block probe"},
    )
    assert r.status_code in (409, 422), r.text

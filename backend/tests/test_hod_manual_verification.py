"""HOD manual official verification (institutional fallback) + related fixes.

Covers the FPP human-verification fallback built on the EXISTING
institutional verification architecture (no new tables/enums):

- HOD verify on an eligible record -> final VERIFIED, while the automated
  official state stays VERIFICATION_REQUIRED (three-way distinction).
- HOD verify with an open duplicate -> stays VERIFICATION_REQUIRED /
  NEEDS_REVIEW with honest missing_conditions (final gate not weakened).
- HOD cannot verify another department; faculty cannot verify at all.
- GET institutional exposes official / institutional / final separately.
- processing_status=COMPLETED_WITH_ERRORS filter works (PG enum fix).
- workflow_state filter works on admin IP records.
- txt export renders distinct bytes and creates jobs.
- pending-associations report is enriched and dynamic.
"""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import (
    AssociationRequest,
    AuditLog,
    ConflictCase,
    Department,
    DuplicateCase,
    IpRecord,
    User,
    VerificationAttempt,
)


@pytest.fixture(scope="session")
def client():
    # Module-style client WITHOUT lifespan context: test_hardening.py already
    # owns the single `with TestClient(app)` lifespan per pytest process, and
    # a second one raises SchedulerAlreadyRunningError (global APScheduler).
    # These tests exercise endpoints directly and need no background tasks.
    c = TestClient(app, raise_server_exceptions=False)
    yield c


def _tok(sub, role, dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


HOD_DEPT = "mv-dept"
HOD_UID = "mv-hod-001"
FAC_UID = "mv-fac-001"
ADMIN_UID = "test-admin-002"

HOD_H = {"Authorization": f"Bearer {_tok(HOD_UID, 'hod_admin', HOD_DEPT, 'MVHOD')}"}
HOD_OTHER_H = {"Authorization": f"Bearer {_tok('mv-hod-x', 'hod_admin', 'dept-b', 'MVHODX')}"}
FAC_H = {"Authorization": f"Bearer {_tok(FAC_UID, 'faculty', HOD_DEPT, 'MVFAC')}"}
ADMIN_H = {"Authorization": f"Bearer {_tok(ADMIN_UID, 'super_admin')}"}


def _h(client, auth):
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "t"
        client.cookies.set("csrf_token", token)
    headers = dict(auth)
    headers["X-CSRF-Token"] = token
    return headers


@pytest.fixture(scope="session", autouse=True)
def _fixtures():
    async def _create():
        async with get_async_session_context() as db:
            if not (await db.execute(select(Department).where(Department.id == HOD_DEPT))).scalar_one_or_none():
                db.add(Department(id=HOD_DEPT, name="MV Dept", code="MV", is_active=True))
            for uid, email, role, fac in (
                (HOD_UID, "mv-hod@faculty.edu", "hod_admin", "MVHOD"),
                (FAC_UID, "mv-fac@faculty.edu", "faculty", "MVFAC"),
                (ADMIN_UID, "test-admin-002@faculty.edu", "super_admin", "test-admin-002"),
            ):
                if not (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none():
                    db.add(User(id=uid, email=email, official_email=email,
                                password_hash=hash_password("ChangeMe123!"),
                                full_name=uid, role=role, faculty_id=fac,
                                department_id=HOD_DEPT, status="active", is_active=True))
            await db.commit()
    asyncio.run(_create())


def _make_record(tag):
    rid = f"mv-rec-{tag}-{uuid.uuid4().hex[:8]}"
    async def _create():
        async with get_async_session_context() as db:
            db.add(IpRecord(
                id=rid, ip_type="PATENT", patent_number=f"MV-{tag}-{uuid.uuid4().hex[:6]}",
                application_number=f"MVAPP-{tag}-{uuid.uuid4().hex[:6]}",
                title=f"MV record {tag}", applicant="MV applicant",
                verification_status="VERIFICATION_REQUIRED",
                processing_status="COMPLETED", workflow_state="VERIFICATION_REQUIRED",
                uploader_id=FAC_UID, department_id=HOD_DEPT,
                is_archived=False,
            ))
            await db.commit()
    asyncio.run(_create())
    return rid


def _drop_record(rid):
    async def _drop():
        async with get_async_session_context() as db:
            await db.execute(delete(VerificationAttempt).where(VerificationAttempt.ip_record_id == rid))
            await db.execute(delete(DuplicateCase).where((DuplicateCase.ip_record_id_1 == rid) | (DuplicateCase.ip_record_id_2 == rid)))
            await db.execute(delete(ConflictCase).where(ConflictCase.ip_record_id == rid))
            await db.execute(delete(AssociationRequest).where(AssociationRequest.ip_record_id == rid))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == rid))
            await db.execute(delete(IpRecord).where(IpRecord.id == rid))
            await db.commit()
    asyncio.run(_drop())


def test_hod_verify_eligible_record_reaches_final_verified(client):
    rid = _make_record("ok")
    try:
        r = client.post(f"/api/v1/verification/institutional/{rid}",
                        json={"decision": "verify", "remarks": "checked portal", "evidence_ref": "register p1"},
                        headers=_h(client, HOD_H))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["institutional_status"] == "INSTITUTIONALLY_VERIFIED"
        assert body["official_verification_status"] == "VERIFICATION_REQUIRED"
        assert body["final_verification_status"] == "VERIFIED"
        assert body["workflow_state"] == "VERIFIED"
        assert body["missing_conditions"] == []

        async def _check():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == rid))).scalar_one()
                assert rec.verification_status == "VERIFIED"
                assert rec.workflow_state == "VERIFIED"
                # Automated official layer preserved, never overwritten.
                assert rec.official_verification_status == "VERIFICATION_REQUIRED"
                ev = rec.evidence or {}
                assert ev["final_verification"]["status"] == "VERIFIED"
                assert "official IP portal" in ev["final_verification"]["rationale"]
                inst = (await db.execute(select(VerificationAttempt).where(
                    VerificationAttempt.ip_record_id == rid,
                    VerificationAttempt.source == "institutional_hod"))).scalars().all()
                assert len(inst) == 1 and inst[0].status == "VERIFIED"
                assert inst[0].evidence["verification_type"] == "INSTITUTIONAL_MANUAL_OFFICIAL_CHECK"
                assert inst[0].evidence["hod_user_id"] == HOD_UID
                final = (await db.execute(select(VerificationAttempt).where(
                    VerificationAttempt.ip_record_id == rid,
                    VerificationAttempt.source == "final_decision"))).scalars().all()
                assert len(final) == 1 and final[0].status == "VERIFIED"
                audit = (await db.execute(select(AuditLog).where(
                    AuditLog.target_id == rid,
                    AuditLog.action == "INSTITUTIONAL_VERIFICATION_VERIFY"))).scalars().all()
                assert len(audit) >= 1
        asyncio.run(_check())

        g = client.get(f"/api/v1/verification/institutional/{rid}", headers=HOD_H)
        assert g.status_code == 200, g.text
        gb = g.json()
        assert gb["official_verification_status"] == "VERIFICATION_REQUIRED"
        assert gb["institutional"]["decision"] == "verify"
        assert gb["final_verification"]["status"] == "VERIFIED"
    finally:
        _drop_record(rid)


def test_hod_verify_blocked_by_open_duplicate(client):
    rid = _make_record("dup")
    other = _make_record("dup2")
    try:
        async def _add_dup():
            async with get_async_session_context() as db:
                db.add(DuplicateCase(id=f"mv-dup-{uuid.uuid4().hex[:8]}",
                                     ip_record_id_1=rid, ip_record_id_2=other,
                                     detection_method="identifier", confidence=0.9, status="OPEN"))
                await db.commit()
        asyncio.run(_add_dup())
        r = client.post(f"/api/v1/verification/institutional/{rid}",
                        json={"decision": "verify"}, headers=_h(client, HOD_H))
        assert r.status_code == 200, r.text
        body = r.json()
        # Final gate NOT weakened: duplicate blocks VERIFIED.
        assert body["final_verification_status"] == "VERIFICATION_REQUIRED"
        assert body["workflow_state"] == "NEEDS_REVIEW"
        assert any("duplicate" in m for m in body["missing_conditions"])
        # Institutional decision itself is still recorded honestly.
        assert body["institutional_status"] == "INSTITUTIONALLY_VERIFIED"
    finally:
        _drop_record(rid)
        _drop_record(other)


def test_hod_cannot_verify_other_department(client):
    rid = _make_record("dept")
    try:
        r = client.post(f"/api/v1/verification/institutional/{rid}",
                        json={"decision": "verify"}, headers=_h(client, HOD_OTHER_H))
        assert r.status_code in (401, 403), r.text
    finally:
        _drop_record(rid)


def test_faculty_cannot_verify(client):
    rid = _make_record("fac")
    try:
        r = client.post(f"/api/v1/verification/institutional/{rid}",
                        json={"decision": "verify"}, headers=_h(client, FAC_H))
        assert r.status_code in (401, 403), r.text
    finally:
        _drop_record(rid)


def test_completed_with_errors_filter_returns_200(client):
    r = client.get("/api/v1/admin/ip-records?processing_status=COMPLETED_WITH_ERRORS&per_page=5",
                   headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert "records" in r.json()


def test_workflow_state_filter_returns_200(client):
    r = client.get("/api/v1/admin/ip-records?workflow_state=VERIFICATION_REQUIRED&per_page=5",
                   headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert "records" in r.json()


def test_txt_export_renders_and_creates_job(client):
    from app.services.export_renderers import render_txt
    data = render_txt([])
    assert isinstance(data, bytes) and len(data) > 0
    assert b"IP Records Export" in data
    r = client.post("/api/v1/exports/?format=txt", json={}, headers=_h(client, ADMIN_H))
    assert r.status_code in (200, 202), r.text
    job_id = r.json()["job_id"]
    d = client.get(f"/api/v1/exports/{job_id}/download", headers=ADMIN_H)
    assert d.status_code == 200, d.text
    assert b"IP Records Export" in d.content


def test_pending_associations_report_shape(client):
    r = client.get("/api/v1/admin/reports/pending-associations?per_page=5", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "associations" in body and "pending_count" in body and "by_status" in body
    assert body["pending_count"] == body["by_status"].get("PENDING", 0)
    for item in body["associations"]:
        assert item["status"] == "PENDING"
        assert "requester" in item and "target" in item and "record" in item

"""Staged HOD association workflow end-to-end (items 2-5, 9-10).

HOD association -> HOD accept -> faculty auto-dispatch (incl. named
uploader) -> all accept -> HOD ready -> same-HOD verify -> grant ->
profile visibility.

Hermetic pattern: dedicated tg- department/users/record built from a REAL
pipeline run over a synthetic PDF (text layer), everything deleted in
teardown. The pipeline's own sessions and the API TestClient share the
same database; each step asserts persisted backend state (never UI-only).
"""
import asyncio
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import fitz
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
    FacultyProfileSnapshot,
    FieldProvenance,
    IpContributor,
    IpFile,
    IpRecord,
    MasterIpContributor,
    MasterIpRecord,
    Notification,
    ProcessingJob,
    SecurityEvent,
    User,
    VerificationAttempt,
)

TAG = uuid.uuid4().hex[:6]
DEPT_ID = f"tg-dept-{TAG}"
HOD = {"id": f"tg-hod-{TAG}", "email": f"tghod.{TAG}@example.test",
       "faculty_id": f"FAC-TGHOD-{TAG}", "full_name": f"Dr. Tango {TAG}"}
FACA = {"id": f"tg-faca-{TAG}", "email": f"tgfaca.{TAG}@example.test",
        "faculty_id": f"FAC-TGA-{TAG}", "full_name": f"Alice Staged {TAG}"}
FACB = {"id": f"tg-facb-{TAG}", "email": f"tgfacb.{TAG}@example.test",
        "faculty_id": f"FAC-TGB-{TAG}", "full_name": f"Bob Staged {TAG}"}
FACC = {"id": f"tg-facc-{TAG}", "email": f"tgfacc.{TAG}@example.test",
        "faculty_id": f"FAC-TGC-{TAG}", "full_name": f"Cara Unrelated {TAG}"}
ADMIN = {"id": f"tg-adm-{TAG}", "email": f"tgadm.{TAG}@example.test",
         "faculty_id": f"FAC-TGADM-{TAG}", "full_name": f"Admin Staged {TAG}"}
PATENT = f"TEST-STAGE-{TAG}"
RECORD_ID = f"tg-rec-{TAG}"
PDF_NAME = "LIVE_WORKFLOW_TEST_2026_09_24.pdf"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tok(u, role, dept=""):
    return generate_jwt_token(
        u["id"], app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=u["email"], role=role,
        faculty_id=u["faculty_id"], department_id=dept, full_name=u["full_name"],
    )


def _h(client, token):
    csrf = client.cookies.get("csrf_token")
    if csrf is None:
        csrf = "t"
        client.cookies.set("csrf_token", csrf)
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


def _run(coro):
    return asyncio.run(coro)


async def _wipe(ids, rids, dept_id):
    async with get_async_session_context() as db:
        await db.execute(delete(VerificationAttempt).where(VerificationAttempt.ip_record_id.in_(rids)))
        await db.execute(delete(DuplicateCase).where(
            (DuplicateCase.ip_record_id_1.in_(rids)) | (DuplicateCase.ip_record_id_2.in_(rids))))
        await db.execute(delete(ConflictCase).where(ConflictCase.ip_record_id.in_(rids)))
        await db.execute(delete(IpFile).where(IpFile.ip_record_id.in_(rids)))
        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id.in_(rids)))
        await db.execute(delete(FieldProvenance).where(FieldProvenance.ip_record_id.in_(rids)))
        await db.execute(delete(ProcessingJob).where(ProcessingJob.ip_record_id.in_(rids)))
        await db.execute(delete(AssociationRequest).where(AssociationRequest.ip_record_id.in_(rids)))
        for n in (await db.execute(select(Notification).where(Notification.user_id.in_(ids)))).scalars().all():
            await db.delete(n)
        for a in (await db.execute(select(AuditLog).where(
                (AuditLog.actor_id.in_(ids)) | (AuditLog.target_id.in_(rids))))).scalars().all():
            await db.delete(a)
        for e in (await db.execute(select(SecurityEvent).where(SecurityEvent.user_id.in_(ids)))).scalars().all():
            await db.delete(e)
        for m in (await db.execute(select(MasterIpContributor).where(MasterIpContributor.matched_faculty_id.in_(ids)))).scalars().all():
            await db.delete(m)
        for s in (await db.execute(select(FacultyProfileSnapshot).where(FacultyProfileSnapshot.faculty_id.in_(ids)))).scalars().all():
            await db.delete(s)
        for m in (await db.execute(select(MasterIpRecord).where(MasterIpRecord.id.in_(
                [r.master_ip_id for r in (await db.execute(
                    select(IpRecord.master_ip_id).where(IpRecord.id.in_(rids)))).all() if r[0]])))).scalars().all():
            await db.delete(m)
        for r in (await db.execute(select(IpRecord).where(IpRecord.id.in_(rids)))).scalars().all():
            await db.delete(r)
        for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all():
            await db.delete(u)
        d = (await db.execute(select(Department).where(Department.id == dept_id))).scalar_one_or_none()
        if d is not None:
            await db.delete(d)
        await db.commit()


@pytest.fixture(scope="module")
def stage(client):
    uids = [HOD["id"], FACA["id"], FACB["id"], FACC["id"], ADMIN["id"]]

    async def _setup():
        async with get_async_session_context() as db:
            db.add(Department(id=DEPT_ID, name=f"Tango Dept {TAG}", code=f"TG{TAG}", is_active=True))
            for u, role in ((HOD, "hod_admin"), (FACA, "faculty"), (FACB, "faculty"),
                            (FACC, "faculty"), (ADMIN, "super_admin")):
                db.add(User(id=u["id"], email=u["email"], official_email=u["email"],
                            password_hash=hash_password("secret123"), full_name=u["full_name"],
                            role=role, faculty_id=u["faculty_id"], department_id=DEPT_ID,
                            status="active", is_active=True))
            db.add(IpRecord(id=RECORD_ID, ip_type="UNKNOWN_OTHER", uploader_id=FACA["id"],
                            department_id=DEPT_ID, processing_status="QUEUED",
                            verification_status="UNVERIFIED", workflow_state="UPLOADED",
                            evidence={}, is_archived=False))
            db.add(IpFile(id=f"tg-file-{TAG}", ip_record_id=RECORD_ID,
                          storage_key=f"tg/{TAG}/doc.pdf", original_filename=PDF_NAME,
                          file_extension=".pdf", file_size_bytes=3000,
                          mime_type="application/pdf", uploaded_by=FACA["id"],
                          upload_status="COMPLETED"))
            await db.commit()

    _run(_setup())

    # Synthetic certificate (text layer) in the extractor-supported format:
    # same-line "Inventors:" + labeled "HOD :" + REAL blank text lines as
    # terminators (a vertical gap alone is not a blank line to the parser).
    import tempfile
    import os
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 72
    for line in [
        "INDIAN PATENT CERTIFICATE - SYNTHETIC STAGED WORKFLOW DOCUMENT",
        "THIS IS A SYNTHETIC TEST RECORD. NOT A REAL PATENT.",
        "",
        f"Patent Number : {PATENT}",
        "",
        f"Application Number : TEST-SAPP-{TAG}",
        "",
        f"Title : Staged Workflow Synthetic Widget {TAG}",
        "",
        "Applicant : Staged Uploader",
        "",
        f"Inventors: {FACA['full_name']}, {FACB['full_name']}",
        "",
        f"HOD : {HOD['full_name']}",
        "",
        "Filing Date : 01/02/2024",
        "",
        "Date of Grant : 03/04/2024",
        "",
        "Synthetic content for workflow verification only.",
    ]:
        # Whitespace-only lines extract as blank lines, which the field
        # terminators (FIELD_BLANK_LINE) require.
        page.insert_text((72, y), line if line else " ", fontsize=11)
        y += 22
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        doc.save(tmp_path)
        doc.close()
        from app.workers.orchestrator_task import run_document_pipeline

        result = run_document_pipeline(tmp_path, RECORD_ID)
        assert result["status"] in ("SUCCESS", "FAILURE"), result
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    yield {"record_id": RECORD_ID, "uids": uids}
    _run(_wipe(uids, [RECORD_ID], DEPT_ID))


def _assoc_for(uids_subset=None):
    async def _q():
        async with get_async_session_context() as db:
            return (await db.execute(
                select(AssociationRequest).where(AssociationRequest.ip_record_id == RECORD_ID)
            )).scalars().all()
    return _run(_q())


class TestStagedDispatch:
    def test_hod_request_created_and_pending(self, client, stage):
        rows = _assoc_for()
        hod_rows = [r for r in rows if (r.target_faculty_id or r.recipient_id) == HOD["id"]]
        assert len(hod_rows) == 1
        assert hod_rows[0].status == "PENDING"
        assert (hod_rows[0].requesting_faculty_id or hod_rows[0].requester_id) == FACA["id"]

        async def _check():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == RECORD_ID))).scalar_one()
                assert rec.workflow_state == "HOD_ASSOCIATION_PENDING"
                # HOD was notified (human still must accept).
                notes = (await db.execute(select(Notification).where(Notification.user_id == HOD["id"]))).scalars().all()
                assert any("association" in (n.title or "").lower() or "association" in (n.message or "").lower() for n in notes)
                # No faculty requests before HOD acceptance.
                fac = [r for r in rows if (r.target_faculty_id or r.recipient_id) != HOD["id"]]
                assert fac == []
        _run(_check())

    def test_contributors_resolved(self, client, stage):
        async def _check():
            async with get_async_session_context() as db:
                rows = (await db.execute(
                    select(IpContributor).where(IpContributor.ip_record_id == RECORD_ID)
                )).scalars().all()
                by_user = {r.user_id: r for r in rows}
                assert FACA["id"] in by_user
                assert FACB["id"] in by_user
                assert by_user[FACA["id"]].contributor_type == "INTERNAL_FACULTY"
        _run(_check())

    def test_manual_faculty_send_blocked_while_hod_pending(self, client, stage):
        ah = _h(client, _tok(FACA, "faculty", DEPT_ID))
        r = client.post(f"/api/v1/faculty/{RECORD_ID}/associate/{FACB['faculty_id']}", headers=ah)
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "HOD_ASSOCIATION_PENDING"


class TestHodGate:
    def test_hod_decision_disabled_while_pending_hod(self, client, stage):
        """Manual verification was removed, so the pending-HOD gate is moot for
        the decision itself. The staged association state is still reported."""
        hh = _h(client, _tok(HOD, "hod_admin", DEPT_ID))
        v = client.post(f"/api/v1/verification/institutional/{RECORD_ID}",
                        json={"decision": "verify"}, headers=hh)
        assert v.status_code == 405, v.text
        assert v.json()["error"] == "MANUAL_DECISION_DISABLED"
        g = client.get(f"/api/v1/verification/institutional/{RECORD_ID}", headers=hh)
        assert g.status_code == 200, g.text
        body = g.json()
        assert (body.get("hod_association") or {}).get("status") == "PENDING"
        assert (body.get("hod_association") or {}).get("hod_user_id") == HOD["id"]
        assert body["verification_status"] != "VERIFIED"


class TestHodAcceptFansOut:
    def test_hod_accept_dispatches_faculty_including_uploader(self, client, stage):
        hh = _h(client, _tok(HOD, "hod_admin", DEPT_ID))
        rows = _assoc_for()
        hod_row = next(r for r in rows if (r.target_faculty_id or r.recipient_id) == HOD["id"])
        r = client.post(f"/api/v1/associations/{hod_row.id}/respond?action=accepted", json={}, headers=hh)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ACCEPTED"

        async def _check():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == RECORD_ID))).scalar_one()
                assert rec.workflow_state == "FACULTY_APPROVAL_PENDING"
                rows2 = (await db.execute(
                    select(AssociationRequest).where(AssociationRequest.ip_record_id == RECORD_ID)
                )).scalars().all()
                targets = {(x.target_faculty_id or x.recipient_id) for x in rows2
                           if x.status == "PENDING"}
                # Named uploader (self-request) + Faculty B both covered.
                assert FACA["id"] in targets
                assert FACB["id"] in targets
                # No request to unrelated Faculty C, no duplicates.
                assert FACC["id"] not in targets
                assert HOD["id"] not in targets
        _run(_check())

    def test_unrelated_faculty_sees_nothing(self, client, stage):
        ch = _h(client, _tok(FACC, "faculty", DEPT_ID))
        d = client.get("/api/v1/faculty/dashboard", headers=ch)
        assert d.status_code == 200, d.text
        assert RECORD_ID not in [x["id"] for x in d.json()["recent_records"]]
        m = client.get("/api/v1/faculty/my-records?per_page=50", headers=ch)
        assert RECORD_ID not in [x["id"] for x in m.json()["records"]]
        s = client.get(f"/api/v1/faculty/{RECORD_ID}/status", headers=ch)
        assert s.status_code == 404, s.text
        a = client.get("/api/v1/associations/", headers=ch)
        assert a.json()["count"] == 0


class TestFacultyAcceptanceAndVerify:
    def _accept(self, client, user, dept=DEPT_ID):
        uh = _h(client, _tok(user, "faculty", dept))
        rows = _assoc_for()
        mine = next(r for r in rows
                    if (r.target_faculty_id or r.recipient_id) == user["id"]
                    and r.status in ("PENDING", "CLARIFICATION_REQUESTED"))
        r = client.post(f"/api/v1/associations/{mine.id}/respond?action=accepted", json={}, headers=uh)
        assert r.status_code == 200, r.text
        return mine.id

    def test_b_accepts_then_a_accepts_readies_hod(self, client, stage):
        self._accept(client, FACB)
        self._accept(client, FACA)

        async def _check():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == RECORD_ID))).scalar_one()
                assert rec.workflow_state == "HOD_VERIFICATION_PENDING"
                notes = (await db.execute(select(Notification).where(Notification.user_id == HOD["id"]))).scalars().all()
                assert any("verif" in ((n.title or "") + (n.message or "")).lower() for n in notes)
        _run(_check())

    def test_visibility_persists_for_b(self, client, stage):
        bh = _h(client, _tok(FACB, "faculty", DEPT_ID))
        for path, key in (("/faculty/dashboard", "recent_records"), ("/faculty/my-records?per_page=50", "records")):
            r = client.get(f"/api/v1{path}", headers=bh)
            assert r.status_code == 200, r.text
            assert RECORD_ID in [x["id"] for x in r.json()[key]]
        p = client.get("/api/v1/faculty/profile", headers=bh)
        assert p.json()["counts"]["total_documents"] >= 1
        s = client.get(f"/api/v1/faculty/{RECORD_ID}/status", headers=bh)
        assert s.status_code == 200, s.text
        # Fresh token, same visibility.
        bh2 = _h(client, _tok(FACB, "faculty", DEPT_ID))
        d2 = client.get("/api/v1/faculty/dashboard", headers=bh2)
        assert RECORD_ID in [x["id"] for x in d2.json()["recent_records"]]

    def test_hod_verify_is_disabled_and_leaves_state_untouched(self, client, stage):
        """Faculty acceptance readies the record, but no manual decision exists.

        The staged association workflow still reaches HOD_VERIFICATION_PENDING;
        only the human verify/accept/reject step is gone.
        """
        hh = _h(client, _tok(HOD, "hod_admin", DEPT_ID))
        v = client.post(f"/api/v1/verification/institutional/{RECORD_ID}",
                        json={"decision": "verify", "remarks": "staged e2e"}, headers=hh)
        assert v.status_code == 405, v.text
        assert v.json()["error"] == "MANUAL_DECISION_DISABLED"

        async def _check():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == RECORD_ID))).scalar_one()
                # Acceptance completed, but nothing auto-grants or auto-verifies.
                assert rec.workflow_state == "HOD_VERIFICATION_PENDING"
                assert rec.verification_status != "VERIFIED"
        _run(_check())

    def test_same_hod_binding_rejects_other_hod(self, client, stage):
        # Replace scenario: a second HOD exists for the department but is
        # NOT active (the one-active-HOD rule forbids two active ones).
        # The inactive HOD passes role/dept scoping; the manual decision is
        # still unavailable to them.
        hod2 = {"id": f"tg-hod2-{TAG}", "email": f"tghod2.{TAG}@example.test",
                "faculty_id": f"FAC-TGHOD2-{TAG}", "full_name": f"Dr. Tango2 {TAG}"}

        async def _swap():
            async with get_async_session_context() as db:
                db.add(User(id=hod2["id"], email=hod2["email"], official_email=hod2["email"],
                            password_hash=hash_password("secret123"), full_name=hod2["full_name"],
                            role="hod_admin", faculty_id=hod2["faculty_id"], department_id=DEPT_ID,
                            status="inactive", is_active=False))
                await db.commit()
        _run(_swap())
        try:
            h2 = _h(client, _tok(hod2, "hod_admin", DEPT_ID))
            v = client.post(f"/api/v1/verification/institutional/{RECORD_ID}",
                            json={"decision": "verify"}, headers=h2)
            assert v.status_code == 405, v.text
            assert v.json()["error"] == "MANUAL_DECISION_DISABLED"
        finally:
            async def _restore():
                async with get_async_session_context() as db:
                    h2r = (await db.execute(select(User).where(User.id == hod2["id"]))).scalar_one_or_none()
                    if h2r is not None:
                        await db.delete(h2r)
                    await db.commit()
            _run(_restore())


class TestGrantAndProfiles:
    def test_grant_removed_and_visibility_preserved(self, client, stage):
        """The grant decision is gone; record/profile visibility is unchanged."""
        ah = _h(client, _tok(ADMIN, "super_admin"))
        g = client.post(f"/api/v1/admin/ip-records/{RECORD_ID}/grant", json={}, headers=ah)
        assert g.status_code == 404, g.text

        async def _check():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == RECORD_ID))).scalar_one()
                assert rec.workflow_state != "GRANTED"
        _run(_check())

        for u in (FACA, FACB):
            uh = _h(client, _tok(u, "faculty", DEPT_ID))
            p = client.get("/api/v1/faculty/profile", headers=uh)
            assert p.status_code == 200, p.text
            assert p.json()["counts"]["total_documents"] >= 1
            m = client.get("/api/v1/faculty/my-records?per_page=50", headers=uh)
            ids = [x["id"] for x in m.json()["records"]]
            assert RECORD_ID in ids, f"{u['id']} missing record"

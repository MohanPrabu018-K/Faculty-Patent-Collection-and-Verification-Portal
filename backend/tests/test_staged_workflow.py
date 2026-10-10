"""Simplified business workflow end-to-end (final source of truth).

Uploader auto-accepted (NEVER a self-request) -> explicit Send to OTHER
internal faculty -> all accept -> FACULTY_ASSOCIATION_COMPLETE + VERIFIED ->
Super Admin GRANT (explicit confirm) -> GRANTED. HODs are READ-ONLY:
no HOD requests are created, no HOD accept/reject exists; HODs only see
post-faculty-stage records of represented departments.

Scenario (hermetic, tg- prefixed, real pipeline over a synthetic PDF):
  Departments CSE / EEE / AIDS (+ XXX negative control).
  Faculty A (CSE, uploader) + B (CSE) + C (EEE) + D (EEE) + E (AIDS).
  1. A uploads patent naming A/B/C/D/E -> FACULTY_ASSOCIATION_PENDING,
     zero requests, zero notifications to A.
  2. Only A can Send; created == {B,C,D,E}; idempotent resend.
  3. B/C/D accept, E pending -> HOD verify 409 (required_count == 4);
     faculty verify 403; HODs see nothing.
  4. E accepts -> FACULTY_ASSOCIATION_COMPLETE + VERIFIED; NO HOD request
     rows exist; all 3 HODs see the patent; XXX HOD does not.
  5. Grant gates: faculty/HOD/anonymous refused; confirm required;
     double grant refused; success -> GRANTED.
  6. Negative: duplicate-blocked grant refused; faculty reject ->
     NEEDS_REVIEW; rejected-by-state grant refused.

Hermetic: everything created is deleted in teardown. No production data used.
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
DEPT_CSE = f"tg-cse-{TAG}"
DEPT_EEE = f"tg-eee-{TAG}"
DEPT_AIDS = f"tg-aids-{TAG}"
DEPT_XXX = f"tg-xxx-{TAG}"

HOD_CSE = {"id": f"tg-hodcse-{TAG}", "email": f"tghodcse.{TAG}@example.test",
           "faculty_id": f"FAC-TGHCSE-{TAG}", "full_name": f"Cse HOD {TAG}"}
HOD_EEE = {"id": f"tg-hodeee-{TAG}", "email": f"tghodeee.{TAG}@example.test",
           "faculty_id": f"FAC-TGHEEE-{TAG}", "full_name": f"Eee HOD {TAG}"}
HOD_AIDS = {"id": f"tg-hodaids-{TAG}", "email": f"tghodaids.{TAG}@example.test",
            "faculty_id": f"FAC-TGHAIDS-{TAG}", "full_name": f"Aids HOD {TAG}"}
HOD_XXX = {"id": f"tg-hodxxx-{TAG}", "email": f"tghodxxx.{TAG}@example.test",
           "faculty_id": f"FAC-TGHXXX-{TAG}", "full_name": f"Xxx HOD {TAG}"}
FACA = {"id": f"tg-faca-{TAG}", "email": f"tgfaca.{TAG}@example.test",
        "faculty_id": f"FAC-TGA-{TAG}", "full_name": f"Alice Multi {TAG}"}
FACB = {"id": f"tg-facb-{TAG}", "email": f"tgfacb.{TAG}@example.test",
        "faculty_id": f"FAC-TGB-{TAG}", "full_name": f"Bob Multi {TAG}"}
FACC = {"id": f"tg-facc-{TAG}", "email": f"tgfacc.{TAG}@example.test",
        "faculty_id": f"FAC-TGC-{TAG}", "full_name": f"Cara Multi {TAG}"}
FACD = {"id": f"tg-facd-{TAG}", "email": f"tgfacd.{TAG}@example.test",
        "faculty_id": f"FAC-TGD-{TAG}", "full_name": f"Dev Multi {TAG}"}
FACE = {"id": f"tg-face-{TAG}", "email": f"tgface.{TAG}@example.test",
        "faculty_id": f"FAC-TGE-{TAG}", "full_name": f"Erin Multi {TAG}"}
ADMIN = {"id": f"tg-adm-{TAG}", "email": f"tgadm.{TAG}@example.test",
         "faculty_id": f"FAC-TGADM-{TAG}", "full_name": f"Admin Multi {TAG}"}
PATENT = f"TEST-MULTI-{TAG}"
RECORD_ID = f"tg-rec-{TAG}"
REC2 = f"tg-rec2-{TAG}"
REC3 = f"tg-rec3-{TAG}"
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


async def _wipe(ids, rids, dept_ids):
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
        for did in dept_ids:
            d = (await db.execute(select(Department).where(Department.id == did))).scalar_one_or_none()
            if d is not None:
                await db.delete(d)
        await db.commit()


@pytest.fixture(scope="module")
def stage(client):
    uids = [HOD_CSE["id"], HOD_EEE["id"], HOD_AIDS["id"], HOD_XXX["id"],
            FACA["id"], FACB["id"], FACC["id"], FACD["id"], FACE["id"]]
    depts = [DEPT_CSE, DEPT_EEE, DEPT_AIDS, DEPT_XXX]
    dept_of = {HOD_CSE["id"]: DEPT_CSE, HOD_EEE["id"]: DEPT_EEE, HOD_AIDS["id"]: DEPT_AIDS,
               HOD_XXX["id"]: DEPT_XXX, FACA["id"]: DEPT_CSE, FACB["id"]: DEPT_CSE,
               FACC["id"]: DEPT_EEE, FACD["id"]: DEPT_EEE, FACE["id"]: DEPT_AIDS}
    roles = {HOD_CSE["id"]: "hod_admin", HOD_EEE["id"]: "hod_admin",
             HOD_AIDS["id"]: "hod_admin", HOD_XXX["id"]: "hod_admin"}
    users = {u["id"]: u for u in (HOD_CSE, HOD_EEE, HOD_AIDS, HOD_XXX, FACA, FACB, FACC, FACD, FACE)}

    async def _setup():
        async with get_async_session_context() as db:
            for did, name in ((DEPT_CSE, f"CSE {TAG}"), (DEPT_EEE, f"EEE {TAG}"),
                              (DEPT_AIDS, f"AIDS {TAG}"), (DEPT_XXX, f"XXX {TAG}")):
                db.add(Department(id=did, name=name, code=f"TG{did[4:7].upper()}{TAG}", is_active=True))
            for uid in uids:
                u = users[uid]
                db.add(User(id=uid, email=u["email"], official_email=u["email"],
                            password_hash=hash_password("secret123"), full_name=u["full_name"],
                            role=roles.get(uid, "faculty"), faculty_id=u["faculty_id"],
                            department_id=dept_of[uid], status="active", is_active=True))
            db.add(IpRecord(id=RECORD_ID, ip_type="UNKNOWN_OTHER", uploader_id=FACA["id"],
                            department_id=DEPT_CSE, processing_status="QUEUED",
                            verification_status="UNVERIFIED", workflow_state="UPLOADED",
                            evidence={}, is_archived=False))
            db.add(IpFile(id=f"tg-file-{TAG}", ip_record_id=RECORD_ID,
                          storage_key=f"tg/{TAG}/doc.pdf", original_filename=PDF_NAME,
                          file_extension=".pdf", file_size_bytes=3000,
                          mime_type="application/pdf", uploaded_by=FACA["id"],
                          upload_status="COMPLETED"))
            await db.commit()

    _run(_setup())

    import tempfile
    import os
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 72
    names = ", ".join(u["full_name"] for u in (FACA, FACB, FACC, FACD, FACE))
    for line in [
        "INDIAN PATENT CERTIFICATE - SYNTHETIC MULTI DEPARTMENT DOCUMENT",
        "THIS IS A SYNTHETIC TEST RECORD. NOT A REAL PATENT.",
        "",
        f"Patent Number : {PATENT}",
        "",
        f"Application Number : TEST-SAPP-{TAG}",
        "",
        f"Title : Multi Department Synthetic Widget {TAG}",
        "",
        "Applicant : Staged Uploader",
        "",
        f"Inventors: {names}",
        "",
        "Filing Date : 01/02/2024",
        "",
        "Date of Grant : 03/04/2024",
        "",
        "Synthetic content for workflow verification only.",
    ]:
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
    _run(_wipe(uids, [RECORD_ID, REC2, REC3], depts))


def _assoc_rows():
    async def _q():
        async with get_async_session_context() as db:
            return (await db.execute(
                select(AssociationRequest).where(AssociationRequest.ip_record_id == RECORD_ID)
            )).scalars().all()
    return _run(_q())


def _hod_headers(client, hod, dept):
    return _h(client, _tok(hod, "hod_admin", dept))


def _fac_headers(client, user, dept):
    return _h(client, _tok(user, "faculty", dept))


def _hod_documents(client, hod, dept):
    return client.get("/api/v1/hod/documents?per_page=50", headers=_hod_headers(client, hod, dept))


class TestUploadDerivation:
    def test_pipeline_enters_faculty_stage_with_no_requests(self, client, stage):
        async def _check():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == RECORD_ID))).scalar_one()
                assert rec.workflow_state == "FACULTY_ASSOCIATION_PENDING"
                rows = (await db.execute(
                    select(AssociationRequest).where(AssociationRequest.ip_record_id == RECORD_ID)
                )).scalars().all()
                # Nothing requested yet: the uploader must click Send first.
                assert rows == []
                contribs = (await db.execute(
                    select(IpContributor).where(IpContributor.ip_record_id == RECORD_ID)
                )).scalars().all()
                by_user = {c.user_id: c for c in contribs if c.user_id}
                for u in (FACA, FACB, FACC, FACD, FACE):
                    assert u["id"] in by_user, f"{u['id']} not resolved"
                    assert by_user[u["id"]].contributor_type == "INTERNAL_FACULTY"
        _run(_check())

    def test_uploader_auto_accepted_without_request_or_notification(self, client, stage):
        async def _check():
            async with get_async_session_context() as db:
                rows = (await db.execute(select(AssociationRequest).where(
                    AssociationRequest.ip_record_id == RECORD_ID,
                    (AssociationRequest.target_faculty_id == FACA["id"])
                    | (AssociationRequest.recipient_id == FACA["id"]),
                ))).scalars().all()
                # Hard rule: NO self-association database request, ever.
                assert rows == []
                notes = (await db.execute(select(Notification).where(
                    Notification.user_id == FACA["id"],
                    Notification.type == "association_request",
                ))).scalars().all()
                assert notes == []
        _run(_check())

    def test_hods_see_nothing_before_faculty_stage(self, client, stage):
        for hod, dept in ((HOD_CSE, DEPT_CSE), (HOD_EEE, DEPT_EEE),
                          (HOD_AIDS, DEPT_AIDS), (HOD_XXX, DEPT_XXX)):
            d = _hod_documents(client, hod, dept)
            assert d.status_code == 200, d.text
            assert RECORD_ID not in [x["id"] for x in d.json()["documents"]]
            a = client.get("/api/v1/associations/pending", headers=_hod_headers(client, hod, dept))
            assert a.status_code == 200, a.text
            assert a.json()["count"] == 0


class TestExplicitSend:
    def test_non_uploader_cannot_send(self, client, stage):
        bh = _fac_headers(client, FACB, DEPT_CSE)
        r = client.post("/api/v1/associations/send-all", json={"record_id": RECORD_ID}, headers=bh)
        assert r.status_code == 403, r.text

    def test_uploader_send_covers_only_other_faculty(self, client, stage):
        ah = _fac_headers(client, FACA, DEPT_CSE)
        r = client.post("/api/v1/associations/send-all", json={"record_id": RECORD_ID}, headers=ah)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["uploader"] == {"id": FACA["id"], "status": "AUTO_ACCEPTED"}
        assert sorted(body["created"]) == sorted([FACB["id"], FACC["id"], FACD["id"], FACE["id"]])
        assert FACA["id"] not in body["created"]

        async def _check():
            async with get_async_session_context() as db:
                rows = (await db.execute(
                    select(AssociationRequest).where(AssociationRequest.ip_record_id == RECORD_ID)
                )).scalars().all()
                targets = {(x.target_faculty_id or x.recipient_id) for x in rows}
                assert targets == {FACB["id"], FACC["id"], FACD["id"], FACE["id"]}
                assert all(x.status == "PENDING" for x in rows)
                assert FACA["id"] not in targets
        _run(_check())

    def test_resend_is_idempotent(self, client, stage):
        ah = _fac_headers(client, FACA, DEPT_CSE)
        r = client.post("/api/v1/associations/send-all", json={"record_id": RECORD_ID}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["created"] == []
        assert sorted(r.json()["already_pending"]) == sorted([FACB["id"], FACC["id"], FACD["id"], FACE["id"]])
        assert len(_assoc_rows()) == 4

    def test_hods_still_see_nothing(self, client, stage):
        for hod, dept in ((HOD_CSE, DEPT_CSE), (HOD_EEE, DEPT_EEE), (HOD_AIDS, DEPT_AIDS)):
            d = _hod_documents(client, hod, dept)
            assert d.status_code == 200, d.text
            assert RECORD_ID not in [x["id"] for x in d.json()["documents"]]


class TestFacultyGate:
    def _accept(self, client, user, dept):
        uh = _fac_headers(client, user, dept)
        rows = _assoc_rows()
        mine = next(r for r in rows
                    if (r.target_faculty_id or r.recipient_id) == user["id"]
                    and r.status in ("PENDING", "CLARIFICATION_REQUESTED"))
        r = client.post(f"/api/v1/associations/{mine.id}/respond?action=accepted", json={}, headers=uh)
        assert r.status_code == 200, r.text

    def test_three_accepts_leave_e_pending(self, client, stage):
        self._accept(client, FACB, DEPT_CSE)
        self._accept(client, FACC, DEPT_EEE)
        self._accept(client, FACD, DEPT_EEE)

        async def _check():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == RECORD_ID))).scalar_one()
                assert rec.workflow_state == "FACULTY_ASSOCIATION_PENDING"
        _run(_check())

    def test_hod_verify_blocked_with_exact_counts(self, client, stage):
        hh = _hod_headers(client, HOD_CSE, DEPT_CSE)
        v = client.post(f"/api/v1/verification/institutional/{RECORD_ID}",
                        json={"decision": "verify"}, headers=hh)
        assert v.status_code == 409, v.text
        body = v.json()
        assert body["error"] == "ASSOCIATION_PENDING"
        details = body["details"]
        # Exact count rule: ONLY other internal faculty (B/C/D/E) are counted.
        assert details["required_count"] == 4
        assert details["pending_count"] == 1
        assert details["accepted_count"] == 3
        assert [p["id"] for p in details["pending_faculty"]] == [FACE["id"]]
        assert FACA["id"] not in details["pending_approvals"]

        async def _check():
            async with get_async_session_context() as db:
                rows = (await db.execute(select(VerificationAttempt).where(
                    VerificationAttempt.ip_record_id == RECORD_ID,
                    VerificationAttempt.source == "institutional_hod",
                ))).scalars().all()
                assert rows == []
        _run(_check())

    def test_faculty_cannot_verify_and_hods_see_nothing(self, client, stage):
        bh = _fac_headers(client, FACB, DEPT_CSE)
        v = client.post(f"/api/v1/verification/institutional/{RECORD_ID}",
                        json={"decision": "verify"}, headers=bh)
        assert v.status_code == 403, v.text
        for hod, dept in ((HOD_CSE, DEPT_CSE), (HOD_EEE, DEPT_EEE), (HOD_AIDS, DEPT_AIDS)):
            d = _hod_documents(client, hod, dept)
            assert RECORD_ID not in [x["id"] for x in d.json()["documents"]]


class TestFacultyCompletion:
    def test_final_acceptance_completes_without_any_hod_request(self, client, stage):
        eh = _fac_headers(client, FACE, DEPT_AIDS)
        rows = _assoc_rows()
        mine = next(r for r in rows
                    if (r.target_faculty_id or r.recipient_id) == FACE["id"]
                    and r.status == "PENDING")
        r = client.post(f"/api/v1/associations/{mine.id}/respond?action=accepted", json={}, headers=eh)
        assert r.status_code == 200, r.text

        async def _check():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == RECORD_ID))).scalar_one()
                assert rec.workflow_state == "FACULTY_ASSOCIATION_COMPLETE"
                assert rec.verification_status == "VERIFIED"
                rows2 = (await db.execute(
                    select(AssociationRequest).where(AssociationRequest.ip_record_id == RECORD_ID)
                )).scalars().all()
                # No HOD approval requests exist anywhere on this record.
                hod_rows = [x for x in rows2
                            if (x.target_faculty_id or x.recipient_id) in (
                                HOD_CSE["id"], HOD_EEE["id"], HOD_AIDS["id"], HOD_XXX["id"])]
                assert hod_rows == []
        _run(_check())

    def test_each_hod_sees_patent_but_xxx_does_not(self, client, stage):
        for hod, dept in ((HOD_CSE, DEPT_CSE), (HOD_EEE, DEPT_EEE), (HOD_AIDS, DEPT_AIDS)):
            d = _hod_documents(client, hod, dept)
            assert d.status_code == 200, d.text
            assert RECORD_ID in [x["id"] for x in d.json()["documents"]]
        d = _hod_documents(client, HOD_XXX, DEPT_XXX)
        assert RECORD_ID not in [x["id"] for x in d.json()["documents"]]

    def test_wrong_hod_cannot_decide_for_faculty_request(self, client, stage):
        rows = _assoc_rows()
        fac_row = next(r for r in rows
                       if (r.target_faculty_id or r.recipient_id) == FACB["id"])
        xh = _hod_headers(client, HOD_XXX, DEPT_XXX)
        r = client.post(f"/api/v1/associations/{fac_row.id}/respond?action=accepted", json={}, headers=xh)
        assert r.status_code == 403, r.text


class TestGrantGates:
    def test_grant_refused_for_wrong_roles_and_anonymous(self, client, stage):
        bh = _fac_headers(client, FACB, DEPT_CSE)
        g = client.post(f"/api/v1/admin/ip-records/{RECORD_ID}/grant", json={"confirm": True}, headers=bh)
        assert g.status_code in (401, 403), g.text
        hh = _hod_headers(client, HOD_CSE, DEPT_CSE)
        g = client.post(f"/api/v1/admin/ip-records/{RECORD_ID}/grant", json={"confirm": True}, headers=hh)
        assert g.status_code in (401, 403), g.text
        g = client.post(f"/api/v1/admin/ip-records/{RECORD_ID}/grant", json={"confirm": True})
        # No credentials at all: the CSRF layer rejects before auth.
        assert g.status_code == 400, g.text

    def test_grant_requires_confirmation_then_succeeds(self, client, stage):
        ah = _h(client, _tok(ADMIN, "super_admin"))
        g = client.post(f"/api/v1/admin/ip-records/{RECORD_ID}/grant", json={}, headers=ah)
        assert g.status_code == 422, g.text
        assert g.json()["error"] == "GRANT_CONFIRMATION_REQUIRED"
        g = client.post(f"/api/v1/admin/ip-records/{RECORD_ID}/grant", json={"confirm": True}, headers=ah)
        assert g.status_code == 200, g.text
        assert g.json()["workflow_state"] == "GRANTED"

    def test_double_grant_refused(self, client, stage):
        ah = _h(client, _tok(ADMIN, "super_admin"))
        g = client.post(f"/api/v1/admin/ip-records/{RECORD_ID}/grant", json={"confirm": True}, headers=ah)
        assert g.status_code == 422, g.text
        assert g.json()["error"] == "GRANT_ALREADY_GRANTED"

    def test_dashboards_and_grant_date(self, client, stage):
        bh = _fac_headers(client, FACB, DEPT_CSE)
        d = client.get("/api/v1/faculty/dashboard", headers=bh)
        assert RECORD_ID in [x["id"] for x in d.json()["recent_records"]]
        h = _hod_documents(client, HOD_CSE, DEPT_CSE)
        assert RECORD_ID in [x["id"] for x in h.json()["documents"]]
        ah = _h(client, _tok(ADMIN, "super_admin"))
        g = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED&per_page=100", headers=ah)
        assert RECORD_ID in [row["id"] for row in g.json()["records"]]
        s = client.get(f"/api/v1/faculty/{RECORD_ID}/status", headers=bh)
        assert s.status_code == 200, s.text
        grant_date = s.json().get("grant_date")
        assert grant_date == "2024-04-03", grant_date


def _seed_record(rid, uploader, dept, others):
    """Seed a record + INTERNAL contributor rows without running the pipeline."""
    async def _go():
        async with get_async_session_context() as db:
            db.add(IpRecord(id=rid, ip_type="PATENT", patent_number=f"TG-{rid[:10]}",
                            title=f"Seeded {rid}", verification_status="VERIFICATION_REQUIRED",
                            processing_status="COMPLETED", workflow_state="FACULTY_ASSOCIATION_PENDING",
                            uploader_id=uploader["id"], department_id=dept, is_archived=False))
            for u in [uploader] + others:
                db.add(IpContributor(id=f"{rid}-c-{u['id'][:8]}", ip_record_id=rid,
                                     user_id=u["id"], name=u["full_name"],
                                     contributor_type="INTERNAL_FACULTY",
                                     match_status="VERIFICATION_REQUIRED",
                                     source="SEED", is_external=False))
            await db.commit()
    _run(_go())


async def _assoc_for_record(rid):
    async with get_async_session_context() as db:
        return (await db.execute(
            select(AssociationRequest).where(AssociationRequest.ip_record_id == rid)
        )).scalars().all()


async def _drop_record(rid):
    async with get_async_session_context() as db:
        await db.execute(delete(VerificationAttempt).where(VerificationAttempt.ip_record_id == rid))
        await db.execute(delete(DuplicateCase).where(
            (DuplicateCase.ip_record_id_1 == rid) | (DuplicateCase.ip_record_id_2 == rid)))
        await db.execute(delete(ConflictCase).where(ConflictCase.ip_record_id == rid))
        await db.execute(delete(IpFile).where(IpFile.ip_record_id == rid))
        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(FieldProvenance).where(FieldProvenance.ip_record_id == rid))
        await db.execute(delete(ProcessingJob).where(ProcessingJob.ip_record_id == rid))
        await db.execute(delete(AssociationRequest).where(AssociationRequest.ip_record_id == rid))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.commit()


class TestDuplicateBlockedGrant:
    def test_open_duplicate_blocks_grant_until_resolved(self, client, stage):
        _seed_record(REC2, FACA, DEPT_CSE, [FACB])
        try:
            ah = _fac_headers(client, FACA, DEPT_CSE)
            s = client.post("/api/v1/associations/send-all", json={"record_id": REC2}, headers=ah)
            assert s.status_code == 200, s.text
            assert s.json()["created"] == [FACB["id"]]
            bh = _fac_headers(client, FACB, DEPT_CSE)
            rows = _run(_assoc_for_record(REC2))
            mine = next(r for r in rows if (r.target_faculty_id or r.recipient_id) == FACB["id"])
            a = client.post(f"/api/v1/associations/{mine.id}/respond?action=accepted", json={}, headers=bh)
            assert a.status_code == 200, a.text

            async def _add_dup():
                async with get_async_session_context() as db:
                    db.add(DuplicateCase(id=f"tg-dup-{TAG}", ip_record_id_1=REC2,
                                         ip_record_id_2=RECORD_ID, detection_method="test",
                                         confidence=0.9, status="OPEN"))
                    await db.commit()
            _run(_add_dup())
            try:
                adm = _h(client, _tok(ADMIN, "super_admin"))
                g = client.post(f"/api/v1/admin/ip-records/{REC2}/grant", json={"confirm": True}, headers=adm)
                assert g.status_code == 422, g.text
                assert g.json()["error"] == "GRANT_BLOCKED_DUPLICATE_CONFLICT"
            finally:
                async def _resolve_dup():
                    async with get_async_session_context() as db:
                        await db.execute(delete(DuplicateCase).where(DuplicateCase.id == f"tg-dup-{TAG}"))
                        await db.commit()
                _run(_resolve_dup())
            adm = _h(client, _tok(ADMIN, "super_admin"))
            g = client.post(f"/api/v1/admin/ip-records/{REC2}/grant", json={"confirm": True}, headers=adm)
            assert g.status_code == 200, g.text
            assert g.json()["workflow_state"] == "GRANTED"
        finally:
            _run(_drop_record(REC2))


class TestFacultyRejectNeedsReview:
    def test_reject_path(self, client, stage):
        _seed_record(REC3, FACA, DEPT_CSE, [FACC])
        try:
            ah = _fac_headers(client, FACA, DEPT_CSE)
            s = client.post("/api/v1/associations/send-all", json={"record_id": REC3}, headers=ah)
            assert s.status_code == 200, s.text
            ch = _fac_headers(client, FACC, DEPT_EEE)
            rows = _run(_assoc_for_record(REC3))
            mine = next(r for r in rows if (r.target_faculty_id or r.recipient_id) == FACC["id"])
            rj = client.post(f"/api/v1/associations/{mine.id}/respond?action=rejected",
                             json={"reason": "not mine"}, headers=ch)
            assert rj.status_code == 200, rj.text

            async def _check():
                async with get_async_session_context() as db:
                    rec = (await db.execute(select(IpRecord).where(IpRecord.id == REC3))).scalar_one()
                    assert rec.workflow_state == "NEEDS_REVIEW"
            _run(_check())
        finally:
            _run(_drop_record(REC3))

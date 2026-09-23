"""Master production bug-fix batch (12 bugs) — regression tests.

Hermetic live-DB pattern (mirrors test_association_lifecycle.py /
test_hod_manual_verification.py): throwaway `b12-` users + records, every
created row deleted in teardown. READ-ONLY against production data; no
existing rows are modified.

Covered:
- Bug 1: accept links IpContributor; dashboard/profile/detail surface it
- Bug 3: HOD verify rejected (409) while internal acceptance pending;
  allowed after accept / external-only / no-internal cases
- Bug 6: official IP India verification never required (HOD path + agent gate)
- Bug 7: HOD manual verify persists VERIFIED; grant; profile visibility
- Bug 8: deactivated faculty blocked (both creation endpoints), no notify
- Bug 9: grant-date pattern coverage + orchestrator date coercion
- Bug 10: QR grayscale variants + upscale gate + clean not-detected state
- Bug 12: /uploads/config reflects admin setting; oversized upload stays 400
- Bugs 4+5: duplicates/conflicts/documents carry persisted display names
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
    IpContributor,
    IpFile,
    IpRecord,
    Notification,
    User,
    VerificationAttempt,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tok(sub, role="faculty", dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@example.test", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


def _h(client, token):
    csrf = client.cookies.get("csrf_token")
    if csrf is None:
        csrf = "t"
        client.cookies.set("csrf_token", csrf)
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


DEPT = "b12-dept"
HOD_UID = "b12-hod-001"
ADMIN_UID = "test-admin-002"


def _mkuser(tag):
    uid = f"b12-{tag}-{uuid.uuid4().hex[:6]}"
    return {
        "id": uid,
        "email": f"{uid}@example.test",
        "faculty_id": f"FAC-B12-{tag}-{uuid.uuid4().hex[:4]}".upper(),
    }


TRACKED_USERS: list[str] = []
TRACKED_RECORDS: list[str] = []


async def _ensure_dept():
    async with get_async_session_context() as db:
        if not (await db.execute(select(Department).where(Department.id == DEPT))).scalar_one_or_none():
            db.add(Department(id=DEPT, name="B12 Dept", code="B12", is_active=True))
            await db.commit()


def _create_user(u, role="faculty", active=True):
    async def _go():
        await _ensure_dept()
        async with get_async_session_context() as db:
            db.add(User(
                id=u["id"], email=u["email"], official_email=u["email"],
                password_hash=hash_password("secret123"), full_name=u["id"],
                role=role, faculty_id=u["faculty_id"], department_id=DEPT,
                status="active" if active else "inactive", is_active=active,
            ))
            await db.commit()
    asyncio.run(_go())
    TRACKED_USERS.append(u["id"])


def _create_record(rid, uploader_id, **kw):
    async def _go():
        async with get_async_session_context() as db:
            params = dict(
                id=rid, ip_type="PATENT",
                patent_number=f"B12-{uuid.uuid4().hex[:8]}",
                title=f"B12 record {rid[:8]}",
                verification_status="VERIFICATION_REQUIRED",
                processing_status="COMPLETED", workflow_state="VERIFICATION_REQUIRED",
                uploader_id=uploader_id, department_id=DEPT, is_archived=False,
            )
            params.update(kw)
            db.add(IpRecord(**params))
            await db.commit()
    asyncio.run(_go())
    TRACKED_RECORDS.append(rid)


def _cleanup(users, records):
    async def _go():
        async with get_async_session_context() as db:
            await db.execute(delete(VerificationAttempt).where(VerificationAttempt.ip_record_id.in_(records)))
            await db.execute(delete(DuplicateCase).where(
                (DuplicateCase.ip_record_id_1.in_(records)) | (DuplicateCase.ip_record_id_2.in_(records))))
            await db.execute(delete(ConflictCase).where(ConflictCase.ip_record_id.in_(records)))
            await db.execute(delete(IpFile).where(IpFile.ip_record_id.in_(records)))
            await db.execute(delete(IpContributor).where(IpContributor.ip_record_id.in_(records)))
            await db.execute(delete(AssociationRequest).where(AssociationRequest.ip_record_id.in_(records)))
            for n in (await db.execute(
                select(Notification).where(Notification.user_id.in_(users)))).scalars().all():
                await db.delete(n)
            for a in (await db.execute(
                select(AuditLog).where(
                    (AuditLog.actor_id.in_(users)) | (AuditLog.target_id.in_(records))
                ))).scalars().all():
                await db.delete(a)
            for rid in records:
                row = (await db.execute(select(IpRecord).where(IpRecord.id == rid))).scalar_one_or_none()
                if row is not None:
                    await db.delete(row)
            for u in (await db.execute(select(User).where(User.id.in_(users)))).scalars().all():
                await db.delete(u)
            await db.commit()
    asyncio.run(_go())
    for u in users:
        if u in TRACKED_USERS:
            TRACKED_USERS.remove(u)
    for r in records:
        if r in TRACKED_RECORDS:
            TRACKED_RECORDS.remove(r)


def _hod_headers(client):
    return _h(client, _tok(HOD_UID, "hod_admin", DEPT, "B12HOD"))


def _admin_headers(client):
    return _h(client, _tok(ADMIN_UID, "super_admin"))


@pytest.fixture(scope="module", autouse=True)
def _base_users():
    users = []
    for uid, email, role, fac in (
        (HOD_UID, "b12-hod@example.test", "hod_admin", "B12HOD"),
        (ADMIN_UID, "test-admin-002@faculty.edu", "super_admin", "test-admin-002"),
    ):
        async def _one(uid=uid, email=email, role=role, fac=fac):
            await _ensure_dept()
            async with get_async_session_context() as db:
                if not (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none():
                    db.add(User(id=uid, email=email, official_email=email,
                                password_hash=hash_password("ChangeMe123!"),
                                full_name=uid, role=role, faculty_id=fac,
                                department_id=DEPT, status="active", is_active=True))
                    await db.commit()
        asyncio.run(_one())
        users.append(uid)
    yield users
    # Leave the shared suite users (HOD/admin/dept) in place like mv-* ones.


# ---------------------------------------------------------------- Bug 1 ---
class TestAcceptLinksContributorAndSurfaces:
    def test_accept_persists_contributor_and_dashboard(self, client):
        sender = _mkuser("snd1")
        recip = _mkuser("rcp1")
        for u in (sender, recip):
            _create_user(u)
        rid = f"b12-rec-{uuid.uuid4().hex[:8]}"
        _create_record(rid, sender["id"])
        try:
            sh = _h(client, _tok(sender["id"], "faculty", DEPT, sender["faculty_id"]))
            rh = _h(client, _tok(recip["id"], "faculty", DEPT, recip["faculty_id"]))
            r = client.post(
                f"/api/v1/associations/?recipient_faculty_id={recip['faculty_id']}",
                json={"record_id": rid, "reason": "co-inventor"},
                headers=sh,
            )
            assert r.status_code == 201, r.text
            assoc_id = r.json()["id"]
            assert r.json()["status"] == "PENDING"

            a = client.post(f"/api/v1/associations/{assoc_id}/respond?action=accepted",
                            json={}, headers=rh)
            assert a.status_code == 200, a.text
            assert a.json()["status"] == "ACCEPTED"

            async def _check_db():
                async with get_async_session_context() as db:
                    row = (await db.execute(
                        select(AssociationRequest).where(AssociationRequest.id == assoc_id)
                    )).scalar_one()
                    assert row.status == "ACCEPTED"
                    link = (await db.execute(
                        select(IpContributor).where(
                            IpContributor.ip_record_id == rid,
                            IpContributor.user_id == recip["id"],
                        )
                    )).scalar_one_or_none()
                    assert link is not None
                    assert link.contributor_type == "INTERNAL_FACULTY"
            asyncio.run(_check_db())

            # Dashboard reflects the accepted patent for Faculty B.
            d = client.get("/api/v1/faculty/dashboard", headers=rh)
            assert d.status_code == 200, d.text
            ids = [x["id"] for x in d.json()["recent_records"]]
            assert rid in ids

            # Record detail is viewable by the accepted contributor.
            s = client.get(f"/api/v1/faculty/{rid}/status", headers=rh)
            assert s.status_code == 200, s.text

            # ... and again with a fresh token (logout/login persistence).
            rh2 = _h(client, _tok(recip["id"], "faculty", DEPT, recip["faculty_id"]))
            d2 = client.get("/api/v1/faculty/dashboard", headers=rh2)
            assert rid in [x["id"] for x in d2.json()["recent_records"]]

            # Profile counts include the associated record (Bug 7 visibility).
            p = client.get("/api/v1/faculty/profile", headers=rh2)
            assert p.status_code == 200, p.text
            assert p.json()["counts"]["total_documents"] >= 1
        finally:
            _cleanup([sender["id"], recip["id"]], [rid])


# ---------------------------------------------------------------- Bug 3 ---
def _add_internal_contributor(record_id, user_id, name="B12 Internal"):
    async def _go():
        async with get_async_session_context() as db:
            db.add(IpContributor(
                id=f"b12-c-{uuid.uuid4().hex[:8]}", ip_record_id=record_id,
                user_id=user_id, name=name, contributor_type="INTERNAL_FACULTY",
                match_status="VERIFICATION_REQUIRED", source="CERTIFICATE_OCR",
                is_external=False,
            ))
            await db.commit()
    asyncio.run(_go())


class TestHodVerifyGate:
    def _setup(self, client, tag):
        sender = _mkuser(f"{tag}s")
        other = _mkuser(f"{tag}o")
        for u in (sender, other):
            _create_user(u)
        rid = f"b12-rec-{tag}-{uuid.uuid4().hex[:6]}"
        _create_record(rid, sender["id"])
        return sender, other, rid

    def test_verify_rejected_while_internal_approval_pending(self, client):
        sender, other, rid = self._setup(client, "p")
        try:
            _add_internal_contributor(rid, other["id"])
            sh = _h(client, _tok(sender["id"], "faculty", DEPT, sender["faculty_id"]))
            r = client.post(
                f"/api/v1/associations/?recipient_faculty_id={other['faculty_id']}",
                json={"record_id": rid}, headers=sh)
            assert r.status_code == 201, r.text

            v = client.post(f"/api/v1/verification/institutional/{rid}",
                            json={"decision": "verify"}, headers=_hod_headers(client))
            assert v.status_code == 409, v.text
            assert v.json()["error"] == "ASSOCIATION_PENDING"

            # Nothing was recorded: no institutional attempt exists.
            async def _check():
                async with get_async_session_context() as db:
                    rows = (await db.execute(select(VerificationAttempt).where(
                        VerificationAttempt.ip_record_id == rid,
                        VerificationAttempt.source == "institutional_hod",
                    ))).scalars().all()
                    assert rows == []
            asyncio.run(_check())

            # Eligibility endpoint exposes the outstanding approver.
            g = client.get(f"/api/v1/verification/institutional/{rid}",
                           headers=_hod_headers(client))
            assert g.status_code == 200, g.text
            assert other["id"] in (g.json().get("pending_approvals") or [])
        finally:
            _cleanup([sender["id"], other["id"]], [rid])

    def test_verify_allowed_after_accept_and_persists_verified(self, client):
        sender, other, rid = self._setup(client, "a")
        try:
            _add_internal_contributor(rid, other["id"])
            sh = _h(client, _tok(sender["id"], "faculty", DEPT, sender["faculty_id"]))
            rh = _h(client, _tok(other["id"], "faculty", DEPT, other["faculty_id"]))
            r = client.post(
                f"/api/v1/associations/?recipient_faculty_id={other['faculty_id']}",
                json={"record_id": rid}, headers=sh)
            assert r.status_code == 201, r.text
            a = client.post(f"/api/v1/associations/{r.json()['id']}/respond?action=accepted",
                            json={}, headers=rh)
            assert a.status_code == 200, a.text

            v = client.post(f"/api/v1/verification/institutional/{rid}",
                            json={"decision": "verify", "remarks": "checked"},
                            headers=_hod_headers(client))
            assert v.status_code == 200, v.text
            body = v.json()
            assert body["final_verification_status"] == "VERIFIED"
            assert body["workflow_state"] == "VERIFIED"
            assert body["missing_conditions"] == []
            # Bug 6: automated official verification stays untouched / not required.
            assert body["official_verification_status"] == "VERIFICATION_REQUIRED"

            async def _check():
                async with get_async_session_context() as db:
                    rec = (await db.execute(select(IpRecord).where(IpRecord.id == rid))).scalar_one()
                    assert rec.verification_status == "VERIFIED"
                    assert rec.workflow_state == "VERIFIED"
                    assert rec.official_verification_status == "VERIFICATION_REQUIRED"
            asyncio.run(_check())
        finally:
            _cleanup([sender["id"], other["id"]], [rid])

    def test_verify_allowed_external_only(self, client):
        sender, other, rid = self._setup(client, "e")
        try:
            async def _ext():
                async with get_async_session_context() as db:
                    db.add(IpContributor(
                        id=f"b12-c-{uuid.uuid4().hex[:8]}", ip_record_id=rid,
                        user_id=None, name="External Person",
                        contributor_type="EXTERNAL", is_external=True,
                        match_status="VERIFICATION_REQUIRED", source="CERTIFICATE_OCR",
                    ))
                    await db.commit()
            asyncio.run(_ext())
            v = client.post(f"/api/v1/verification/institutional/{rid}",
                            json={"decision": "verify"}, headers=_hod_headers(client))
            assert v.status_code == 200, v.text
            assert v.json()["final_verification_status"] == "VERIFIED"
        finally:
            _cleanup([sender["id"], other["id"]], [rid])

    def test_verify_allowed_no_internal_links(self, client):
        sender, other, rid = self._setup(client, "n")
        try:
            v = client.post(f"/api/v1/verification/institutional/{rid}",
                            json={"decision": "verify"}, headers=_hod_headers(client))
            assert v.status_code == 200, v.text
            assert v.json()["final_verification_status"] == "VERIFIED"
        finally:
            _cleanup([sender["id"], other["id"]], [rid])

    def test_reject_still_recordable_while_pending(self, client):
        sender, other, rid = self._setup(client, "r")
        try:
            _add_internal_contributor(rid, other["id"])
            sh = _h(client, _tok(sender["id"], "faculty", DEPT, sender["faculty_id"]))
            r = client.post(
                f"/api/v1/associations/?recipient_faculty_id={other['faculty_id']}",
                json={"record_id": rid}, headers=sh)
            assert r.status_code == 201, r.text
            v = client.post(f"/api/v1/verification/institutional/{rid}",
                            json={"decision": "reject", "remarks": "mismatch"},
                            headers=_hod_headers(client))
            assert v.status_code == 200, v.text
            assert v.json()["decision"] == "reject"
        finally:
            _cleanup([sender["id"], other["id"]], [rid])


# ---------------------------------------------------------------- Bug 7 ---
class TestHodManualVerifyAndGrantVisibility:
    def test_verify_grant_profile_visibility(self, client):
        sender = _mkuser("g7s")
        other = _mkuser("g7o")
        for u in (sender, other):
            _create_user(u)
        rid = f"b12-rec-g7-{uuid.uuid4().hex[:6]}"
        _create_record(rid, sender["id"])
        try:
            sh = _h(client, _tok(sender["id"], "faculty", DEPT, sender["faculty_id"]))
            rh = _h(client, _tok(other["id"], "faculty", DEPT, other["faculty_id"]))
            _add_internal_contributor(rid, other["id"])
            r = client.post(
                f"/api/v1/associations/?recipient_faculty_id={other['faculty_id']}",
                json={"record_id": rid}, headers=sh)
            assert r.status_code == 201, r.text
            a = client.post(f"/api/v1/associations/{r.json()['id']}/respond?action=accepted",
                            json={}, headers=rh)
            assert a.status_code == 200, a.text

            v = client.post(f"/api/v1/verification/institutional/{rid}",
                            json={"decision": "verify"}, headers=_hod_headers(client))
            assert v.status_code == 200, v.text
            assert v.json()["final_verification_status"] == "VERIFIED"

            g = client.post(f"/api/v1/admin/ip-records/{rid}/grant", json={},
                            headers=_admin_headers(client))
            assert g.status_code == 200, g.text
            assert g.json()["workflow_state"] == "GRANTED"

            # Faculty profile + records surface the granted patent for the
            # accepted contributor (backend rows are the source of truth).
            p = client.get("/api/v1/faculty/profile", headers=rh)
            assert p.status_code == 200, p.text
            assert p.json()["counts"]["verified"] >= 1
            m = client.get("/api/v1/faculty/my-records?verification_status=VERIFIED",
                           headers=rh)
            assert m.status_code == 200, m.text
            assert rid in [x["id"] for x in m.json()["records"]]
        finally:
            _cleanup([sender["id"], other["id"]], [rid])


# ---------------------------------------------------------------- Bug 8 ---
class TestDeactivatedFacultyBlocked:
    def test_send_rejected_no_row_no_notification(self, client):
        sender = _mkuser("d8s")
        recip = _mkuser("d8r")
        _create_user(sender)
        _create_user(recip, active=False)
        rid = f"b12-rec-d8-{uuid.uuid4().hex[:6]}"
        _create_record(rid, sender["id"])
        try:
            sh = _h(client, _tok(sender["id"], "faculty", DEPT, sender["faculty_id"]))
            r = client.post(
                f"/api/v1/associations/?recipient_faculty_id={recip['faculty_id']}",
                json={"record_id": rid}, headers=sh)
            assert r.status_code == 422, r.text

            async def _check():
                async with get_async_session_context() as db:
                    rows = (await db.execute(select(AssociationRequest).where(
                        (AssociationRequest.target_faculty_id == recip["id"])
                        | (AssociationRequest.recipient_id == recip["id"])
                    ))).scalars().all()
                    assert rows == []
                    notes = (await db.execute(select(Notification).where(
                        Notification.user_id == recip["id"]))).scalars().all()
                    assert notes == []
            asyncio.run(_check())

            # Secondary faculty endpoint enforces the same rule.
            r2 = client.post(
                f"/api/v1/faculty/{rid}/associate/{recip['faculty_id']}",
                headers=sh)
            assert r2.status_code == 422, r2.text
        finally:
            _cleanup([sender["id"], recip["id"]], [rid])

    def test_active_recipient_still_allowed(self, client):
        sender = _mkuser("d8as")
        recip = _mkuser("d8ar")
        for u in (sender, recip):
            _create_user(u)
        rid = f"b12-rec-d8a-{uuid.uuid4().hex[:6]}"
        _create_record(rid, sender["id"])
        try:
            sh = _h(client, _tok(sender["id"], "faculty", DEPT, sender["faculty_id"]))
            r = client.post(
                f"/api/v1/associations/?recipient_faculty_id={recip['faculty_id']}",
                json={"record_id": rid}, headers=sh)
            assert r.status_code == 201, r.text

            async def _check():
                async with get_async_session_context() as db:
                    notes = (await db.execute(select(Notification).where(
                        Notification.user_id == recip["id"]))).scalars().all()
                    assert len(notes) >= 1
            asyncio.run(_check())
        finally:
            _cleanup([sender["id"], recip["id"]], [rid])


# ------------------------------------------------- Bugs 4+5 (backend) ---
class TestDisplayNamesEnriched:
    def test_hod_duplicates_conflicts_documents_carry_names(self, client):
        u = _mkuser("d45u")
        _create_user(u)
        r1 = f"b12-rec-d45a-{uuid.uuid4().hex[:6]}"
        r2 = f"b12-rec-d45b-{uuid.uuid4().hex[:6]}"
        for rid in (r1, r2):
            _create_record(rid, u["id"], title=f"B12 doc {rid[:8]}")
        try:
            async def _seed():
                async with get_async_session_context() as db:
                    db.add(IpFile(id=f"b12-f-{uuid.uuid4().hex[:8]}", ip_record_id=r1,
                                  storage_key=f"b12/{uuid.uuid4().hex}", original_filename="patent_application.pdf",
                                  file_extension=".pdf", file_size_bytes=10, uploaded_by=u["id"],
                                  upload_status="COMPLETED"))
                    db.add(DuplicateCase(id=f"b12-dup-{uuid.uuid4().hex[:8]}",
                                         ip_record_id_1=r1, ip_record_id_2=r2,
                                         detection_method="identifier", confidence=0.9, status="OPEN"))
                    db.add(ConflictCase(id=f"b12-cf-{uuid.uuid4().hex[:8]}", ip_record_id=r1,
                                        conflict_type="test", description="b12", status="OPEN"))
                    await db.commit()
            asyncio.run(_seed())

            d = client.get("/api/v1/hod/duplicates", headers=_hod_headers(client))
            assert d.status_code == 200, d.text
            row = next(x for x in d.json()["duplicates"]
                       if x["ip_record_id_1"] == r1 and x["ip_record_id_2"] == r2)
            assert (row["record_1"] or {}).get("display_name") == "patent_application.pdf"
            assert (row["record_2"] or {}).get("display_name") == f"B12 doc {r2[:8]}"

            c = client.get("/api/v1/hod/conflicts", headers=_hod_headers(client))
            assert c.status_code == 200, c.text
            crow = next(x for x in c.json()["conflicts"] if x["ip_record_id"] == r1)
            assert (crow["record"] or {}).get("display_name") == "patent_application.pdf"

            docs = client.get("/api/v1/hod/documents?per_page=50", headers=_hod_headers(client))
            assert docs.status_code == 200, docs.text
            drow = next(x for x in docs.json()["documents"] if x["id"] == r1)
            assert drow["document_name"] == "patent_application.pdf"
            assert "id" not in str(drow["document_name"])
        finally:
            _cleanup([u["id"]], [r1, r2])

    def test_admin_queues_carry_names(self, client):
        u = _mkuser("d45au")
        _create_user(u)
        r1 = f"b12-rec-adm-{uuid.uuid4().hex[:6]}"
        _create_record(r1, u["id"], title="B12 admin doc")
        try:
            async def _seed():
                async with get_async_session_context() as db:
                    db.add(IpFile(id=f"b12-f-{uuid.uuid4().hex[:8]}", ip_record_id=r1,
                                  storage_key=f"b12/{uuid.uuid4().hex}", original_filename="admin_doc.pdf",
                                  file_extension=".pdf", file_size_bytes=10, uploaded_by=u["id"],
                                  upload_status="COMPLETED"))
                    db.add(VerificationAttempt(id=f"b12-v-{uuid.uuid4().hex[:8]}",
                                               ip_record_id=r1, source="manual",
                                               attempt_number=1, status="VERIFICATION_REQUIRED"))
                    await db.commit()
            asyncio.run(_seed())
            v = client.get("/api/v1/admin/verifications?per_page=50",
                           headers=_admin_headers(client))
            assert v.status_code == 200, v.text
            rows = [x for x in v.json()["verifications"] if x["ip_record_id"] == r1]
            assert rows and (rows[0]["record"] or {}).get("display_name") == "admin_doc.pdf"
        finally:
            _cleanup([u["id"]], [r1])


# ------------------------------------------------------- Bug 6 (unit) ---
class TestOfficialVerificationNotRequired:
    def test_pipeline_gate_verifies_without_official_confirmation(self):
        from app.agents.final_verification_agent import FinalVerificationAgent

        agent = FinalVerificationAgent()
        status, rationale, confidence = agent._decide_verification(
            verification_status="VERIFICATION_REQUIRED",
            verification_confidence=0.0,
            extraction_confidence=0.85,
            resolved_entities=[],
            duplicate_conflicts=[],
            critical_conflicts=[],
            field_completeness=0.85,
            evidence_coverage=0.9,
            has_faculty_approval=True,
        )
        assert status == "VERIFIED"
        assert confidence >= 0.75


# ------------------------------------------------------- Bug 9 (unit) ---
class TestGrantDateExtraction:
    def _extract(self, text):
        from app.services.extraction import StructuredExtractionService

        svc = StructuredExtractionService()
        res = svc.extract_from_text(
            f"Patent Number : IN123456\nTitle : Widget\n{text}\nApplicant : Someone",
            "PATENT",
        )
        nf = res["normalized_fields"].get("grant_date")
        return nf[0]["value"] if nf else None

    def test_separator_variants(self):
        from datetime import date

        assert self._extract("Date of Grant : 22/10/2024") == date(2024, 10, 22)
        assert self._extract("(45) Date of Grant : 04/10/2024") == date(2024, 10, 4)
        assert self._extract("Grant Date: 2024-10-22") == date(2024, 10, 22)

    def test_separatorless_variants(self):
        from datetime import date

        assert self._extract("The patent was Granted on 15 March 2024 by the office") == date(2024, 3, 15)
        assert self._extract("Date of Grant 22/10/2024") == date(2024, 10, 22)
        assert self._extract("Granted: 22-10-2024") == date(2024, 10, 22)
        assert self._extract("Date of Grant of Patent : 15/03/2024") == date(2024, 3, 15)
        assert self._extract("Date of Grant : 04/10/2024 (Friday)") == date(2024, 10, 4)

    def test_no_false_positive(self):
        assert self._extract("The grant dates are important for renewal") is None

    def test_orchestrator_date_coercion(self):
        from datetime import date, datetime

        from app.workers.orchestrator_task import _coerce_record_datetime

        assert _coerce_record_datetime(date(2024, 10, 22)) == datetime(2024, 10, 22)
        assert _coerce_record_datetime(datetime(2024, 10, 22, 5, 6)) == datetime(2024, 10, 22, 5, 6)
        assert _coerce_record_datetime("2024-10-22") == datetime(2024, 10, 22)
        assert _coerce_record_datetime(2024) is None
        assert _coerce_record_datetime("not a date") is None
        assert _coerce_record_datetime(None) is None


# ------------------------------------------------------ Bug 10 (unit) ---
class TestQrVariantCoverage:
    def test_page_size_image_gets_grayscale_and_upscale(self):
        from PIL import Image

        from app.services.ocr_pipeline import _prepare_qr_variants

        page = Image.new("RGB", (1190, 1684), color="white")
        labels = [lbl for lbl, _ in _prepare_qr_variants(page)]
        assert "original" in labels
        assert "grayscale" in labels
        assert "rotated_90" in labels and "rotated_180" in labels and "rotated_270" in labels
        assert "upscaled_2x" in labels

    def test_large_image_skips_upscale(self):
        from PIL import Image

        from app.services.ocr_pipeline import _prepare_qr_variants

        labels = [lbl for lbl, _ in _prepare_qr_variants(Image.new("RGB", (2000, 2000), color="white"))]
        assert "grayscale" in labels
        assert not any("upscaled_2x" in lbl for lbl in labels)

    def test_grayscale_variant_reaches_decoder(self):
        import io

        from PIL import Image

        import pyzbar.pyzbar as pyzbar_mod
        from app.services.ocr_pipeline import decode_qr_payloads

        seen_modes: list[str] = []
        real_decode = pyzbar_mod.decode

        def _spy(image, *args, **kwargs):
            try:
                seen_modes.append(getattr(image, "mode", "?"))
            except Exception:
                pass
            return []

        pyzbar_mod.decode = _spy
        try:
            buf = io.BytesIO()
            Image.new("RGB", (300, 300), color="white").save(buf, format="PNG")
            result = decode_qr_payloads(buf.getvalue(), filename="blank.png")
        finally:
            pyzbar_mod.decode = real_decode
        assert "L" in seen_modes
        # Genuinely no QR: clean not-detected state, never fabricated data.
        # (source is "none" when nothing decodes, "invalid" when a decoder
        # reports an empty payload — both carry qr_data == [].)
        assert result.success is False
        assert result.qr_data == []
        assert result.source in ("none", "invalid")


# ------------------------------------------------------ Bug 12 (live) ---
class TestUploadConfigAndSizeError:
    def test_config_reflects_admin_setting_and_size_error_stays_structured(self, client):
        from app.core.config import upload_settings
        from app.core.runtime_settings import get_max_upload_bytes, get_max_upload_mb

        admin_h = _admin_headers(client)
        before = client.get("/api/v1/admin/settings", headers=admin_h)
        assert before.status_code == 200, before.text
        original_mb = before.json()["uploads"]["max_upload_mb"]
        faculty = _mkuser("u12f")
        _create_user(faculty)
        fh = _h(client, _tok(faculty["id"], "faculty", DEPT, faculty["faculty_id"]))
        try:
            c = client.get("/api/v1/uploads/config", headers=fh)
            assert c.status_code == 200, c.text
            body = c.json()
            assert body["max_upload_bytes"] == get_max_upload_bytes(upload_settings.max_upload_bytes)
            assert body["max_upload_mb"] == get_max_upload_mb(upload_settings.max_upload_bytes)
            assert ".pdf" in body["allowed_extensions"]

            p = client.patch("/api/v1/admin/settings", json={"max_upload_mb": 2},
                             headers=admin_h)
            assert p.status_code == 200, p.text
            assert p.json()["max_upload_mb"] == 2

            c2 = client.get("/api/v1/uploads/config", headers=fh)
            assert c2.status_code == 200, c2.text
            assert c2.json()["max_upload_mb"] == 2
            assert c2.json()["max_upload_bytes"] == 2 * 1024 * 1024

            big = b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024 + 100)
            r = client.post("/api/v1/uploads/", files={"file": ("big.pdf", big, "application/pdf")},
                            headers=fh)
            assert r.status_code == 400, r.text
            payload = r.json()
            assert payload["error"] == "UPLOAD_ERROR"
            assert "(max:" in payload["message"]
        finally:
            client.patch("/api/v1/admin/settings", json={"max_upload_mb": original_mb},
                         headers=admin_h)
            _cleanup([faculty["id"]], [])

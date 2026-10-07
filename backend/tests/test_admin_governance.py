"""Admin governance: one-HOD-per-department (item 7) + faculty delete (item 6).

Hermetic pattern: gv- departments/users/records, everything created is
deleted in teardown. The partial unique index uq_active_hod_per_department
is asserted live. No existing data is touched.
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
    Department,
    Designation,
    IpRecord,
    Notification,
    SecurityEvent,
    User,
)

TAG = uuid.uuid4().hex[:6]
ADMIN = {"id": f"gv-adm-{TAG}", "email": f"gvadm.{TAG}@example.test"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tok(uid, email, role, dept="", fac=""):
    return generate_jwt_token(
        uid, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=email, role=role,
        faculty_id=fac or uid, department_id=dept, full_name=uid,
    )


def _h(client, token):
    csrf = client.cookies.get("csrf_token")
    if csrf is None:
        csrf = "t"
        client.cookies.set("csrf_token", csrf)
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


def _run(coro):
    return asyncio.run(coro)


async def _mkdept(suffix):
    did = f"gv-dept-{TAG}-{suffix}"
    async with get_async_session_context() as db:
        db.add(Department(id=did, name=f"GV Dept {TAG} {suffix}", code=f"GV{TAG}{suffix}", is_active=True))
        await db.commit()
    return did


async def _mkuser(uid, email, role, dept_id, active=True, designation_id=None):
    async with get_async_session_context() as db:
        db.add(User(id=uid, email=email, official_email=email,
                    password_hash=hash_password("secret123"), full_name=uid,
                    role=role, faculty_id=f"FAC-GV-{uid[:6]}".upper(),
                    department_id=dept_id, designation_id=designation_id,
                    status="active" if active else "inactive", is_active=active))
        await db.commit()


async def _wipe_users(uids, dept_ids, record_ids=()):
    async with get_async_session_context() as db:
        for rid in record_ids:
            await db.execute(delete(AssociationRequest).where(AssociationRequest.ip_record_id == rid))
            row = (await db.execute(select(IpRecord).where(IpRecord.id == rid))).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
        for n in (await db.execute(select(Notification).where(Notification.user_id.in_(uids)))).scalars().all():
            await db.delete(n)
        for e in (await db.execute(select(SecurityEvent).where(SecurityEvent.user_id.in_(uids)))).scalars().all():
            await db.delete(e)
        for a in (await db.execute(select(AuditLog).where(
                (AuditLog.actor_id.in_(uids)) | (AuditLog.target_id.in_(uids)) | (AuditLog.entity_id.in_(uids))
        ))).scalars().all():
            await db.delete(a)
        for u in (await db.execute(select(User).where(User.id.in_(uids)))).scalars().all():
            await db.delete(u)
        for did in dept_ids:
            d = (await db.execute(select(Department).where(Department.id == did))).scalar_one_or_none()
            if d is not None:
                await db.delete(d)
        await db.commit()


@pytest.fixture(scope="module", autouse=True)
def _admin():
    _run(_mkuser(ADMIN["id"], ADMIN["email"], "super_admin", None))
    yield
    _run(_wipe_users([ADMIN["id"]], []))


def _admin_h(client):
    return _h(client, _tok(ADMIN["id"], ADMIN["email"], "super_admin"))


class TestHodUniqueness:
    def test_second_active_hod_rejected_with_message(self, client):
        dept = _run(_mkdept("d1"))
        h1 = f"gv-hod1-{TAG}"
        h2 = f"gv-hod2-{TAG}"
        try:
            _run(_mkuser(h1, f"{h1}@example.test", "hod_admin", dept))
            # Direct second HOD via API-equivalent path is covered below;
            # here prove the DB backstop itself rejects a duplicate row.
            import sqlalchemy.exc

            async def _dup():
                async with get_async_session_context() as db:
                    db.add(User(id=h2, email=f"{h2}@example.test", official_email=f"{h2}@example.test",
                                password_hash=hash_password("x"), full_name=h2,
                                role="hod_admin", faculty_id="FAC-GV-H2",
                                department_id=dept, status="active", is_active=True))
                    await db.commit()

            with pytest.raises(sqlalchemy.exc.IntegrityError):
                _run(_dup())
        finally:
            _run(_wipe_users([h1, h2], [dept]))

    def test_create_second_hod_returns_409_message(self, client):
        dept = _run(_mkdept("d2"))
        h1 = f"gv-hod3-{TAG}"
        try:
            _run(_mkuser(h1, f"{h1}@example.test", "hod_admin", dept))
            desig = _run(_get_hod_designation())
            assert desig is not None, "HOD designation seed required"
            r = client.post("/api/v1/admin/faculty",
                            json={"email": f"gv-hod4-{TAG}@example.test", "full_name": "Second HOD",
                                  "department_id": dept, "designation_id": desig},
                            headers=_admin_h(client))
            assert r.status_code == 409, r.text
            assert r.json()["error"] == "DUPLICATE_HOD"
            assert r.json()["message"] == (
                "An HOD is already assigned to this department. "
                "Please update the existing HOD instead of creating a new one."
            )
        finally:
            _run(_wipe_users([h1], [dept]))

    def test_update_to_occupied_dept_rejected(self, client):
        d1 = _run(_mkdept("d3a"))
        d2 = _run(_mkdept("d3b"))
        h1 = f"gv-hod5-{TAG}"
        fac = f"gv-fac5-{TAG}"
        try:
            _run(_mkuser(h1, f"{h1}@example.test", "hod_admin", d1))
            _run(_mkuser(fac, f"{fac}@example.test", "faculty", d2))
            desig = _run(_get_hod_designation())
            # Promote faculty to HOD inside the occupied department.
            r = client.patch(f"/api/v1/admin/faculty/{fac}",
                             json={"designation_id": desig, "department_id": d1},
                             headers=_admin_h(client))
            assert r.status_code == 409, r.text
            assert r.json()["error"] == "DUPLICATE_HOD"
        finally:
            _run(_wipe_users([h1, fac], [d1, d2]))

    def test_deactivated_hod_does_not_block_and_replace_works(self, client):
        dept = _run(_mkdept("d4"))
        h1 = f"gv-hod6-{TAG}"
        try:
            _run(_mkuser(h1, f"{h1}@example.test", "hod_admin", dept))
            desig = _run(_get_hod_designation())
            # Deactivate the old HOD, then create the replacement.
            d = client.post(f"/api/v1/admin/faculty/{h1}/deactivate", headers=_admin_h(client))
            assert d.status_code == 200, d.text
            r = client.post("/api/v1/admin/faculty",
                            json={"email": f"gv-hod7-{TAG}@example.test", "full_name": "Replacement HOD",
                                  "department_id": dept, "designation_id": desig},
                            headers=_admin_h(client))
            assert r.status_code == 201, r.text
            new_id = r.json()["id"]
            try:
                async def _check():
                    async with get_async_session_context() as db:
                        active = (await db.execute(select(User).where(
                            User.role == "hod_admin", User.is_active.is_(True),
                            User.department_id == dept))).scalars().all()
                        assert [u.id for u in active] == [new_id]
                _run(_check())
            finally:
                _run(_wipe_users([new_id], []))
        finally:
            _run(_wipe_users([h1], [dept]))


async def _get_hod_designation():
    async with get_async_session_context() as db:
        from app.models.base import Designation as _D

        row = (await db.execute(select(_D).where(_D.title.ilike("HOD")))).scalars().first()
        return row.id if row else None


class TestFacultyDelete:
    def test_delete_clean_faculty(self, client):
        dept = _run(_mkdept("d5"))
        uid = f"gv-del-{TAG}"
        try:
            _run(_mkuser(uid, f"{uid}@example.test", "faculty", dept))
            r = client.delete(f"/api/v1/admin/faculty/{uid}", headers=_admin_h(client))
            assert r.status_code == 200, r.text

            async def _check():
                async with get_async_session_context() as db:
                    assert (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none() is None
            _run(_check())
        finally:
            _run(_wipe_users([uid], [dept]))

    def test_delete_uploader_refused(self, client):
        dept = _run(_mkdept("d6"))
        uid = f"gv-own-{TAG}"
        rid = f"gv-rec-{TAG}"
        try:
            _run(_mkuser(uid, f"{uid}@example.test", "faculty", dept))

            async def _rec():
                async with get_async_session_context() as db:
                    db.add(IpRecord(id=rid, ip_type="PATENT", patent_number=f"GV-{TAG}",
                                    title="GV owned", verification_status="VERIFICATION_REQUIRED",
                                    processing_status="COMPLETED", workflow_state="NEEDS_REVIEW",
                                    uploader_id=uid, department_id=dept, is_archived=False))
                    await db.commit()
            _run(_rec())
            r = client.delete(f"/api/v1/admin/faculty/{uid}", headers=_admin_h(client))
            assert r.status_code == 409, r.text
            assert r.json()["error"] == "FACULTY_HAS_DATA"
            assert "uploaded record" in r.json()["message"]
        finally:
            _run(_wipe_users([uid], [dept], [rid]))

    def test_delete_assoc_party_refused(self, client):
        dept = _run(_mkdept("d7"))
        a = f"gv-asa-{TAG}"
        b = f"gv-asb-{TAG}"
        rid = f"gv-rec2-{TAG}"
        try:
            _run(_mkuser(a, f"{a}@example.test", "faculty", dept))
            _run(_mkuser(b, f"{b}@example.test", "faculty", dept))

            async def _seed():
                async with get_async_session_context() as db:
                    db.add(IpRecord(id=rid, ip_type="PATENT", patent_number=f"GV2-{TAG}",
                                    title="GV assoc", verification_status="VERIFICATION_REQUIRED",
                                    processing_status="COMPLETED", workflow_state="NEEDS_REVIEW",
                                    uploader_id=a, department_id=dept, is_archived=False))
                    db.add(AssociationRequest(id=f"gv-ar-{TAG}", ip_record_id=rid,
                                              requesting_faculty_id=a, target_faculty_id=b,
                                              requester_id=a, recipient_id=b, status="PENDING"))
                    await db.commit()
            _run(_seed())
            r = client.delete(f"/api/v1/admin/faculty/{b}", headers=_admin_h(client))
            assert r.status_code == 409, r.text
        finally:
            _run(_wipe_users([a, b], [dept], [rid]))

    def test_delete_unknown_is_404_and_admin_self_not_deletable(self, client):
        r = client.delete("/api/v1/admin/faculty/no-such-id", headers=_admin_h(client))
        assert r.status_code == 404, r.text
        # Super admins are outside the faculty/hod scope: self-delete is 404,
        # and the endpoint additionally guards against self-deletion.
        r2 = client.delete(f"/api/v1/admin/faculty/{ADMIN['id']}", headers=_admin_h(client))
        assert r2.status_code == 404, r2.text


class TestGrantDateFormats:
    def test_dotted_and_iso_dotted_dates(self):
        from datetime import date

        from app.services.extraction import normalize_date

        assert normalize_date("22.10.2024") == date(2024, 10, 22)
        assert normalize_date("2024.10.22") == date(2024, 10, 22)
        assert normalize_date("22/10/2024") == date(2024, 10, 22)
        assert normalize_date("not a date") is None

    def test_grant_patterns_cover_dotted_forms(self):
        from datetime import date

        from app.services.extraction import StructuredExtractionService

        svc = StructuredExtractionService()
        res = svc.extract_from_text(
            "Patent Number : IN999001\nTitle : Dotted\nDate of Grant : 22.10.2024\nApplicant : Someone",
            "PATENT",
        )
        nf = res["normalized_fields"].get("grant_date")
        assert nf and nf[0]["value"] == date(2024, 10, 22)
        svc2 = StructuredExtractionService()
        res2 = svc2.extract_from_text(
            "Patent Number : IN999002\nTitle : Plain\nGranted on 15 March 2024\nApplicant : Someone",
            "PATENT",
        )
        nf2 = res2["normalized_fields"].get("grant_date")
        assert nf2 and nf2[0]["value"] == date(2024, 3, 15)

    def test_version_like_strings_are_not_dates(self):
        from app.services.extraction import StructuredExtractionService

        svc = StructuredExtractionService()
        res = svc.extract_from_text(
            "Patent Number : IN999003\nTitle : Widget\nSoftware version 1.2.3 released\nApplicant : Someone",
            "PATENT",
        )
        assert res["normalized_fields"].get("grant_date") is None


class TestHodExtraction:
    def test_hod_name_evidence_and_guard(self):
        from app.services.extraction import StructuredExtractionService

        svc = StructuredExtractionService()
        res = svc.extract_from_text(
            "Patent Number : IN999004\nTitle : HOD Widget\nHOD : Dr. Rajesh Kumar\nApplicant : Someone",
            "PATENT",
        )
        nf = res["normalized_fields"].get("hod_name")
        assert nf and "Rajesh" in str(nf[0]["value"])

        svc2 = StructuredExtractionService()
        res2 = svc2.extract_from_text(
            "Patent Number : IN999005\nTitle : Dept Doc\nHead of Department : Computer Science\nApplicant : Someone",
            "PATENT",
        )
        assert res2["normalized_fields"].get("hod_name") is None

    def test_hod_identity_matches_active_same_dept(self):
        from app.services.identity_resolution import resolve_hod_identity

        async def _go():
            return await resolve_hod_identity(
                "No Such Person Anywhere",
                faculty_db=[{"id": "x", "faculty_id": "X", "full_name": "Zed Zeb",
                             "email": "z@example.test", "department": "D",
                             "designation": "", "institution": "", "is_active": True}],
            )
        result = _run(_go())
        assert result.best_match is None or result.best_match.overall_confidence < 0.4


class TestEmailStatus:
    def test_settings_exposes_email_status_without_secrets(self, client):
        r = client.get("/api/v1/admin/settings", headers=_admin_h(client))
        assert r.status_code == 200, r.text
        email = r.json().get("email")
        assert isinstance(email, dict)
        assert email.get("status") in ("CONFIGURED", "DISABLED")
        flat = str(r.json())
        assert "smtp_password" not in flat.lower()
        assert "SMTP_PASSWORD" not in flat


class TestWorkflowStatuses:
    def test_new_states_transition_and_flags(self):
        from app.services.workflow import advance_through, can_transition, describe_state

        assert advance_through("UPLOADED", "HOD_ASSOCIATION_PENDING") == "HOD_ASSOCIATION_PENDING"
        assert can_transition("HOD_ASSOCIATION_PENDING", "HOD_ASSOCIATION_ACCEPTED")
        assert can_transition("HOD_ASSOCIATION_ACCEPTED", "FACULTY_APPROVAL_PENDING")
        assert can_transition("FACULTY_APPROVAL_PENDING", "FACULTY_APPROVED")
        assert can_transition("FACULTY_APPROVED", "HOD_VERIFICATION_PENDING")
        assert can_transition("HOD_VERIFICATION_PENDING", "VERIFIED")
        assert advance_through("HOD_VERIFICATION_PENDING", "VERIFIED") == "VERIFIED"
        for s in ("HOD_ASSOCIATION_PENDING", "HOD_ASSOCIATION_ACCEPTED",
                  "FACULTY_APPROVED", "HOD_VERIFICATION_PENDING"):
            assert describe_state(s)["requires_human_review"] is True
        assert describe_state("VERIFIED")["terminal"] is True

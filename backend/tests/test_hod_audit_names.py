"""HOD audit readability (Bug 4) — regression tests.

The HOD audit endpoint must resolve human-readable actor and patent/IP
entity names. Raw UUIDs stay in the payload for traceability but must not
be the primary display. Audit functionality itself is unchanged.

Hermetic pattern: b4- users/record/audit rows, everything created is
deleted in teardown (the shared b4-dept row persists like mv-dept).
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
from app.models.base import AuditLog, Department, IpFile, IpRecord, User


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tok(sub, role, dept="", fac=""):
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


DEPT = "b4-dept"
HOD_UID = "b4-hod-001"


@pytest.fixture(scope="module", autouse=True)
def _dept():
    async def _go():
        async with get_async_session_context() as db:
            if not (await db.execute(select(Department).where(Department.id == DEPT))).scalar_one_or_none():
                db.add(Department(id=DEPT, name="B4 Dept", code="B4", is_active=True))
                await db.commit()
    asyncio.run(_go())


@pytest.fixture()
def audit_scene():
    tag = uuid.uuid4().hex[:6]
    hod = {"id": HOD_UID, "email": "b4-hod@example.test", "faculty_id": "B4HOD"}
    fac = {"id": f"b4-fac-{tag}", "email": f"b4fac.{tag}@example.test", "faculty_id": f"FAC-B4-{tag}"}
    rid = f"b4-rec-{tag}"
    aid = f"b4-audit-{tag}"

    async def _create():
        async with get_async_session_context() as db:
            for u, role in ((hod, "hod_admin"), (fac, "faculty")):
                if not (await db.execute(select(User).where(User.id == u["id"]))).scalar_one_or_none():
                    db.add(User(id=u["id"], email=u["email"], official_email=u["email"],
                                password_hash=hash_password("secret123"), full_name=u["id"],
                                role=role, faculty_id=u["faculty_id"], department_id=DEPT,
                                status="active", is_active=True))
            db.add(IpRecord(id=rid, ip_type="PATENT", patent_number=f"B4-{tag}",
                            title="B4 audit widget", verification_status="VERIFICATION_REQUIRED",
                            processing_status="COMPLETED", workflow_state="VERIFICATION_REQUIRED",
                            uploader_id=fac["id"], department_id=DEPT, is_archived=False))
            db.add(IpFile(id=f"b4-f-{tag}", ip_record_id=rid, storage_key=f"b4/{tag}",
                          original_filename="b4_certificate.pdf", file_extension=".pdf",
                          file_size_bytes=10, uploaded_by=fac["id"], upload_status="COMPLETED"))
            db.add(AuditLog(id=aid, actor_id=hod["id"], actor_role="hod_admin",
                            action="INSTITUTIONAL_VERIFICATION_VERIFY",
                            entity_type="ip_record", entity_id=rid))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            await db.execute(delete(AuditLog).where(AuditLog.id == aid))
            await db.execute(delete(IpFile).where(IpFile.ip_record_id == rid))
            row = (await db.execute(select(IpRecord).where(IpRecord.id == rid))).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
            for u in (await db.execute(select(User).where(User.id == fac["id"]))).scalars().all():
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        yield {"hod": hod, "fac": fac, "record_id": rid, "audit_id": aid}
    finally:
        asyncio.run(_delete())


class TestHodAuditNames:
    def test_audit_resolves_actor_and_record_names(self, client, audit_scene):
        h = _h(client, _tok(HOD_UID, "hod_admin", DEPT, "B4HOD"))
        r = client.get("/api/v1/hod/audit?per_page=50", headers=h)
        assert r.status_code == 200, r.text
        rows = [e for e in r.json()["audit_entries"] if e["id"] == audit_scene["audit_id"]]
        assert len(rows) == 1
        row = rows[0]
        # Actor resolved to a human name.
        assert (row["actor"] or {}).get("full_name") == HOD_UID
        # Patent entity resolved to persisted document identity.
        entity = row["entity"] or {}
        assert entity.get("display_name") == "b4_certificate.pdf"
        assert entity.get("title") == "B4 audit widget"
        # Raw IDs retained for traceability, not as the display.
        assert row["actor_id"] == HOD_UID
        assert row["entity_id"] == audit_scene["record_id"]

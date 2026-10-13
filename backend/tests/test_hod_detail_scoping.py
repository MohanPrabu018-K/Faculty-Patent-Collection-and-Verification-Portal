"""B12: HOD record-detail scoping matches the HOD list rule.

GET /faculty/{id}/status and GET /uploads/{id}/status used to filter HODs by
``record.department_id`` only, while GET /hod/documents lists any
past-faculty-stage record whose *represented* departments (uploader +
contributor + record departments) include the HOD's department. An HOD could
see a multi-department patent in the list and then get 404 on View.

Fixed: both detail endpoints enforce the shared ``_hod_visible_record_ids``
rule. The 404 contract is byte-identical (no enumeration change).

Hermetic: throwaway departments/users/record, deleted by fixtures.
"""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import Department, IpRecord, User


def _clear_rate_limiters():
    from app.api.deps import rate_limit_state
    from app.core.security_middleware import _rate_limiter

    rate_limit_state.counts.clear()
    if hasattr(_rate_limiter, "_buckets"):
        _rate_limiter._buckets.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    _clear_rate_limiters()
    yield


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tok(sub, role, dept=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=sub, department_id=dept, full_name=sub,
    )


def _h(client, token):
    csrf = client.cookies.get("csrf_token") or "t"
    client.cookies.set("csrf_token", csrf)
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


TAG = uuid.uuid4().hex[:8]
DEPT_A = f"bx-dept-a-{TAG}"
DEPT_B = f"bx-dept-b-{TAG}"
DEPT_C = f"bx-dept-c-{TAG}"


@pytest.fixture(scope="module")
def world():
    """Two departments, uploader faculty in A, HODs for A/B/C, and one
    past-faculty-stage record owned by the A uploader but filed under B."""
    up_id, ha_id, hb_id, hc_id = (f"bx-u-{TAG}", f"bx-ha-{TAG}", f"bx-hb-{TAG}", f"bx-hc-{TAG}")
    rec_id = f"bx-rec-{TAG}"

    async def _create():
        async with get_async_session_context() as db:
            for did, name, letter in ((DEPT_A, f"BX Dept A {TAG}", "A"), (DEPT_B, f"BX Dept B {TAG}", "B"),
                              (DEPT_C, f"BX Dept C {TAG}", "C")):
                db.add(Department(id=did, name=name, code=f"BX-{TAG}-{letter}"))
            await db.flush()
            db.add(User(id=up_id, email=f"{up_id}@faculty.edu", full_name="BX Uploader",
                        password_hash=hash_password("secret123"), role="faculty",
                        faculty_id=up_id, department_id=DEPT_A, is_active=True, status="active"))
            for hid, dept in ((ha_id, DEPT_A), (hb_id, DEPT_B), (hc_id, DEPT_C)):
                db.add(User(id=hid, email=f"{hid}@faculty.edu", full_name=f"BX HOD {dept[-1].upper()}",
                            password_hash=hash_password("secret123"), role="hod_admin",
                            faculty_id=hid, department_id=dept, is_active=True, status="active"))
            db.add(IpRecord(id=rec_id, ip_type="PATENT", patent_number=f"BX-PAT-{TAG}",
                            title="BX multi-department probe", verification_status="VERIFIED",
                            processing_status="COMPLETED", workflow_state="FACULTY_ASSOCIATION_COMPLETE",
                            uploader_id=up_id, department_id=DEPT_B))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            row = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
            for uid in (up_id, ha_id, hb_id, hc_id):
                u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
                if u is not None:
                    await db.delete(u)
            for did in (DEPT_A, DEPT_B, DEPT_C):
                d = (await db.execute(select(Department).where(Department.id == did))).scalar_one_or_none()
                if d is not None:
                    await db.delete(d)
            await db.commit()

    asyncio.run(_create())
    try:
        yield {"rec": rec_id, "up": up_id, "ha": ha_id, "hb": hb_id, "hc": hc_id}
    finally:
        asyncio.run(_delete())


def test_represented_dept_hod_reads_status_detail(client, world):
    """HOD-A's department is represented via the uploader (record filed under
    B). Old code returned 404 here despite the list showing the record."""
    r = client.get(f"/api/v1/faculty/{world['rec']}/status", headers=_h(client, _tok(world["ha"], "hod_admin", DEPT_A)))
    assert r.status_code == 200, r.text
    assert r.json()["record_id"] == world["rec"]


def test_record_dept_hod_reads_status_detail(client, world):
    r = client.get(f"/api/v1/faculty/{world['rec']}/status", headers=_h(client, _tok(world["hb"], "hod_admin", DEPT_B)))
    assert r.status_code == 200, r.text
    assert r.json()["record_id"] == world["rec"]


def test_unrelated_hod_gets_identical_404(client, world):
    r = client.get(f"/api/v1/faculty/{world['rec']}/status", headers=_h(client, _tok(world["hc"], "hod_admin", DEPT_C)))
    assert r.status_code == 404, r.text
    assert r.json().get("error") == "NOT_FOUND"


def test_pre_stage_record_invisible_to_same_dept_hod(client, world):
    """Even the record-department HOD cannot see a record still in faculty
    association (stage gate applies to detail, not just the list)."""
    rec2, up = f"bx-rec2-{TAG}", world["up"]

    async def _create():
        async with get_async_session_context() as db:
            db.add(IpRecord(id=rec2, ip_type="PATENT", patent_number=f"BX2-PAT-{TAG}",
                            title="BX pre-stage probe", verification_status="UNVERIFIED",
                            processing_status="PROCESSING", workflow_state="ASSOCIATION_PENDING",
                            uploader_id=up, department_id=DEPT_A))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            row = (await db.execute(select(IpRecord).where(IpRecord.id == rec2))).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
            await db.commit()

    asyncio.run(_create())
    try:
        r = client.get(f"/api/v1/faculty/{rec2}/status", headers=_h(client, _tok(world["ha"], "hod_admin", DEPT_A)))
        assert r.status_code == 404, r.text
    finally:
        asyncio.run(_delete())


def test_upload_status_parity_for_represented_hod(client, world):
    r = client.get(f"/api/v1/uploads/{world['rec']}/status", headers=_h(client, _tok(world["ha"], "hod_admin", DEPT_A)))
    assert r.status_code == 200, r.text
    r2 = client.get(f"/api/v1/uploads/{world['rec']}/status", headers=_h(client, _tok(world["hc"], "hod_admin", DEPT_C)))
    assert r2.status_code == 404, r2.text


def test_hod_without_department_still_403(client, world):
    r = client.get(f"/api/v1/faculty/{world['rec']}/status", headers=_h(client, _tok(world["ha"], "hod_admin", "")))
    assert r.status_code == 403, r.text

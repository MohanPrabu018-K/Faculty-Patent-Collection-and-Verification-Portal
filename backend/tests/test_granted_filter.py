"""Regression tests for the GRANTED filter (Issue 4).

Root cause: the granted-patents page sent ?verification_status=GRANTED, but
verification_status is a Postgres ENUM without GRANTED, so the query raised
InvalidTextRepresentationError -> 500 INTERNAL_ERROR. GRANTED lives on
workflow_state (a free String column).

Covers: GRANTED via workflow_state, VERIFIED, existing filters, invalid enum
values (422, never 500), pagination with GRANTED, empty GRANTED result, and
granted-row field completeness. All read-only GETs except a hermetic GRANTED
fixture record (created + deleted by the fixture; no production data used).
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
from app.models.base import IpRecord, User


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def granted_record():
    """Hermetic GRANTED record (the old hardcoded production fixture id is
    gone after the authorized production cleanup)."""
    uid = f"gf-u-{uuid.uuid4().hex[:6]}"
    rid = f"gf-rec-{uuid.uuid4().hex[:6]}"

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(id=uid, email=f"{uid}@example.test", official_email=f"{uid}@example.test",
                        password_hash=hash_password("secret123"), full_name=uid,
                        role="faculty", faculty_id=f"FAC-GF-{uid[:6]}".upper(),
                        status="active", is_active=True))
            db.add(IpRecord(id=rid, ip_type="PATENT", patent_number=f"GF-{uid[:6]}",
                            title="Granted filter fixture", verification_status="VERIFIED",
                            processing_status="COMPLETED", workflow_state="GRANTED",
                            uploader_id=uid, is_archived=False))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            row = (await db.execute(select(IpRecord).where(IpRecord.id == rid))).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
            u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        yield rid
    finally:
        asyncio.run(_delete())


def _tok(sub, role, dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


ADMIN = {"Authorization": f"Bearer {_tok('test-admin-002', 'super_admin')}"}


def _h(client, auth):
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "t"
        client.cookies.set("csrf_token", token)
    headers = dict(auth)
    headers["X-CSRF-Token"] = token
    return headers


def test_granted_workflow_filter_returns_granted_records(client):
    r = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert len(body["records"]) >= 1
    for row in body["records"]:
        assert row["workflow_state"] == "GRANTED"


def test_granted_workflow_filter_includes_known_granted_record(client, granted_record):
    r = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED&per_page=100", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    ids = [row["id"] for row in r.json()["records"]]
    assert granted_record in ids


def test_granted_record_row_carries_relevant_fields(client, granted_record):
    r = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED&per_page=100", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    row = next(row for row in r.json()["records"] if row["id"] == granted_record)
    for key in ("id", "ip_type", "title", "verification_status", "processing_status", "workflow_state"):
        assert key in row, f"granted row missing {key}"
    assert row["workflow_state"] == "GRANTED"


def test_verified_filter_still_works(client):
    r = client.get("/api/v1/admin/ip-records?verification_status=VERIFIED", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    for row in r.json()["records"]:
        assert row["verification_status"] == "VERIFIED"


def test_existing_filters_still_work(client):
    for params in (
        "?verification_status=VERIFICATION_REQUIRED",
        "?processing_status=COMPLETED",
        "?ip_type=PATENT",
    ):
        r = client.get(f"/api/v1/admin/ip-records{params}", headers=_h(client, ADMIN))
        assert r.status_code == 200, r.text


def test_granted_as_verification_status_is_422_not_500(client):
    r = client.get("/api/v1/admin/ip-records?verification_status=GRANTED", headers=_h(client, ADMIN))
    assert r.status_code == 422, r.text
    assert r.json().get("error") == "VALIDATION_ERROR"
    assert "INTERNAL_ERROR" not in r.text


def test_unknown_processing_status_is_422_not_500(client):
    r = client.get("/api/v1/admin/ip-records?processing_status=NOPE", headers=_h(client, ADMIN))
    assert r.status_code == 422, r.text
    assert r.json().get("error") == "VALIDATION_ERROR"


def test_pagination_with_granted_filter(client):
    r = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED&page=1&per_page=1", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page"] == 1
    assert body["per_page"] == 1
    assert len(body["records"]) <= 1
    r2 = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED&page=2&per_page=1", headers=_h(client, ADMIN))
    assert r2.status_code == 200, r2.text


def test_empty_granted_result(client):
    r = client.get(
        "/api/v1/admin/ip-records?workflow_state=GRANTED&search=zzz-no-such-record-zzz",
        headers=_h(client, ADMIN),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["records"] == []

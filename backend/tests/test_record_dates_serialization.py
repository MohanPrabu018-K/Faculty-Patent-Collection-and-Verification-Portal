"""Record date serialization (D-004 follow-through).

registration_date is extracted and persisted, but the faculty list/detail
payloads serialized only filing/grant/published dates, so designs never
showed their registration date. Both payloads now include it (ISO datetime,
same convention as filing_date); grant_date keeps its date-only contract.
"""
import asyncio
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import IpRecord, User


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _h(client, token):
    csrf = client.cookies.get("csrf_token") or "t"
    client.cookies.set("csrf_token", csrf)
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


def _tok(sub, role):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=sub, department_id="", full_name=sub,
    )


TAG = uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def world():
    up_id, rec_id = f"rd-up-{TAG}", f"rd-rec-{TAG}"

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(id=up_id, email=f"{up_id}@faculty.edu", full_name="RD Uploader",
                        password_hash=hash_password("secret123"), role="faculty",
                        faculty_id=up_id, is_active=True, status="active"))
            db.add(IpRecord(id=rec_id, ip_type="DESIGN_REGISTRATION", design_number=f"RD-DES-{TAG}",
                            title="RD design probe", verification_status="UNVERIFIED",
                            processing_status="COMPLETED", workflow_state="UPLOADED",
                            uploader_id=up_id,
                            registration_date=datetime(2025, 5, 21, 0, 0, 0),
                            grant_date=datetime(2025, 6, 1, 0, 0, 0)))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            row = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
            u = (await db.execute(select(User).where(User.id == up_id))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        yield {"rec": rec_id, "up": up_id}
    finally:
        asyncio.run(_delete())


def test_status_serializes_registration_date(client, world):
    r = client.get(f"/api/v1/faculty/{world['rec']}/status",
                   headers=_h(client, _tok(world["up"], "faculty")))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["registration_date"] == "2025-05-21T00:00:00", body
    # Grant-date date-only contract preserved; dates not interchanged.
    assert body["grant_date"] == "2025-06-01", body
    assert body["filing_date"] is None


def test_list_serializes_registration_date(client, world):
    r = client.get("/api/v1/faculty/my-records", headers=_h(client, _tok(world["up"], "faculty")))
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body.get("items", body.get("records", body if isinstance(body, list) else []))
    mine = [x for x in rows if x.get("id") == world["rec"] or x.get("record_id") == world["rec"]]
    assert mine, "created record missing from faculty list"
    assert mine[0]["registration_date"] == "2025-05-21T00:00:00", mine[0]

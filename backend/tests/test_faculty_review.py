"""Regression tests for the faculty Review & Confirm workflow.

The Review & Confirm UI on the faculty record detail page allows the
uploader to submit with zero edits as a pure confirmation, so the backend
must accept an empty corrections object (recording the review audit event)
— not just non-empty corrections. A previous frontend revision disabled
Submit until the user typed something, making confirmation impossible.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import AuditLog, FieldProvenance, IpRecord, User


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tok(sub, role="faculty"):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=sub, department_id="", full_name=sub,
    )


def _h(client, auth):
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "t"
        client.cookies.set("csrf_token", token)
    headers = dict(auth)
    headers["X-CSRF-Token"] = token
    return headers


OWNER_AUTH = {"Authorization": f"Bearer {_tok('tmp-review-owner')}"}
OTHER_AUTH = {"Authorization": f"Bearer {_tok('tmp-review-other')}"}


@pytest.fixture()
def review_record():
    """Synthetic uploader-owned record, removed after the test."""
    import asyncio

    owner_id = "tmp-review-owner"
    other_id = "tmp-review-other"
    rid = f"tmp-rev-{uuid.uuid4().hex[:10]}"

    async def _create():
        async with get_async_session_context() as db:
            for uid in (owner_id, other_id):
                exists = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
                if not exists:
                    db.add(
                        User(
                            id=uid,
                            email=f"{uid}@faculty.edu",
                            official_email=f"{uid}@faculty.edu",
                            password_hash=hash_password("ChangeMe123!"),
                            full_name=f"Review Probe {uid}",
                            role="faculty",
                            faculty_id=uid,
                            status="active",
                            is_active=True,
                        )
                    )
            db.add(
                IpRecord(
                    id=rid,
                    ip_type="DESIGN_REGISTRATION",
                    title="Review Probe Title",
                    design_number="999991-001",
                    uploader_id=owner_id,
                    processing_status="AWAITING_REVIEW",
                    verification_status="VERIFICATION_REQUIRED",
                    document_type="CERTIFICATE",
                )
            )
            await db.commit()

    async def _remove():
        async with get_async_session_context() as db:
            # Remove this test's row plus any orphan rows from
            # previously crashed runs (same synthetic uploader ids).
            orphans = (
                await db.execute(
                    select(IpRecord.id).where(IpRecord.uploader_id.in_([owner_id, other_id]))
                )
            ).scalars().all()
            stale = [i for i in orphans if i == rid or str(i).startswith("tmp-rev-")]
            if stale:
                await db.execute(delete(FieldProvenance).where(FieldProvenance.ip_record_id.in_(stale)))
                await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(stale)))
                await db.execute(delete(IpRecord).where(IpRecord.id.in_(stale)))
            await db.execute(
                delete(AuditLog).where((AuditLog.actor_id.in_([owner_id, other_id])))
            )
            await db.execute(delete(User).where(User.id.in_([owner_id, other_id])))
            await db.commit()

    asyncio.run(_create())
    try:
        yield rid
    finally:
        asyncio.run(_remove())


def test_empty_confirm_is_accepted_and_audited(client, review_record):
    r = client.post(
        f"/api/v1/faculty/{review_record}/review",
        headers=_h(client, OWNER_AUTH),
        json={"corrections": {}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reviewed"

    async def _audit():
        async with get_async_session_context() as db:
            return (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.action == "RECORD_REVIEWED",
                        AuditLog.target_id == review_record,
                    )
                )
            ).scalars().all()

    import asyncio

    rows = asyncio.run(_audit())
    assert rows, "empty confirmation must still leave a RECORD_REVIEWED audit row"


def test_correction_persists_provenance_and_field(client, review_record):
    import asyncio

    new_title = f"Review Probe Corrected {uuid.uuid4().hex[:6]}"
    r = client.post(
        f"/api/v1/faculty/{review_record}/review",
        headers=_h(client, OWNER_AUTH),
        json={"corrections": {"title": new_title}},
    )
    assert r.status_code == 200, r.text
    assert "title" in r.json()["corrected_fields"]

    async def _check():
        async with get_async_session_context() as db:
            record = (await db.execute(select(IpRecord).where(IpRecord.id == review_record))).scalar_one()
            prov = (
                await db.execute(
                    select(FieldProvenance).where(
                        FieldProvenance.ip_record_id == review_record,
                        FieldProvenance.field_name == "title",
                    )
                )
            ).scalars().all()
            return record.title, prov

    title, prov = asyncio.run(_check())
    assert title == new_title
    assert prov and all(p.source == "FACULTY_CONFIRMED" and p.status == "CONFIRMED" for p in prov)


def test_non_uploader_cannot_review(client, review_record):
    r = client.post(
        f"/api/v1/faculty/{review_record}/review",
        headers=_h(client, OTHER_AUTH),
        json={"corrections": {"title": "Intruder Title"}},
    )
    assert r.status_code == 403, r.text


def test_anonymous_cannot_review(client, review_record):
    # Pass CSRF (cookie echoed in header) so the request reaches the auth
    # layer, which must reject it as unauthenticated.
    token = client.cookies.get("csrf_token") or "t"
    client.cookies.set("csrf_token", token)
    r = client.post(
        f"/api/v1/faculty/{review_record}/review",
        headers={"X-CSRF-Token": token},
        json={"corrections": {}},
    )
    assert r.status_code in (401, 403), r.text

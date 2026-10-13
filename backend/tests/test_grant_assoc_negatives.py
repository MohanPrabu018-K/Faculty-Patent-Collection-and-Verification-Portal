"""Audit negatives: secondary association endpoint + grant gates.

A8:  POST /faculty/{id}/associate/{fid} previously inserted a duplicate row
     (and allowed self-requests). Now mirrors the primary endpoint contract:
     400 on self-request, 409 on a live pair.
C10: grant with a pending faculty approval -> GRANT_ASSOCIATION_INCOMPLETE.
C11: grant with an OPEN high-severity conflict -> GRANT_BLOCKED_DUPLICATE_CONFLICT.
C12: grant with incomplete processing / missing identifier -> GRANT_* codes.
C15: grant from REJECTED workflow state -> GRANT_TRANSITION_INVALID.

Hermetic: throwaway users/records/requests/cases, deleted by fixtures.
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
from app.models.base import AssociationRequest, ConflictCase, IpRecord, User


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


@pytest.fixture(scope="module")
def world():
    """Uploader + target faculty, a bare grantable record, and one PENDING
    uploader->target request (planted once for the duplicate/gate tests)."""
    up_id, tgt_id = f"an-up-{TAG}", f"an-tgt-{TAG}"
    rec_id = f"an-rec-{TAG}"

    async def _create():
        async with get_async_session_context() as db:
            for uid, name in ((up_id, "Audit Uploader"), (tgt_id, "Audit Target")):
                db.add(User(id=uid, email=f"{uid}@faculty.edu", full_name=name,
                            password_hash=hash_password("secret123"), role="faculty",
                            faculty_id=uid, is_active=True, status="active"))
            db.add(IpRecord(id=rec_id, ip_type="PATENT", patent_number=f"AN-PAT-{TAG}",
                            title="Audit negatives probe", verification_status="VERIFIED",
                            processing_status="COMPLETED", workflow_state="VERIFIED",
                            uploader_id=up_id))
            db.add(AssociationRequest(
                id=f"an-req-{TAG}", ip_record_id=rec_id,
                requesting_faculty_id=up_id, target_faculty_id=tgt_id,
                requester_id=up_id, recipient_id=tgt_id, status="PENDING"))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            for model, key in ((AssociationRequest, None), (ConflictCase, None)):
                rows = (await db.execute(select(model).where(
                    getattr(model, "ip_record_id") == rec_id))).scalars().all()
                for r in rows:
                    await db.delete(r)
            rec = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one_or_none()
            if rec is not None:
                await db.delete(rec)
            for uid in (up_id, tgt_id):
                u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
                if u is not None:
                    await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        yield {"rec": rec_id, "up": up_id, "tgt": tgt_id}
    finally:
        asyncio.run(_delete())


def _grant(client, rec_id):
    return client.post(f"/api/v1/admin/ip-records/{rec_id}/grant",
                       headers=_h(client, _tok("audit-admin", "super_admin")),
                       json={"confirm": True})


def test_secondary_duplicate_is_409(client, world):
    r = client.post(f"/api/v1/faculty/{world['rec']}/associate/{world['tgt']}",
                    headers=_h(client, _tok(world["up"], "faculty")))
    assert r.status_code == 409, r.text
    assert r.json().get("error") == "VALIDATION_ERROR"
    assert "already PENDING" in r.json().get("message", "")


def test_secondary_self_request_is_400(client, world):
    r = client.post(f"/api/v1/faculty/{world['rec']}/associate/{world['up']}",
                    headers=_h(client, _tok(world["up"], "faculty")))
    assert r.status_code == 400, r.text
    assert r.json().get("message") == "Self-association is not allowed"


def test_grant_blocked_by_pending_approval(client, world):
    # The PENDING request planted above gates the grant.
    r = _grant(client, world["rec"])
    assert r.status_code == 422, r.text
    assert r.json().get("error") == "GRANT_ASSOCIATION_INCOMPLETE"


def test_grant_blocked_by_open_conflict(client):
    rec_id, up_id = f"an-rec2-{TAG}", f"an-up2-{TAG}"

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(id=up_id, email=f"{up_id}@faculty.edu", full_name="Audit Up2",
                        password_hash=hash_password("secret123"), role="faculty",
                        faculty_id=up_id, is_active=True, status="active"))
            db.add(IpRecord(id=rec_id, ip_type="PATENT", patent_number=f"AN2-PAT-{TAG}",
                            title="Audit conflict probe", verification_status="VERIFIED",
                            processing_status="COMPLETED", workflow_state="VERIFIED",
                            uploader_id=up_id))
            db.add(ConflictCase(id=f"an-conf2-{TAG}", ip_record_id=rec_id,
                                conflict_type="DATA_MISMATCH", severity="HIGH",
                                description="Audit probe conflict 2", status="OPEN"))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            for row in (await db.execute(select(ConflictCase).where(
                    ConflictCase.ip_record_id == rec_id))).scalars().all():
                await db.delete(row)
            rec = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one_or_none()
            if rec is not None:
                await db.delete(rec)
            u = (await db.execute(select(User).where(User.id == up_id))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        r = _grant(client, rec_id)
        assert r.status_code == 422, r.text
        assert r.json().get("error") == "GRANT_BLOCKED_DUPLICATE_CONFLICT"
    finally:
        asyncio.run(_delete())


def test_grant_rejected_state_is_422(client):
    rec_id, up_id = f"an-rec3-{TAG}", f"an-up3-{TAG}"

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(id=up_id, email=f"{up_id}@faculty.edu", full_name="Audit Up3",
                        password_hash=hash_password("secret123"), role="faculty",
                        faculty_id=up_id, is_active=True, status="active"))
            db.add(IpRecord(id=rec_id, ip_type="PATENT", patent_number=f"AN3-PAT-{TAG}",
                            title="Audit rejected probe", verification_status="VERIFIED",
                            processing_status="COMPLETED", workflow_state="REJECTED",
                            uploader_id=up_id))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            rec = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one_or_none()
            if rec is not None:
                await db.delete(rec)
            u = (await db.execute(select(User).where(User.id == up_id))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        r = _grant(client, rec_id)
        assert r.status_code == 422, r.text
        assert r.json().get("error") == "GRANT_TRANSITION_INVALID"
    finally:
        asyncio.run(_delete())


def test_grant_processing_incomplete_and_identifier_missing(client):
    rec_id, up_id = f"an-rec4-{TAG}", f"an-up4-{TAG}"

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(id=up_id, email=f"{up_id}@faculty.edu", full_name="Audit Up4",
                        password_hash=hash_password("secret123"), role="faculty",
                        faculty_id=up_id, is_active=True, status="active"))
            db.add(IpRecord(id=rec_id, ip_type="PATENT", patent_number=f"AN4-PAT-{TAG}",
                            title="Audit processing probe", verification_status="VERIFIED",
                            processing_status="FAILED", workflow_state="FACULTY_ASSOCIATION_COMPLETE",
                            uploader_id=up_id))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            rec = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one_or_none()
            if rec is not None:
                await db.delete(rec)
            u = (await db.execute(select(User).where(User.id == up_id))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        r = _grant(client, rec_id)
        assert r.status_code == 422, r.text
        assert r.json().get("error") == "GRANT_PROCESSING_INCOMPLETE"

        async def _strip_id():
            async with get_async_session_context() as db:
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one()
                rec.patent_number = None
                rec.processing_status = "COMPLETED"
                await db.commit()

        asyncio.run(_strip_id())
        r2 = _grant(client, rec_id)
        assert r2.status_code == 422, r2.text
        assert r2.json().get("error") == "GRANT_IDENTIFIER_MISSING"
    finally:
        asyncio.run(_delete())

"""Concurrent Super Admin grant safety (Priority 1).

The grant endpoint reads the record with SELECT ... FOR UPDATE and commits
the state transition in a single transaction, with all 8 gates evaluated
while holding the row lock. Under READ COMMITTED the losing transaction
unblocks onto the winner's committed GRANTED row and is deterministically
rejected with GRANT_ALREADY_GRANTED.

These tests prove that against the REAL implementation and REAL PostgreSQL
transactions (threads + separate TestClient instances, no mocks):

A. two simultaneous grants, one record  -> exactly one 200 + one 422,
   single GRANTED state, exactly one PATENT_GRANTED audit row.
B. two simultaneous grants, two records -> both 200 (no global lock).
D. a rejected grant (422) leaves no state or audit trace (atomicity).

Hermetic: synthetic gc-* users/records, deleted by fixtures.
"""
import asyncio
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import AuditLog, IpRecord, User

TAG = uuid.uuid4().hex[:8]


def _tok(sub):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role="super_admin",
        faculty_id=sub, department_id="", full_name=sub,
    )


def _bearer():
    return {"Authorization": f"Bearer {_tok(f'gc-adm-{TAG}')}", "X-CSRF-Token": "t"}


@pytest.fixture(scope="module")
def world():
    """Three grantable records + uploader + a REAL super-admin actor.

    The admin JWT identity must exist in the DB: audit_log.actor_id has a
    foreign key to user.id, so grants by a phantom identity persist the
    grant but (by documented best-effort design) skip the audit row.
    """
    up_id, adm_id = f"gc-up-{TAG}", f"gc-adm-{TAG}"
    recs = [f"gc-rec{i}-{TAG}" for i in (1, 2, 3)]

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(id=up_id, email=f"{up_id}@faculty.edu", full_name="GC Uploader",
                        password_hash=hash_password("secret123"), role="faculty",
                        faculty_id=up_id, is_active=True, status="active"))
            db.add(User(id=adm_id, email=f"{adm_id}@faculty.edu", full_name="GC Admin",
                        password_hash=hash_password("secret123"), role="super_admin",
                        faculty_id=adm_id, is_active=True, status="active"))
            for i, rid in enumerate(recs, 1):
                db.add(IpRecord(id=rid, ip_type="PATENT", patent_number=f"GC-PAT-{TAG}-{i}",
                                title=f"GC race probe {i}", verification_status="VERIFIED",
                                processing_status="COMPLETED", workflow_state="VERIFIED",
                                uploader_id=up_id))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            for rid in recs:
                row = (await db.execute(select(IpRecord).where(IpRecord.id == rid))).scalar_one_or_none()
                if row is not None:
                    await db.delete(row)
                for a in (await db.execute(select(AuditLog).where(AuditLog.target_id == rid))).scalars().all():
                    await db.delete(a)
            for a in (await db.execute(select(AuditLog).where(AuditLog.actor_id == adm_id))).scalars().all():
                await db.delete(a)
            for uid in (up_id, adm_id):
                u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
                if u is not None:
                    await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        yield {"recs": recs, "up": up_id}
    finally:
        asyncio.run(_delete())


def _grant_once(rec_id, out, idx, barrier):
    # Separate client per thread: no shared cookie jar or portal state.
    with TestClient(app) as client:
        client.cookies.set("csrf_token", "t")
        barrier.wait(timeout=60)
        r = client.post(f"/api/v1/admin/ip-records/{rec_id}/grant",
                        headers=_bearer(), json={"confirm": True})
        out[idx] = (r.status_code, r.json())


def _race(rec_id, n=2):
    barrier = threading.Barrier(n)
    out = [None] * n
    threads = [threading.Thread(target=_grant_once, args=(rec_id, out, i, barrier)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=300)
    assert all(o is not None for o in out), "a racer thread did not finish"
    return out


def _audit_grants(rec_id):
    async def _q():
        async with get_async_session_context() as db:
            return (await db.execute(select(AuditLog).where(
                AuditLog.target_id == rec_id, AuditLog.action == "PATENT_GRANTED"))).scalars().all()

    return asyncio.run(_q())


def _workflow(rec_id):
    async def _q():
        async with get_async_session_context() as db:
            row = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one()
            return row.workflow_state

    return asyncio.run(_q())


def test_simultaneous_grant_single_winner(world):
    """Scenario A: exactly one 200 (GRANTED) + one deterministic 422."""
    rec = world["recs"][0]
    out = _race(rec)
    codes = sorted(o[0] for o in out)
    assert codes == [200, 422], out
    winner = next(o[1] for o in out if o[0] == 200)
    loser = next(o[1] for o in out if o[0] == 422)
    assert winner["workflow_state"] == "GRANTED"
    assert loser["error"] == "GRANT_ALREADY_GRANTED", loser
    # No duplicate/inconsistent outcome.
    assert _workflow(rec) == "GRANTED"
    assert len(_audit_grants(rec)) == 1


def test_simultaneous_grants_independent_records(world):
    """Scenario B: two records grant concurrently; both succeed (no global lock)."""
    rec2, rec3 = world["recs"][1], world["recs"][2]
    barrier = threading.Barrier(2)
    out = [None, None]

    def _one(rid, idx):
        with TestClient(app) as client:
            client.cookies.set("csrf_token", "t")
            barrier.wait(timeout=60)
            r = client.post(f"/api/v1/admin/ip-records/{rid}/grant",
                            headers=_bearer(), json={"confirm": True})
            out[idx] = (r.status_code, r.json())

    t1 = threading.Thread(target=_one, args=(rec2, 0))
    t2 = threading.Thread(target=_one, args=(rec3, 1))
    t1.start()
    t2.start()
    t1.join(timeout=300)
    t2.join(timeout=300)
    assert out[0] is not None and out[1] is not None
    assert out[0][0] == 200, out[0]
    assert out[1][0] == 200, out[1]
    assert _workflow(rec2) == "GRANTED" and _workflow(rec3) == "GRANTED"


def test_rejected_grant_leaves_no_trace(world):
    """Scenario D: a gate-rejected grant persists nothing (atomicity)."""
    rec_id, up_id = f"gc-rec4-{TAG}", f"gc-up4-{TAG}"

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(id=up_id, email=f"{up_id}@faculty.edu", full_name="GC Up4",
                        password_hash=hash_password("secret123"), role="faculty",
                        faculty_id=up_id, is_active=True, status="active"))
            db.add(IpRecord(id=rec_id, ip_type="PATENT", patent_number=f"GC4-PAT-{TAG}",
                            title="GC atomicity probe", verification_status="VERIFIED",
                            processing_status="COMPLETED", workflow_state="REJECTED",
                            uploader_id=up_id))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            for a in (await db.execute(select(AuditLog).where(AuditLog.target_id == rec_id))).scalars().all():
                await db.delete(a)
            row = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
            u = (await db.execute(select(User).where(User.id == up_id))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        with TestClient(app) as client:
            client.cookies.set("csrf_token", "t")
            r = client.post(f"/api/v1/admin/ip-records/{rec_id}/grant",
                            headers=_bearer(), json={"confirm": True})
        assert r.status_code == 422, r.text
        assert _workflow(rec_id) == "REJECTED"
        assert _audit_grants(rec_id) == []
    finally:
        asyncio.run(_delete())

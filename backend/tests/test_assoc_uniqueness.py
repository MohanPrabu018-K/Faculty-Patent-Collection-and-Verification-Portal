"""Association live-pair uniqueness (Priority 2 / A9).

Backstop: partial unique index ``uq_assoc_live_pair_per_record`` on
(record, requester, target) for live statuses only
(PENDING/CLARIFICATION_REQUESTED/ADMIN_REVIEW/ACCEPTED/APPROVED).
Terminal rows (REJECTED/NOT_ME/EXPIRED/CANCELLED) are history and must be
able to coexist with a newer live row (retry/reopen preserved).

Proves against REAL PostgreSQL behavior (threads, no mocks):
- repeated identical POST            -> 201 then deterministic 409
- concurrent identical POSTs         -> {201, 409}, exactly one live row, never 500
- concurrent send-alls               -> both 200, single row created across both
- existing ACCEPTED                  -> 409
- existing REJECTED                  -> 201 allowed, history row preserved
- different faculties / different patents -> independent 201s
- the backstop index is present in PostgreSQL

Hermetic: synthetic uq-* rows, deleted by fixtures.
"""
import asyncio
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_, select, text as sa_text

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import AssociationRequest, AuditLog, IpContributor, IpRecord, Notification, User

TAG = uuid.uuid4().hex[:8]
LIVE = ("PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW", "ACCEPTED", "APPROVED")


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


def _tok(sub, role="faculty"):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=sub, department_id="", full_name=sub,
    )


def _h(client, token):
    client.cookies.set("csrf_token", "t")
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": "t"}


@pytest.fixture(scope="module")
def world():
    up_id = f"uq-up-{TAG}"
    facs = [f"uq-f{i}-{TAG}" for i in (1, 2, 3)]
    recs = [f"uq-rec{i}-{TAG}" for i in (1, 2)]

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(id=up_id, email=f"{up_id}@faculty.edu", full_name="UQ Uploader",
                        password_hash=hash_password("secret123"), role="faculty",
                        faculty_id=up_id, is_active=True, status="active"))
            for fid in facs:
                db.add(User(id=fid, email=f"{fid}@faculty.edu", full_name=f"UQ {fid}",
                            password_hash=hash_password("secret123"), role="faculty",
                            faculty_id=fid, is_active=True, status="active"))
            for i, rid in enumerate(recs, 1):
                db.add(IpRecord(id=rid, ip_type="PATENT", patent_number=f"UQ-PAT-{TAG}-{i}",
                                title=f"UQ probe {i}", verification_status="VERIFICATION_REQUIRED",
                                processing_status="COMPLETED", workflow_state="FACULTY_ASSOCIATION_PENDING",
                                uploader_id=up_id))
            # facs[1] is a named internal contributor on recs[0], so the
            # send-all race has a real reviewer to cover.
            db.add(IpContributor(id=f"uq-c1-{TAG}", ip_record_id=recs[0], user_id=facs[1],
                                 name="UQ F2", contributor_type="INTERNAL_FACULTY",
                                 is_external=False, contributor_order=1))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            for rid in recs:
                for row in (await db.execute(select(AssociationRequest).where(
                        AssociationRequest.ip_record_id == rid))).scalars().all():
                    await db.delete(row)
                for crow in (await db.execute(select(IpContributor).where(
                        IpContributor.ip_record_id == rid))).scalars().all():
                    await db.delete(crow)
                rec = (await db.execute(select(IpRecord).where(IpRecord.id == rid))).scalar_one_or_none()
                if rec is not None:
                    await db.delete(rec)
            uids = [up_id, *facs]
            for n in (await db.execute(select(Notification).where(
                    Notification.user_id.in_(uids)))).scalars().all():
                await db.delete(n)
            for a in (await db.execute(select(AuditLog).where(
                    or_(AuditLog.actor_id.in_(uids),
                        AuditLog.entity_id.in_(uids),
                        AuditLog.target_id.in_(uids + recs))))).scalars().all():
                await db.delete(a)
            for uid in uids:
                u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
                if u is not None:
                    await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        yield {"up": up_id, "facs": facs, "recs": recs}
    finally:
        asyncio.run(_delete())


def _post_assoc(client, up_sub, target_faculty_id, rec_id):
    return client.post("/api/v1/associations/",
                       params={"recipient_faculty_id": target_faculty_id},
                       json={"record_id": rec_id},
                       headers=_h(client, _tok(up_sub)))


def _live_rows(rec_id):
    async def _q():
        async with get_async_session_context() as db:
            return (await db.execute(select(AssociationRequest).where(
                AssociationRequest.ip_record_id == rec_id,
                AssociationRequest.status.in_(LIVE)))).scalars().all()

    return asyncio.run(_q())


def test_index_present_in_postgres():
    async def _q():
        async with get_async_session_context() as db:
            return (await db.execute(sa_text(
                "select count(*) from pg_indexes "
                "where indexname='uq_assoc_live_pair_per_record'"))).scalar()

    assert asyncio.run(_q()) == 1


def test_repeated_post_is_409(world):
    with TestClient(app) as client:
        r1 = _post_assoc(client, world["up"], world["facs"][0], world["recs"][0])
        assert r1.status_code == 201, r1.text
        r2 = _post_assoc(client, world["up"], world["facs"][0], world["recs"][0])
        assert r2.status_code == 409, r2.text
        assert r2.json().get("error") == "VALIDATION_ERROR"


def test_concurrent_posts_single_row(world):
    rec, tgt = world["recs"][1], world["facs"][1]
    barrier = threading.Barrier(2)
    out = [None, None]

    def _one(idx):
        with TestClient(app) as client:
            barrier.wait(timeout=60)
            r = _post_assoc(client, world["up"], tgt, rec)
            out[idx] = r.status_code

    t1 = threading.Thread(target=_one, args=(0,))
    t2 = threading.Thread(target=_one, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=300)
    t2.join(timeout=300)
    assert out[0] is not None and out[1] is not None
    assert sorted(out) == [201, 409], out
    assert len(_live_rows(rec)) == 1


def test_concurrent_sendalls_single_row(world):
    rec = world["recs"][0]
    # recs[0] already carries facs[0]/PENDING from the repeat test; the race
    # below concerns facs[1].
    barrier = threading.Barrier(2)
    out = [None, None]

    def _one(idx):
        with TestClient(app) as client:
            client.cookies.set("csrf_token", "t")
            barrier.wait(timeout=60)
            r = client.post("/api/v1/associations/send-all", json={"record_id": rec},
                            headers={"Authorization": f"Bearer {_tok(world['up'])}",
                                     "X-CSRF-Token": "t"})
            out[idx] = (r.status_code, r.json())

    t1 = threading.Thread(target=_one, args=(0,))
    t2 = threading.Thread(target=_one, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=300)
    t2.join(timeout=300)
    assert out[0][0] == 200 and out[1][0] == 200, out
    created_total = sum(len(o[1].get("created", [])) for o in out)
    assert created_total <= 1, out
    assert len(_live_rows(rec)) == 2  # facs[0] (repeat test) + facs[1] (one of these)


def test_existing_accepted_blocks(world):
    rec, tgt = world["recs"][1], world["facs"][0]

    async def _accept():
        async with get_async_session_context() as db:
            db.add(AssociationRequest(
                id=f"uq-acc-{TAG}", ip_record_id=rec,
                requesting_faculty_id=world["up"], target_faculty_id=tgt,
                requester_id=world["up"], recipient_id=tgt, status="ACCEPTED"))
            await db.commit()

    async def _wipe():
        async with get_async_session_context() as db:
            row = (await db.execute(select(AssociationRequest).where(
                AssociationRequest.id == f"uq-acc-{TAG}"))).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
                await db.commit()

    asyncio.run(_accept())
    try:
        with TestClient(app) as client:
            r = _post_assoc(client, world["up"], tgt, rec)
            assert r.status_code == 409, r.text
    finally:
        asyncio.run(_wipe())


def test_rejected_history_allows_retry(world):
    rec, tgt = world["recs"][1], world["facs"][0]

    async def _seed_rejected():
        async with get_async_session_context() as db:
            db.add(AssociationRequest(
                id=f"uq-rej-{TAG}", ip_record_id=rec,
                requesting_faculty_id=world["up"], target_faculty_id=tgt,
                requester_id=world["up"], recipient_id=tgt, status="REJECTED"))
            await db.commit()

    async def _statuses():
        async with get_async_session_context() as db:
            return [r.status for r in (await db.execute(select(AssociationRequest).where(
                AssociationRequest.ip_record_id == rec,
                AssociationRequest.target_faculty_id == tgt))).scalars().all()]

    asyncio.run(_seed_rejected())
    try:
        with TestClient(app) as client:
            r = _post_assoc(client, world["up"], tgt, rec)
            assert r.status_code == 201, r.text
        statuses = asyncio.run(_statuses())
        # History preserved AND retry row live side by side.
        assert "REJECTED" in statuses and "PENDING" in statuses, statuses
    finally:
        async def _wipe():
            async with get_async_session_context() as db:
                for row in (await db.execute(select(AssociationRequest).where(
                        AssociationRequest.ip_record_id == rec,
                        AssociationRequest.target_faculty_id == tgt,
                        AssociationRequest.id.like("uq-%")))).scalars().all():
                    await db.delete(row)
                await db.commit()

        asyncio.run(_wipe())


def test_cross_combinations_independent(world):
    with TestClient(app) as client:
        # Different faculty, same patent.
        r = _post_assoc(client, world["up"], world["facs"][2], world["recs"][1])
        assert r.status_code == 201, r.text
        # Same faculty, different patent.
        r2 = _post_assoc(client, world["up"], world["facs"][2], world["recs"][0])
        assert r2.status_code == 201, r2.text

"""Association lifecycle regression tests (Bugs #1, #2, #11).

Exhaustive writer audit shows creation paths ALWAYS set status="PENDING"
and only an explicit recipient respond() transitions state. These tests lock
that contract end to end with hermetic fixtures (throwaway users + record;
everything created is deleted in teardown):

- CREATE -> 201 PENDING (primary endpoint; secondary faculty endpoint too)
- non-recipient accept -> 403 (no auto-accept path)
- recipient ACCEPT -> 200 ACCEPTED with responder metadata
- double accept -> rejected (409/422)
- recipient inbox + filtered GET reflect ACCEPTED, including with a fresh
  token (logout/login persistence), and the pending queue drops the row.
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
from app.models.base import (
    AssociationRequest,
    AuditLog,
    IpRecord,
    Notification,
    User,
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


def _headers(client, token):
    csrf = client.cookies.get("csrf_token")
    if csrf is None:
        csrf = "t"
        client.cookies.set("csrf_token", csrf)
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


@pytest.fixture()
def pair():
    """Throwaway sender + recipient faculty users."""
    tag = uuid.uuid4().hex[:8]
    sender = {"id": str(uuid.uuid4()), "email": f"sender.{tag}@gmail.com", "faculty_id": f"FAC-SND-{tag}"}
    recip = {"id": str(uuid.uuid4()), "email": f"recip.{tag}@gmail.com", "faculty_id": f"FAC-RCP-{tag}"}

    async def _create():
        async with get_async_session_context() as db:
            for u in (sender, recip):
                db.add(User(
                    id=u["id"], email=u["email"], full_name=f"Probe {u['faculty_id']}",
                    password_hash=hash_password("secret123"), role="faculty",
                    faculty_id=u["faculty_id"], is_active=True, status="active",
                ))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            ids = [sender["id"], recip["id"]]
            for a in (await db.execute(
                select(AuditLog).where(
                    (AuditLog.actor_id.in_(ids))
                    | (AuditLog.entity_id.in_(ids))
                    | (AuditLog.target_id.in_(ids))
                )
            )).scalars().all():
                await db.delete(a)
            for n in (await db.execute(
                select(Notification).where(Notification.user_id.in_(ids))
            )).scalars().all():
                await db.delete(n)
            for ar in (await db.execute(
                select(AssociationRequest).where(
                    (AssociationRequest.requesting_faculty_id.in_(ids))
                    | (AssociationRequest.requester_id.in_(ids))
                    | (AssociationRequest.target_faculty_id.in_(ids))
                    | (AssociationRequest.recipient_id.in_(ids))
                )
            )).scalars().all():
                await db.delete(ar)
            for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all():
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        yield {"sender": sender, "recip": recip}
    finally:
        asyncio.run(_delete())


@pytest.fixture()
def probe_record(pair):
    record_id = str(uuid.uuid4())

    async def _create():
        async with get_async_session_context() as db:
            db.add(IpRecord(
                id=record_id,
                ip_type="PATENT",
                patent_number=f"TEST-LC-{uuid.uuid4().hex[:8]}",
                title="Lifecycle probe record",
                verification_status="VERIFICATION_REQUIRED",
                workflow_state="NEEDS_REVIEW",
                uploader_id=pair["sender"]["id"],
            ))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            row = (await db.execute(select(IpRecord).where(IpRecord.id == record_id))).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
                await db.commit()

    asyncio.run(_create())
    try:
        yield record_id
    finally:
        asyncio.run(_delete())


def _sender_headers(client, pair):
    return _headers(client, _tok(pair["sender"]["id"]))


def _recip_headers(client, pair):
    return _headers(client, _tok(pair["recip"]["id"]))


def test_create_returns_201_pending(client, pair, probe_record):
    r = client.post(
        f"/api/v1/associations/?recipient_faculty_id={pair['recip']['faculty_id']}",
        headers=_sender_headers(client, pair),
        json={"record_id": probe_record, "reason": "lifecycle probe"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["recipient_id"] == pair["recip"]["id"]


def test_secondary_create_endpoint_also_pending(client, pair, probe_record):
    r = client.post(
        f"/api/v1/faculty/{probe_record}/associate/{pair['recip']['faculty_id']}",
        headers=_sender_headers(client, pair),
        json={},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "PENDING"


def test_non_recipient_cannot_accept(client, pair, probe_record):
    created = client.post(
        f"/api/v1/associations/?recipient_faculty_id={pair['recip']['faculty_id']}",
        headers=_sender_headers(client, pair),
        json={"record_id": probe_record, "reason": "authz probe"},
    )
    assert created.status_code == 201, created.text
    assoc_id = created.json()["id"]
    # Sender (not recipient) attempts to accept -> forbidden.
    r = client.post(
        f"/api/v1/associations/{assoc_id}/respond?action=accepted",
        headers=_sender_headers(client, pair),
        json={"reason": "self-accept attempt"},
    )
    assert r.status_code in (401, 403), r.text
    # Still PENDING.
    listing = client.get("/api/v1/associations/", headers=_recip_headers(client, pair))
    row = next(a for a in listing.json()["associations"] if a["id"] == assoc_id)
    assert row["status"] == "PENDING"


def test_recipient_accept_persists_across_relogin(client, pair, probe_record):
    created = client.post(
        f"/api/v1/associations/?recipient_faculty_id={pair['recip']['faculty_id']}",
        headers=_sender_headers(client, pair),
        json={"record_id": probe_record, "reason": "persist probe"},
    )
    assert created.status_code == 201, created.text
    assoc_id = created.json()["id"]

    accept = client.post(
        f"/api/v1/associations/{assoc_id}/respond?action=accepted",
        headers=_recip_headers(client, pair),
        json={"reason": "looks good"},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == "ACCEPTED"

    # Double accept is rejected.
    again = client.post(
        f"/api/v1/associations/{assoc_id}/respond?action=accepted",
        headers=_recip_headers(client, pair),
        json={},
    )
    assert again.status_code in (409, 422), again.text

    # Inbox reflects ACCEPTED with responder metadata.
    inbox = client.get("/api/v1/associations/", headers=_recip_headers(client, pair))
    assert inbox.status_code == 200, inbox.text
    row = next(a for a in inbox.json()["associations"] if a["id"] == assoc_id)
    assert row["status"] == "ACCEPTED"
    assert row["responded_at"] is not None

    # Pending queue drops the row.
    pending = client.get("/api/v1/associations/pending", headers=_recip_headers(client, pair))
    assert pending.status_code == 200, pending.text
    assert all(a["id"] != assoc_id for a in pending.json()["requests"])

    # Fresh token (logout/login equivalent: stateless JWT, backend is source
    # of truth) sees the same persisted ACCEPTED state.
    fresh = _headers(client, _tok(pair["recip"]["id"]))
    relogin = client.get("/api/v1/associations/", headers=fresh)
    assert relogin.status_code == 200, relogin.text
    row2 = next(a for a in relogin.json()["associations"] if a["id"] == assoc_id)
    assert row2["status"] == "ACCEPTED"

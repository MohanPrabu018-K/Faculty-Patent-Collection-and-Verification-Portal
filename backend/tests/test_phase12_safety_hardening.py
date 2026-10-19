"""Phase 1.2 Safety Hardening Regression Tests.

Audit findings addressed:
  FIX 1 (MED-01 / 4A): Preserve human review decisions during pipeline reprocessing.
           _create_contributors must not blindly delete contributor rows whose
           source == 'HUMAN_REVIEW' or who have explicit audit confirmations/rejections.
           Unambiguous 1-to-1 matching preserves human decisions while refreshing OCR evidence.
           Ambiguous matches return to manual review.

  FIX 2 (SEC-01 / 4B): Validate manual target user selection.
           Reject silent misassociations of unrelated users (name similarity < 0.40 without
           explicit >= 10-char review notes). Inactive users and HOD accounts cannot be targets.
           Empty/malformed contributor names are safely rejected with 422.

  FIX 3 (SEC-02 / 4C): Lock identity review after verification.
           Reject identity review mutations with HTTP 409 Conflict if the record is already
           in a verified state (workflow_state in ('VERIFIED', 'GRANTED') or
           verification_status == 'VERIFIED').
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, delete

from app.core.config import app_settings
from app.core.database import get_async_session_context, get_session
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import (
    AssociationRequest,
    AuditLog,
    Department,
    IpContributor,
    IpRecord,
    User,
)
from app.services.identity_resolution import (
    calculate_name_similarity,
    normalize_name,
)
from app.workers.orchestrator_task import (
    _create_contributors,
    _is_human_reviewed,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tok(sub, role="faculty", dept="", fac=""):
    return generate_jwt_token(
        sub,
        app_settings.secret_key,
        app_settings.jwt_algorithm,
        minutes=30,
        email=f"{sub}@example.test",
        role=role,
        department_id=dept,
        faculty_id=fac,
    )


class DummyResult:
    def __init__(self, contributors, agent_outputs=None):
        self.contributors = contributors
        if agent_outputs is None:
            names = [c.get("name") for c in contributors if c.get("name")]
            first = contributors[0] if contributors else {}
            agent_outputs = [
                {
                    "agent_name": "OCRExtractionAgent",
                    "extracted_data": {
                        "inventors": names,
                        "contributor_designation": first.get("designation"),
                        "contributor_department": first.get("department"),
                        "institution": first.get("institution"),
                    },
                }
            ]
        self.agent_outputs = agent_outputs
        self.classification = "PATENT"


# ============================================================================
# FIX 1: Preserve Human Review Decisions During Reprocessing (MED-01)
# ============================================================================

@pytest.mark.asyncio
async def test_fix1_confirmed_human_review_survives_reprocessing():
    """Human-confirmed internal decision must survive pipeline reprocessing."""
    uid = str(uuid.uuid4())
    fid = f"FAC-{uuid.uuid4().hex[:6].upper()}"
    rid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    did = str(uuid.uuid4())

    async with get_async_session_context() as db:
        dept = Department(id=did, name=f"ECE Dept {uuid.uuid4().hex[:6]}", code=f"ECE{uuid.uuid4().hex[:4]}")
        db.add(dept)
        user = User(
            id=uid,
            faculty_id=fid,
            full_name="Dr. N. Devakirubai",
            email=f"{uid}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        db.add(user)
        rec = IpRecord(
            id=rid,
            ip_type="PATENT",
            title="Smart Sensor",
            uploader_id=uid,
            department_id=did,
            workflow_state="IDENTITY_REVIEW",
            verification_status="UNVERIFIED",
        )
        db.add(rec)
        # Contributor that was confirmed by a human reviewer
        contrib = IpContributor(
            id=cid,
            ip_record_id=rid,
            user_id=uid,
            name="Dr. Devakirubai Navulkumar",
            designation="Assistant Professor",
            department="ECE",
            contributor_type="INTERNAL_FACULTY",
            match_status="CONFIRMED_INTERNAL",
            source="HUMAN_REVIEW",
            is_external=False,
            author_position=1,
            contributor_order=0,
        )
        db.add(contrib)
        await db.commit()

    # Reprocess the record: pipeline extracts the same contributor name with refreshed OCR details
    dummy = DummyResult(
        contributors=[{
            "name": "Dr. Devakirubai Navulkumar",
            "designation": "Associate Professor",  # updated OCR
            "department": "Electronics & Communication",  # updated OCR
            "institution": "RPSIT",
        }]
    )

    sync_session = get_session()
    try:
        db_rec = sync_session.get(IpRecord, rid)
        _create_contributors(db_rec, dummy)
    finally:
        sync_session.close()

    # Verify that the human-confirmed contributor row survived and was NOT replaced
    async with get_async_session_context() as db:
        contribs = (
            await db.execute(select(IpContributor).where(IpContributor.ip_record_id == rid))
        ).scalars().all()
        assert len(contribs) == 1
        c = contribs[0]
        # ID and decision preserved!
        assert c.id == cid
        assert c.user_id == uid
        assert c.contributor_type == "INTERNAL_FACULTY"
        assert c.match_status == "CONFIRMED_INTERNAL"
        assert c.source == "HUMAN_REVIEW"
        assert c.is_external is False
        # OCR fields refreshed!
        assert c.designation == "Associate Professor"
        assert c.department == "Electronics & Communication"

        # Cleanup
        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.execute(delete(User).where(User.id == uid))
        await db.execute(delete(Department).where(Department.id == did))
        await db.commit()


@pytest.mark.asyncio
async def test_fix1_rejected_external_decision_survives_reprocessing():
    """Human-rejected external decision must survive pipeline reprocessing."""
    uid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    did = str(uuid.uuid4())

    async with get_async_session_context() as db:
        dept = Department(id=did, name="ECE Dept 2", code=f"EC2{uuid.uuid4().hex[:4]}")
        db.add(dept)
        user = User(
            id=uid,
            faculty_id=f"FAC-{uuid.uuid4().hex[:6].upper()}",
            full_name="Prof. Uploader",
            email=f"{uid}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        db.add(user)
        rec = IpRecord(
            id=rid,
            ip_type="PATENT",
            title="Quantum Circuit",
            uploader_id=uid,
            department_id=did,
            workflow_state="IDENTITY_REVIEW",
            verification_status="UNVERIFIED",
        )
        db.add(rec)
        # Contributor that was rejected by human reviewer as external
        contrib = IpContributor(
            id=cid,
            ip_record_id=rid,
            user_id=None,
            name="Prof. External Collaborator",
            contributor_type="EXTERNAL",
            match_status="CONFIRMED_EXTERNAL",
            source="HUMAN_REVIEW",
            is_external=True,
            author_position=1,
            contributor_order=0,
        )
        db.add(contrib)
        await db.commit()

    dummy = DummyResult(
        contributors=[{"name": "Prof. External Collaborator", "designation": "Guest Scientist"}]
    )

    sync_session = get_session()
    try:
        db_rec = sync_session.get(IpRecord, rid)
        _create_contributors(db_rec, dummy)
    finally:
        sync_session.close()

    async with get_async_session_context() as db:
        contribs = (
            await db.execute(select(IpContributor).where(IpContributor.ip_record_id == rid))
        ).scalars().all()
        assert len(contribs) == 1
        c = contribs[0]
        assert c.id == cid
        assert c.user_id is None
        assert c.contributor_type == "EXTERNAL"
        assert c.match_status == "CONFIRMED_EXTERNAL"
        assert c.is_external is True
        assert c.source == "HUMAN_REVIEW"

        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.execute(delete(User).where(User.id == uid))
        await db.execute(delete(Department).where(Department.id == did))
        await db.commit()


@pytest.mark.asyncio
async def test_fix1_changed_extracted_names_safe_handling():
    """If OCR extraction returns entirely different names, old decisions cannot safely apply."""
    uid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    did = str(uuid.uuid4())

    async with get_async_session_context() as db:
        dept = Department(id=did, name="ECE Dept 3", code=f"EC3{uuid.uuid4().hex[:4]}")
        db.add(dept)
        user = User(
            id=uid,
            faculty_id=f"FAC-{uuid.uuid4().hex[:6].upper()}",
            full_name="Prof. Uploader 3",
            email=f"{uid}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        db.add(user)
        rec = IpRecord(
            id=rid,
            ip_type="PATENT",
            title="Solar Inverter",
            uploader_id=uid,
            department_id=did,
            workflow_state="IDENTITY_REVIEW",
            verification_status="UNVERIFIED",
        )
        db.add(rec)
        contrib = IpContributor(
            id=cid,
            ip_record_id=rid,
            user_id=uid,
            name="Alice Walker",
            contributor_type="INTERNAL_FACULTY",
            match_status="CONFIRMED_INTERNAL",
            source="HUMAN_REVIEW",
            is_external=False,
            author_position=1,
            contributor_order=0,
        )
        db.add(contrib)
        await db.commit()

    # Reprocessing extracts a completely different person "Bob Dylan"
    dummy = DummyResult(
        contributors=[{"name": "Bob Dylan", "designation": "Researcher"}]
    )

    sync_session = get_session()
    try:
        db_rec = sync_session.get(IpRecord, rid)
        _create_contributors(db_rec, dummy)
    finally:
        sync_session.close()

    async with get_async_session_context() as db:
        contribs = (
            await db.execute(select(IpContributor).where(IpContributor.ip_record_id == rid))
        ).scalars().all()
        assert len(contribs) == 1
        c = contribs[0]
        # Old Alice Walker was cleaned up, Bob Dylan created with standard resolution
        assert c.name == "Bob Dylan"
        assert c.source != "HUMAN_REVIEW"
        assert c.id != cid

        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.execute(delete(User).where(User.id == uid))
        await db.execute(delete(Department).where(Department.id == did))
        await db.commit()


# ============================================================================
# FIX 2: Validate Manual Target User Selection (SEC-01)
# ============================================================================

@pytest.mark.asyncio
async def test_fix2_unrelated_target_user_rejected_without_notes(client):
    """Reviewer cannot submit an unrelated faculty member without >= 10 char explanatory notes."""
    uid1 = str(uuid.uuid4())
    uid2 = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    did = str(uuid.uuid4())

    async with get_async_session_context() as db:
        dept = Department(id=did, name="CSE Dept", code=f"CSE{uuid.uuid4().hex[:4]}")
        db.add(dept)
        # Uploader
        u1 = User(
            id=uid1,
            faculty_id="FAC-U1",
            full_name="Dr. Devakirubai Navulkumar",
            email=f"{uid1}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        # Completely unrelated faculty member
        u2 = User(
            id=uid2,
            faculty_id="FAC-U2",
            full_name="Dr. Rajesh Kumar Sharma",
            email=f"{uid2}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        db.add_all([u1, u2])
        rec = IpRecord(
            id=rid,
            ip_type="PATENT",
            title="Biofeedback Band",
            uploader_id=uid1,
            department_id=did,
            workflow_state="IDENTITY_REVIEW",
            verification_status="UNVERIFIED",
        )
        db.add(rec)
        contrib = IpContributor(
            id=cid,
            ip_record_id=rid,
            name="Dr. Devakirubai Navulkumar",
            contributor_type="UNKNOWN",
            match_status="PROBABLE_INTERNAL",
            source="CERTIFICATE_OCR",
            is_external=False,
            author_position=1,
            contributor_order=0,
        )
        db.add(contrib)
        await db.commit()

    token = _tok(uid1, role="faculty", dept=did, fac="FAC-U1")

    # 1. Attempt to associate Rajesh Kumar Sharma with no notes -> 422 IMPLAUSIBLE_CANDIDATE
    res = client.post(
        f"/api/v1/faculty/{rid}/contributors/{cid}/review",
        json={"action": "confirm", "user_id": uid2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422
    assert "IMPLAUSIBLE_CANDIDATE" in res.text or "not plausible" in res.text

    # 2. Attempt with short notes (< 10 chars) -> still rejected
    res2 = client.post(
        f"/api/v1/faculty/{rid}/contributors/{cid}/review",
        json={"action": "confirm", "user_id": uid2, "notes": "typo"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res2.status_code == 422

    # 3. Attempt with genuine explanatory notes (>= 10 chars) -> accepted
    res3 = client.post(
        f"/api/v1/faculty/{rid}/contributors/{cid}/review",
        json={"action": "confirm", "user_id": uid2, "notes": "Name changed legally after marriage per college HR file"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res3.status_code == 200
    data = res3.json()
    assert data["status"] == "success"
    assert data["matched_user_id"] == uid2

    # Cleanup
    async with get_async_session_context() as db:
        await db.execute(delete(AssociationRequest).where(AssociationRequest.ip_record_id == rid))
        await db.execute(delete(AuditLog).where(AuditLog.target_id == cid))
        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.execute(delete(User).where(User.id.in_([uid1, uid2])))
        await db.execute(delete(Department).where(Department.id == did))
        await db.commit()


@pytest.mark.asyncio
async def test_fix2_inactive_target_user_rejected(client):
    """Target user must be active; inactive users must be rejected."""
    uid1 = str(uuid.uuid4())
    uid2 = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    did = str(uuid.uuid4())

    async with get_async_session_context() as db:
        dept = Department(id=did, name="IT Dept", code=f"IT{uuid.uuid4().hex[:4]}")
        db.add(dept)
        u1 = User(
            id=uid1,
            faculty_id="FAC-U1",
            full_name="Prof. Active Uploader",
            email=f"{uid1}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        u2 = User(
            id=uid2,
            faculty_id="FAC-U2",
            full_name="Prof. Former Faculty",
            email=f"{uid2}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=False,  # Inactive account
        )
        db.add_all([u1, u2])
        rec = IpRecord(
            id=rid,
            ip_type="PATENT",
            title="Smart Grid",
            uploader_id=uid1,
            department_id=did,
            workflow_state="IDENTITY_REVIEW",
            verification_status="UNVERIFIED",
        )
        db.add(rec)
        contrib = IpContributor(
            id=cid,
            ip_record_id=rid,
            name="Prof. Former Faculty",
            contributor_type="UNKNOWN",
            match_status="PROBABLE_INTERNAL",
            source="CERTIFICATE_OCR",
            is_external=False,
            author_position=1,
            contributor_order=0,
        )
        db.add(contrib)
        await db.commit()

    token = _tok(uid1, role="faculty", dept=did, fac="FAC-U1")
    res = client.post(
        f"/api/v1/faculty/{rid}/contributors/{cid}/review",
        json={"action": "confirm", "user_id": uid2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422
    assert "inactive" in res.text.lower() or "not found" in res.text.lower()

    async with get_async_session_context() as db:
        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.execute(delete(User).where(User.id.in_([uid1, uid2])))
        await db.execute(delete(Department).where(Department.id == did))
        await db.commit()


@pytest.mark.asyncio
async def test_fix2_empty_or_malformed_contributor_name_rejected(client):
    """Empty or whitespace contributor name cannot be confirmed as faculty."""
    uid1 = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    did = str(uuid.uuid4())

    async with get_async_session_context() as db:
        dept = Department(id=did, name="IT Dept", code=f"IT{uuid.uuid4().hex[:4]}")
        db.add(dept)
        u1 = User(
            id=uid1,
            faculty_id="FAC-U1",
            full_name="Prof. Active Uploader",
            email=f"{uid1}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        db.add(u1)
        rec = IpRecord(
            id=rid,
            ip_type="PATENT",
            title="Smart Grid",
            uploader_id=uid1,
            department_id=did,
            workflow_state="IDENTITY_REVIEW",
            verification_status="UNVERIFIED",
        )
        db.add(rec)
        # Contributor with malformed/whitespace name
        contrib = IpContributor(
            id=cid,
            ip_record_id=rid,
            name="   ",
            contributor_type="UNKNOWN",
            match_status="PROBABLE_INTERNAL",
            source="CERTIFICATE_OCR",
            is_external=False,
            author_position=1,
            contributor_order=0,
        )
        db.add(contrib)
        await db.commit()

    token = _tok(uid1, role="faculty", dept=did, fac="FAC-U1")
    res = client.post(
        f"/api/v1/faculty/{rid}/contributors/{cid}/review",
        json={"action": "confirm", "user_id": uid1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422
    assert "INVALID_CONTRIBUTOR_NAME" in res.text

    async with get_async_session_context() as db:
        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.execute(delete(User).where(User.id == uid1))
        await db.execute(delete(Department).where(Department.id == did))
        await db.commit()


# ============================================================================
# FIX 3: Lock Identity Review After Verification (SEC-02)
# ============================================================================

@pytest.mark.asyncio
async def test_fix3_locked_when_workflow_state_verified(client):
    """Mutating contributor identity on a record with workflow_state='VERIFIED' returns 409."""
    uid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    did = str(uuid.uuid4())

    async with get_async_session_context() as db:
        dept = Department(id=did, name="Mech Dept", code=f"ME{uuid.uuid4().hex[:4]}")
        db.add(dept)
        user = User(
            id=uid,
            faculty_id="FAC-M1",
            full_name="Dr. Verified Faculty",
            email=f"{uid}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        db.add(user)
        rec = IpRecord(
            id=rid,
            ip_type="PATENT",
            title="Turbine Blade",
            uploader_id=uid,
            department_id=did,
            workflow_state="VERIFIED",  # Already verified
            verification_status="UNVERIFIED",
        )
        db.add(rec)
        contrib = IpContributor(
            id=cid,
            ip_record_id=rid,
            name="Dr. Verified Faculty",
            contributor_type="INTERNAL_FACULTY",
            match_status="CONFIRMED_INTERNAL",
            source="CERTIFICATE_OCR",
            is_external=False,
            author_position=1,
            contributor_order=0,
        )
        db.add(contrib)
        await db.commit()

    token = _tok(uid, role="faculty", dept=did, fac="FAC-M1")
    res = client.post(
        f"/api/v1/faculty/{rid}/contributors/{cid}/review",
        json={"action": "reject"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 409
    assert "RECORD_ALREADY_VERIFIED" in res.text

    # Verify no mutation occurred
    async with get_async_session_context() as db:
        c = await db.get(IpContributor, cid)
        assert c.match_status == "CONFIRMED_INTERNAL"
        assert c.contributor_type == "INTERNAL_FACULTY"

        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.execute(delete(User).where(User.id == uid))
        await db.execute(delete(Department).where(Department.id == did))
        await db.commit()


@pytest.mark.asyncio
async def test_fix3_locked_when_verification_status_verified(client):
    """Mutating contributor identity on a record with verification_status='VERIFIED' returns 409."""
    uid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    did = str(uuid.uuid4())

    async with get_async_session_context() as db:
        dept = Department(id=did, name="Mech Dept", code=f"ME{uuid.uuid4().hex[:4]}")
        db.add(dept)
        user = User(
            id=uid,
            faculty_id="FAC-M2",
            full_name="Dr. Second Faculty",
            email=f"{uid}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        db.add(user)
        rec = IpRecord(
            id=rid,
            ip_type="PATENT",
            title="Composite Wing",
            uploader_id=uid,
            department_id=did,
            workflow_state="FACULTY_ASSOCIATION_COMPLETE",
            verification_status="VERIFIED",  # Verified status
        )
        db.add(rec)
        contrib = IpContributor(
            id=cid,
            ip_record_id=rid,
            name="Dr. Second Faculty",
            contributor_type="INTERNAL_FACULTY",
            match_status="CONFIRMED_INTERNAL",
            source="CERTIFICATE_OCR",
            is_external=False,
            author_position=1,
            contributor_order=0,
        )
        db.add(contrib)
        await db.commit()

    token = _tok(uid, role="faculty", dept=did, fac="FAC-M2")
    res = client.post(
        f"/api/v1/faculty/{rid}/contributors/{cid}/review",
        json={"action": "confirm", "user_id": uid},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 409
    assert "RECORD_ALREADY_VERIFIED" in res.text

    async with get_async_session_context() as db:
        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.execute(delete(User).where(User.id == uid))
        await db.execute(delete(Department).where(Department.id == did))
        await db.commit()


@pytest.mark.asyncio
async def test_fix3_repeated_request_after_verification_returns_409(client):
    """Subsequent requests after reaching verified state are rejected and do not create audit events."""
    uid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    did = str(uuid.uuid4())

    async with get_async_session_context() as db:
        dept = Department(id=did, name="Civil Dept", code=f"CE{uuid.uuid4().hex[:4]}")
        db.add(dept)
        user = User(
            id=uid,
            faculty_id="FAC-C1",
            full_name="Dr. Concrete Expert",
            email=f"{uid}@test.edu",
            password_hash=hash_password("Pass123!"),
            role="faculty",
            department_id=did,
            is_active=True,
        )
        db.add(user)
        rec = IpRecord(
            id=rid,
            ip_type="PATENT",
            title="Self Healing Concrete",
            uploader_id=uid,
            department_id=did,
            workflow_state="GRANTED",  # GRANTED state
            verification_status="VERIFIED",
        )
        db.add(rec)
        contrib = IpContributor(
            id=cid,
            ip_record_id=rid,
            name="Dr. Concrete Expert",
            contributor_type="INTERNAL_FACULTY",
            match_status="CONFIRMED_INTERNAL",
            source="HUMAN_REVIEW",
            is_external=False,
            author_position=1,
            contributor_order=0,
        )
        db.add(contrib)
        await db.commit()

    token = _tok(uid, role="faculty", dept=did, fac="FAC-C1")

    # Send 3 repeated requests
    for _ in range(3):
        res = client.post(
            f"/api/v1/faculty/{rid}/contributors/{cid}/review",
            json={"action": "confirm", "user_id": uid},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 409

    # Verify no audit log was created by the rejected requests
    async with get_async_session_context() as db:
        audits = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.target_id == cid,
                    AuditLog.action.in_(("CONTRIBUTOR_IDENTITY_CONFIRMED", "CONTRIBUTOR_IDENTITY_REJECTED")),
                )
            )
        ).scalars().all()
        assert len(audits) == 0

        await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == rid))
        await db.execute(delete(IpRecord).where(IpRecord.id == rid))
        await db.execute(delete(User).where(User.id == uid))
        await db.execute(delete(Department).where(Department.id == did))
        await db.commit()

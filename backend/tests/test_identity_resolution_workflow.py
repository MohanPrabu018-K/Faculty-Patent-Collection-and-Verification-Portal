"""Phase 1 Regression Tests: Safe Faculty Identity Resolution & Review Workflow.

Covers:
TEST 1 — Exact Match (high-confidence unambiguous internal)
TEST 2 — Initial Expansion ("Dr. Devakirubai Navulkumar" vs "Dr. N. Devakirubai" -> PROBABLE_INTERNAL requiring review)
TEST 3 — Token Order (reordered tokens and initials)
TEST 4 — Similar Names (similar names must not misassociate; ambiguous detection)
TEST 5 — No Candidate (unrelated contributor -> CONFIRMED_EXTERNAL)
TEST 6 — Probable Match Persistence (candidate identity, original name, score, match_status persist in DB)
TEST 7 — Workflow Gate (PROBABLE_INTERNAL prevents premature FACULTY_ASSOCIATION_COMPLETE / VERIFIED)
TEST 8 — Reviewer Confirmation (authorized uploader/HOD confirms identity -> CONFIRMED_INTERNAL + audit event)
TEST 9 — Reviewer Rejection (rejected candidate -> CONFIRMED_EXTERNAL, unlinked from user_id + audit event)
TEST 10 — Association Idempotency (repeated confirmation requests do not duplicate associations)
TEST 11 — Authorization (unauthorized users cannot review or mutate identity decisions)
"""

import asyncio
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, delete

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import (
    AssociationRequest,
    AuditLog,
    Department,
    IpContributor,
    IpRecord,
    MasterIpContributor,
    MasterIpRecord,
    User,
)
from app.services.identity_resolution import (
    IdentityCandidate,
    IdentityResolutionService,
    MatchConfidence,
    calculate_name_similarity,
    normalize_name,
)
from app.services.workflow import WorkflowState
from app.workers.orchestrator_task import _resolve_contributor_match


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
        faculty_id=fac or sub,
        department_id=dept,
        full_name=sub,
    )


def _headers(client, token):
    csrf = client.cookies.get("csrf_token")
    if csrf is None:
        csrf = "t"
        client.cookies.set("csrf_token", csrf)
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


# =========================================================================
# TEST 1 — Exact Match
# =========================================================================
def test_exact_match():
    """An exact, unambiguous institutional faculty name should be identified correctly."""
    service = IdentityResolutionService()
    sim = calculate_name_similarity("Dr. Mohan Prabu", "Dr. Mohan Prabu")
    assert sim == 1.0

    cand = IdentityCandidate(
        user_id="u-1",
        faculty_id="FAC-001",
        full_name="Mohan Prabu",
        email="mohan@college.edu",
        name_similarity=1.0,
        overall_confidence=0.95,
        institution_match=True,
    )
    status, req_review, reason = service._determine_match_status([cand])
    assert status == "CONFIRMED_INTERNAL"
    assert req_review is False
    assert reason is None


# =========================================================================
# TEST 2 — Initial Expansion
# =========================================================================
def test_initial_expansion():
    """Compare 'Dr. Devakirubai Navulkumar' and 'Dr. N. Devakirubai'.
    The system should preserve the plausible candidate for review rather than
    discarding it or automatically confirming it."""
    service = IdentityResolutionService()
    extracted = "Dr. Devakirubai Navulkumar"
    institutional = "Dr. N. Devakirubai"

    sim = calculate_name_similarity(extracted, institutional)
    # Token-level bipartite alignment should match 'N' with 'Navulkumar' and 'Devakirubai' with 'Devakirubai'
    assert sim >= 0.85, f"Expected high similarity with initial expansion, got {sim}"

    # Overall confidence when certificate has no institutional header
    cand = IdentityCandidate(
        user_id="u-devakirubai",
        faculty_id="FAC-DEV",
        full_name="Dr. N. Devakirubai",
        email="devakirubai@college.edu",
        name_similarity=sim,
        institution_match=False,
    )
    # Overall confidence is rebalanced
    cand.overall_confidence = service._calculate_overall_confidence(cand)
    assert cand.overall_confidence >= 0.40, f"Expected confidence >= 0.40, got {cand.overall_confidence}"

    status, req_review, reason = service._determine_match_status([cand])
    # Must be PROBABLE_INTERNAL requiring review (NOT confirmed, NOT discarded)
    assert status == "PROBABLE_INTERNAL"
    assert req_review is True
    assert "Probable internal faculty" in (reason or "")

    # Orchestrator resolver must preserve the user_id and confidence
    entity = {
        "contributor_name": extracted,
        "match_status": status,
        "best_match": {
            "id": "u-devakirubai",
            "faculty_id": "FAC-DEV",
            "name": "Dr. N. Devakirubai",
            "confidence": cand.overall_confidence,
        },
    }
    matched_id, conf, m_status, c_type, is_ext = _resolve_contributor_match(extracted, [entity])
    assert matched_id == "u-devakirubai", "Candidate user_id must be preserved"
    assert m_status == "PROBABLE_INTERNAL"
    assert is_ext is False, "Candidate must NOT be marked external"
    assert c_type == "UNKNOWN", "Type must remain UNKNOWN until confirmed"


# =========================================================================
# TEST 3 — Token Order
# =========================================================================
def test_token_order():
    """Test reasonable reordered name tokens and initials."""
    # Full token reordering
    assert calculate_name_similarity("Navulkumar Devakirubai", "Devakirubai Navulkumar") == 0.98

    # Reordered initials and honorifics
    sim1 = calculate_name_similarity("Dr. N. Devakirubai", "Dr. Devakirubai N.")
    assert sim1 >= 0.95

    # Reverse token order with initial expansion
    sim2 = calculate_name_similarity("Navulkumar Devakirubai", "Dr. N. Devakirubai")
    assert sim2 >= 0.85


# =========================================================================
# TEST 4 — Similar Names
# =========================================================================
def test_similar_names_no_misassociation():
    """Two different faculty with similar names must not be automatically associated with the wrong person."""
    service = IdentityResolutionService()

    # Contributor "Dr. Ramesh Patel" vs faculty "Ramesh Kumar"
    sim_diff = calculate_name_similarity("Dr. Ramesh Patel", "Dr. Ramesh Kumar")
    assert sim_diff < 0.65, f"Different surnames should not match closely, got {sim_diff}"

    # Ambiguity case: two candidates with close confidence scores
    cand1 = IdentityCandidate(
        user_id="u-1",
        faculty_id="FAC-1",
        full_name="Ramesh Kumar",
        email="rk@college.edu",
        name_similarity=0.72,
        overall_confidence=0.68,
    )
    cand2 = IdentityCandidate(
        user_id="u-2",
        faculty_id="FAC-2",
        full_name="Ramesh K.",
        email="rk2@college.edu",
        name_similarity=0.70,
        overall_confidence=0.66,
    )

    status, req_review, reason = service._determine_match_status([cand1, cand2])
    assert status == "AMBIGUOUS_INTERNAL"
    assert req_review is True
    assert "Multiple plausible faculty candidates" in (reason or "")


# =========================================================================
# TEST 5 — No Candidate
# =========================================================================
def test_no_candidate_confirmed_external():
    """A contributor with no plausible internal candidate must follow external-contributor rules safely."""
    service = IdentityResolutionService()
    status, req_review, reason = service._determine_match_status([])
    assert status == "CONFIRMED_EXTERNAL"
    assert req_review is False

    # Orchestrator resolver with empty entities
    matched_id, conf, m_status, c_type, is_ext = _resolve_contributor_match("External Researcher", [])
    assert matched_id is None
    assert m_status == "CONFIRMED_EXTERNAL"
    assert c_type == "EXTERNAL"
    assert is_ext is True


# =========================================================================
# FIXTURE FOR PERSISTENCE AND API TESTS
# =========================================================================
@pytest.fixture()
def identity_fixture():
    """Creates isolated test users, record, and contributors for persistence and API tests."""
    tag = uuid.uuid4().hex[:8]
    uploader_id = f"uploader-{tag}"
    candidate_id = f"candidate-{tag}"
    outsider_id = f"outsider-{tag}"
    hod_id = f"hod-{tag}"
    record_id = f"rec-{tag}"
    contrib_id = f"contrib-{tag}"
    dept_id = f"dept-{tag}"

    async def _setup():
        async with get_async_session_context() as db:
            dept = Department(id=dept_id, name=f"Dept {tag}", code=f"D{tag[:4].upper()}")
            db.add(dept)

            u_uploader = User(
                id=uploader_id,
                email=f"uploader.{tag}@college.edu",
                full_name=f"Uploader Faculty {tag}",
                password_hash=hash_password("Pass123!"),
                role="faculty",
                faculty_id=f"FAC-UPL-{tag}",
                department_id=dept_id,
                is_active=True,
                status="active",
            )
            u_cand = User(
                id=candidate_id,
                email=f"candidate.{tag}@college.edu",
                full_name=f"Dr. N. Devakirubai {tag}",
                password_hash=hash_password("Pass123!"),
                role="faculty",
                faculty_id=f"FAC-CAND-{tag}",
                department_id=dept_id,
                is_active=True,
                status="active",
            )
            u_out = User(
                id=outsider_id,
                email=f"outsider.{tag}@college.edu",
                full_name=f"Outsider Faculty {tag}",
                password_hash=hash_password("Pass123!"),
                role="faculty",
                faculty_id=f"FAC-OUT-{tag}",
                department_id=dept_id,
                is_active=True,
                status="active",
            )
            u_hod = User(
                id=hod_id,
                email=f"hod.{tag}@college.edu",
                full_name=f"HOD User {tag}",
                password_hash=hash_password("Pass123!"),
                role="hod_admin",
                faculty_id=f"FAC-HOD-{tag}",
                department_id=dept_id,
                is_active=True,
                status="active",
            )
            db.add_all([u_uploader, u_cand, u_out, u_hod])

            rec = IpRecord(
                id=record_id,
                ip_type="DESIGN_REGISTRATION",
                title=f"Test Patent {tag}",
                design_number=f"410787-{tag[:3]}",
                uploader_id=uploader_id,
                department_id=dept_id,
                processing_status="AWAITING_REVIEW",
                verification_status="VERIFICATION_REQUIRED",
                workflow_state="IDENTITY_REVIEW",
            )
            db.add(rec)

            contrib = IpContributor(
                id=contrib_id,
                ip_record_id=record_id,
                name="Dr. Devakirubai Navulkumar",
                contributor_type="UNKNOWN",
                user_id=candidate_id,
                match_confidence=0.72,
                match_status="PROBABLE_INTERNAL",
                is_external=False,
                contributor_order=1,
            )
            db.add(contrib)
            await db.commit()

    async def _cleanup():
        async with get_async_session_context() as db:
            await db.execute(delete(AssociationRequest).where(AssociationRequest.ip_record_id == record_id))
            await db.execute(delete(AuditLog).where(AuditLog.entity_id.in_([record_id, contrib_id])))
            await db.execute(delete(IpContributor).where(IpContributor.ip_record_id == record_id))
            await db.execute(delete(IpRecord).where(IpRecord.id == record_id))
            await db.execute(delete(User).where(User.id.in_([uploader_id, candidate_id, outsider_id, hod_id])))
            await db.execute(delete(Department).where(Department.id == dept_id))
            await db.commit()

    asyncio.run(_setup())
    yield {
        "record_id": record_id,
        "contrib_id": contrib_id,
        "uploader_id": uploader_id,
        "candidate_id": candidate_id,
        "outsider_id": outsider_id,
        "hod_id": hod_id,
        "dept_id": dept_id,
    }
    asyncio.run(_cleanup())


# =========================================================================
# TEST 6 — Probable Match Persistence
# =========================================================================
def test_probable_match_persistence(identity_fixture):
    """Confirm candidate identity, original name, score, and review status survive database persistence and reload."""
    async def _check():
        async with get_async_session_context() as db:
            row = (
                await db.execute(
                    select(IpContributor).where(
                        IpContributor.id == identity_fixture["contrib_id"]
                    )
                )
            ).scalar_one()

            assert row.name == "Dr. Devakirubai Navulkumar"
            assert row.match_status == "PROBABLE_INTERNAL"
            assert row.user_id == identity_fixture["candidate_id"]
            assert abs(row.match_confidence - 0.72) < 0.001
            assert row.is_external is False
            assert row.contributor_type == "UNKNOWN"

    asyncio.run(_check())


# =========================================================================
# TEST 7 — Workflow Gate
# =========================================================================
def test_workflow_gate(identity_fixture):
    """An unresolved probable or ambiguous identity must not cause the record to be marked fully institutionally verified."""
    async def _check():
        async with get_async_session_context() as db:
            rec = (
                await db.execute(
                    select(IpRecord).where(IpRecord.id == identity_fixture["record_id"])
                )
            ).scalar_one()

            # Record must remain in IDENTITY_REVIEW and VERIFICATION_REQUIRED
            assert rec.workflow_state == "IDENTITY_REVIEW"
            assert rec.verification_status != "VERIFIED"

            # Check verification guard
            from app.api.verification import _pending_internal_approvals
            has_pending = await _pending_internal_approvals(db, rec)
            assert len(has_pending) > 0, "Unresolved probable contributors must block pending approvals check"

    asyncio.run(_check())


# =========================================================================
# TEST 8 — Reviewer Confirmation
# =========================================================================
def test_reviewer_confirmation(client, identity_fixture):
    """Only an authorized reviewer may confirm an identity. On confirmation, contributor becomes CONFIRMED_INTERNAL and audit log is recorded."""
    token = _tok(identity_fixture["uploader_id"], role="faculty")
    headers = _headers(client, token)

    url = f"/api/v1/faculty/{identity_fixture['record_id']}/contributors/{identity_fixture['contrib_id']}/review"
    res = client.post(url, json={"action": "confirm", "notes": "Verified faculty member"}, headers=headers)
    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}: {res.text}"
    body = res.json()
    assert body["match_status"] == "CONFIRMED_INTERNAL"
    assert body["is_external"] is False

    # Verify DB state
    async def _check():
        async with get_async_session_context() as db:
            contrib = (
                await db.execute(
                    select(IpContributor).where(IpContributor.id == identity_fixture["contrib_id"])
                )
            ).scalar_one()
            assert contrib.match_status == "CONFIRMED_INTERNAL"
            assert contrib.contributor_type == "INTERNAL_FACULTY"
            assert contrib.user_id == identity_fixture["candidate_id"]

            rec = (
                await db.execute(
                    select(IpRecord).where(IpRecord.id == identity_fixture["record_id"])
                )
            ).scalar_one()
            assert rec.workflow_state == "FACULTY_ASSOCIATION_PENDING"

            audit = (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.entity_id == identity_fixture["contrib_id"],
                        AuditLog.action == "CONTRIBUTOR_IDENTITY_CONFIRMED",
                    )
                )
            ).scalar_one_or_none()
            assert audit is not None
            assert audit.actor_id == identity_fixture["uploader_id"]

    asyncio.run(_check())


# =========================================================================
# TEST 9 — Reviewer Rejection
# =========================================================================
def test_reviewer_rejection(client, identity_fixture):
    """A rejected candidate must not remain silently associated."""
    token = _tok(identity_fixture["uploader_id"], role="faculty")
    headers = _headers(client, token)

    url = f"/api/v1/faculty/{identity_fixture['record_id']}/contributors/{identity_fixture['contrib_id']}/review"
    res = client.post(url, json={"action": "reject", "notes": "Different person with similar name"}, headers=headers)
    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}: {res.text}"
    body = res.json()
    assert body["match_status"] == "CONFIRMED_EXTERNAL"
    assert body["is_external"] is True

    # Verify DB state
    async def _check():
        async with get_async_session_context() as db:
            contrib = (
                await db.execute(
                    select(IpContributor).where(IpContributor.id == identity_fixture["contrib_id"])
                )
            ).scalar_one()
            assert contrib.match_status == "CONFIRMED_EXTERNAL"
            assert contrib.contributor_type == "EXTERNAL"
            assert contrib.user_id is None
            assert contrib.is_external is True

            audit = (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.entity_id == identity_fixture["contrib_id"],
                        AuditLog.action == "CONTRIBUTOR_IDENTITY_REJECTED",
                    )
                )
            ).scalar_one_or_none()
            assert audit is not None
            assert audit.actor_id == identity_fixture["uploader_id"]

    asyncio.run(_check())


# =========================================================================
# TEST 10 — Association Idempotency
# =========================================================================
def test_association_idempotency(client, identity_fixture):
    """Repeated confirmation requests must not create duplicate association requests."""
    token = _tok(identity_fixture["uploader_id"], role="faculty")
    headers = _headers(client, token)
    url = f"/api/v1/faculty/{identity_fixture['record_id']}/contributors/{identity_fixture['contrib_id']}/review"

    # Call confirm first time
    res1 = client.post(url, json={"action": "confirm"}, headers=headers)
    assert res1.status_code == 200

    # Call confirm second time (idempotent retry)
    res2 = client.post(url, json={"action": "confirm"}, headers=headers)
    assert res2.status_code == 200

    # Verify that only 1 association request exists
    async def _check():
        async with get_async_session_context() as db:
            assocs = (
                await db.execute(
                    select(AssociationRequest).where(
                        AssociationRequest.ip_record_id == identity_fixture["record_id"],
                        AssociationRequest.recipient_id == identity_fixture["candidate_id"],
                    )
                )
            ).scalars().all()
            assert len(assocs) == 1, f"Expected exactly 1 association request, found {len(assocs)}"

    asyncio.run(_check())


# =========================================================================
# TEST 11 — Authorization
# =========================================================================
def test_authorization(client, identity_fixture):
    """Unauthorized users must not confirm, reject, or inspect restricted identity-review data."""
    # Outsider faculty (not uploader, not HOD, not admin)
    token = _tok(identity_fixture["outsider_id"], role="faculty")
    headers = _headers(client, token)
    url = f"/api/v1/faculty/{identity_fixture['record_id']}/contributors/{identity_fixture['contrib_id']}/review"

    res = client.post(url, json={"action": "confirm"}, headers=headers)
    assert res.status_code == 403, f"Expected 403 Forbidden for outsider, got {res.status_code}"

    # HOD of the department IS authorized
    hod_token = _tok(
        identity_fixture["hod_id"],
        role="hod_admin",
        dept=identity_fixture["dept_id"],
    )
    hod_headers = _headers(client, hod_token)
    res_hod = client.post(url, json={"action": "confirm"}, headers=hod_headers)
    assert res_hod.status_code == 200, f"Expected 200 OK for HOD, got {res_hod.status_code}"

"""Regression tests for official/final verification gates.

Uses the sanctioned test-only FixtureVerificationAdapter (never production) to
prove gate behavior: genuine match -> VERIFIED, mismatch -> not VERIFIED,
unavailable -> VERIFICATION_REQUIRED, and final-gate logic. No DB mutation.
"""

import pytest

from app.agents.final_verification_agent import FinalVerificationAgent
from app.services.duplicate_detection import normalize_identifier
from app.verification.adapters import (
    FixtureVerificationAdapter,
    IndiaPatentOfficeAdapter,
    VerificationRequest,
)


def _request() -> VerificationRequest:
    return VerificationRequest(
        ip_type="PATENT",
        identifier="202600000001",
        title="Synthetic Test Widget",
        applicant="Test Applicant University",
        inventor="A. Tester",
        filing_date="2025-03-15",
        country="IN",
    )


@pytest.mark.asyncio
async def test_genuine_match_verifies():
    adapter = FixtureVerificationAdapter(
        {
            "202600000001": {
                "status": "VERIFIED",
                "matched_data": {
                    "application_number": "202600000001",
                    "title": "Synthetic Test Widget",
                    "applicant": "Test Applicant University",
                    "inventors": ["A. Tester"],
                    "filing_date": "2025-03-15",
                },
            }
        }
    )
    result = await adapter.verify(_request())
    assert result.status == "VERIFIED"
    by_field = {fc.field_name: fc.status for fc in result.field_comparisons}
    assert by_field["application_number"] == "MATCH"
    assert by_field["title"] == "MATCH"


@pytest.mark.asyncio
async def test_mismatch_is_not_verified():
    adapter = FixtureVerificationAdapter({"202600000001": {"status": "MISMATCH"}})
    result = await adapter.verify(_request())
    assert result.status == "MISMATCH"
    assert result.status != "VERIFIED"


@pytest.mark.asyncio
async def test_unavailable_source_requires_verification():
    adapter = IndiaPatentOfficeAdapter(search_url="", enabled=False)
    result = await adapter.verify(_request())
    assert result.status == "VERIFICATION_REQUIRED"
    assert result.confidence == 0.0


def test_final_blocked_when_official_unresolved():
    agent = FinalVerificationAgent()
    status, rationale, _ = agent._decide_verification(
        verification_status="VERIFICATION_REQUIRED",
        verification_confidence=0.0,
        extraction_confidence=0.58,
        resolved_entities=[],
        duplicate_conflicts=[],
        critical_conflicts=[],
        field_completeness=0.67,
        evidence_coverage=0.25,
        has_faculty_approval=False,
    )
    assert status == "NEEDS_REVIEW"
    assert "faculty approval pending" in rationale


def test_final_verified_when_every_gate_passes():
    agent = FinalVerificationAgent()
    status, _, confidence = agent._decide_verification(
        verification_status="VERIFIED",
        verification_confidence=0.9,
        extraction_confidence=0.9,
        resolved_entities=[],
        duplicate_conflicts=[],
        critical_conflicts=[],
        field_completeness=0.8,
        evidence_coverage=0.85,
        has_faculty_approval=True,
    )
    assert status == "VERIFIED"
    assert confidence >= 0.9


def test_final_blocked_by_unresolved_duplicate_despite_official():
    agent = FinalVerificationAgent()
    status, rationale, _ = agent._decide_verification(
        verification_status="VERIFIED",
        verification_confidence=0.9,
        extraction_confidence=0.9,
        resolved_entities=[],
        duplicate_conflicts=[{"type": "duplicate_record"}],
        critical_conflicts=[],
        field_completeness=0.9,
        evidence_coverage=0.9,
        has_faculty_approval=True,
    )
    assert status == "NEEDS_REVIEW"
    assert "duplicate" in rationale


def test_duplicate_identifier_matching_stable():
    assert normalize_identifier("202441103691") == normalize_identifier("202441103691")
    assert normalize_identifier("435272-001") == normalize_identifier("435272-001")
    assert normalize_identifier("435272-001") != normalize_identifier("435273-001")


def test_faculty_approval_conservative_without_record():
    agent = FinalVerificationAgent()
    assert agent._check_faculty_approval([], None) is False
    assert (
        agent._check_faculty_approval(
            [
                {
                    "contributor_name": "Dr. X",
                    "best_match": {"id": "uid-x", "confidence": 0.5},
                }
            ],
            "nonexistent-record-id",
        )
        is False
    )

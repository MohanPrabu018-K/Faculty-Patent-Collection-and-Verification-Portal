"""Regression tests: application-number identifier handling in quality gates.

A patent application number (e.g. 202441103691) is a first-class canonical
identifier for PATENT records that carry no granted patent number yet.
Previously DataQualityAgent required ``patent_number`` for PATENT
completeness and never emitted evidence for applicant/inventors, so:

- application-only patents scored completeness 0.67 / coverage 0.25, and
- EVERY record (even complete designs) capped at coverage 0.5,

making FinalVerificationAgent VERIFIED unreachable through real pipeline
data regardless of official verification or faculty approval.

These tests lock the corrected behavior without touching live DB state.
"""

import pytest

from app.agents.data_quality_agent import DataQualityAgent
from app.agents.final_verification_agent import FinalVerificationAgent
from app.core.ai_contracts import OrchestratorInput


def _doc6_like() -> dict:
    return {
        "ip_type": "PATENT",
        "application_number": "202441103691",
        "patent_number": None,
        "design_number": None,
        "title": "IOT SOLUTIONS FOR REMOTE VEHICLE OPERATION AND SURVEILLANCE",
        "applicant": "R P SARATHY INSTITUTE",
        "inventors": ["DEVAKIRUBAI", "PUSHPA", "KANNAMMAL", "UMA MAHESWARI", "SONIYA"],
        "filing_date": "2024-12-27",
    }


async def _quality(canonical: dict):
    agent = DataQualityAgent()
    result = await agent.process(
        OrchestratorInput(upload_id="t", file_data=b"", filename="t.pdf", context={"canonical_data": canonical})
    )
    assert result.agent_name == "DataQualityAgent"
    return result


@pytest.mark.asyncio
async def test_patent_application_number_counts_as_identifier():
    result = await _quality(_doc6_like())
    assert result.extracted_data["field_completeness"] == 1.0
    assert "patent/application number" not in " ".join(result.warnings)


@pytest.mark.asyncio
async def test_patent_application_number_coverage_reaches_gate():
    result = await _quality(_doc6_like())
    assert result.extracted_data["evidence_coverage"] >= 0.8


@pytest.mark.asyncio
async def test_application_number_validity_evidence_present():
    result = await _quality(_doc6_like())
    assert result.extracted_data.get("application_number_validity") == 1.0
    fields = [e.get("field") for e in result.evidence]
    assert "application_number" in fields
    assert "applicant" in fields
    assert "inventors" in fields


@pytest.mark.asyncio
async def test_patent_without_any_identifier_still_incomplete():
    canon = _doc6_like()
    canon["application_number"] = None
    result = await _quality(canon)
    assert result.extracted_data["field_completeness"] < 0.75
    assert any("patent/application number" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_design_missing_applicant_still_below_coverage_gate():
    result = await _quality(
        {
            "ip_type": "DESIGN_REGISTRATION",
            "design_number": "435272-001",
            "title": "ARTIFICIAL INTELLIGENCE BASED STRESS DETECTION DEVICE",
            "applicant": None,
            "inventors": ["A. Tester"],
        }
    )
    assert result.extracted_data["evidence_coverage"] < 0.8


@pytest.mark.asyncio
async def test_complete_design_reaches_both_gates():
    result = await _quality(
        {
            "ip_type": "DESIGN_REGISTRATION",
            "design_number": "435272-001",
            "title": "ARTIFICIAL INTELLIGENCE BASED STRESS DETECTION DEVICE",
            "applicant": "Test Applicant University",
            "inventors": ["A. Tester"],
            "filing_date": "2024-01-01",
        }
    )
    assert result.extracted_data["field_completeness"] >= 0.75
    assert result.extracted_data["evidence_coverage"] >= 0.8


@pytest.mark.asyncio
async def test_final_gate_passes_with_realistic_doc6_quality_and_approval():
    """Code-readiness: with genuine quality metrics + faculty approval and no
    conflicts, the final gate no longer blocks on quality. (Official status
    stays VERIFICATION_REQUIRED until a real authoritative source confirms.)"""
    agent = FinalVerificationAgent()
    quality = await _quality(_doc6_like())
    completeness = quality.extracted_data["field_completeness"]
    coverage = quality.extracted_data["evidence_coverage"]
    status, _, _ = agent._decide_verification(
        verification_status="VERIFICATION_REQUIRED",
        verification_confidence=0.0,
        extraction_confidence=0.9,
        resolved_entities=[],
        duplicate_conflicts=[],
        critical_conflicts=[],
        field_completeness=completeness,
        evidence_coverage=coverage,
        has_faculty_approval=True,
    )
    assert status == "VERIFIED"


def test_final_gate_still_blocked_without_faculty_approval():
    """The honest blocker is preserved: quality alone never forces green."""
    agent = FinalVerificationAgent()
    status, rationale, _ = agent._decide_verification(
        verification_status="VERIFICATION_REQUIRED",
        verification_confidence=0.0,
        extraction_confidence=0.9,
        resolved_entities=[],
        duplicate_conflicts=[],
        critical_conflicts=[],
        field_completeness=1.0,
        evidence_coverage=1.0,
        has_faculty_approval=False,
    )
    assert status == "NEEDS_REVIEW"
    assert "faculty approval pending" in rationale

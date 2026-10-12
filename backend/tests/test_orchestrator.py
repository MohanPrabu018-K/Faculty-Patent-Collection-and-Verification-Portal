import pytest
import asyncio
from types import SimpleNamespace
from app.ai_orchestrator import AIOrchestrator
from app.core.ai_contracts import OrchestratorInput
from app.models.base import IpRecord
from app.workers import orchestrator_task


@pytest.mark.asyncio
async def test_orchestrator_creation():
    orchestrator = AIOrchestrator()
    assert orchestrator is not None
    assert len(orchestrator._agent_classes) == 12


@pytest.mark.asyncio
async def test_orchestrator_execute_minimal():
    orchestrator = AIOrchestrator()
    input_data = OrchestratorInput(
        upload_id="test_001",
        file_data=b"",
        filename="test.pdf",
    )
    result = await orchestrator.execute(input_data)
    assert result is not None
    assert result.overall_status in ["completed", "completed_partial", "human_review_required", "completed_with_errors"]
    assert isinstance(result.agent_outputs, list)


@pytest.mark.asyncio
async def test_orchestrator_all_agents_present():
    orchestrator = AIOrchestrator()
    expected_agents = [
        "DocumentClassificationAgent",
        "QRAnalysisAgent",
        "OCRExtractionAgent",
        "DocumentUnderstandingAgent",
        "VerificationAgent",
        "FacultyIdentityResolutionAgent",
        "DuplicateDetectionAgent",
        "ConflictResolutionAgent",
        "AssociationRecommendationAgent",
        "DataQualityAgent",
        "FinalVerificationAgent",
        "ReportAnalyticsAgent",
    ]
    for agent_name in expected_agents:
        assert agent_name in orchestrator._agent_classes

class _FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
    def execute(self, *args, **kwargs):
        return SimpleNamespace(scalar_one_or_none=lambda: self.existing)
    def close(self):
        pass


@pytest.mark.asyncio
async def test_orchestrator_persists_ocr_ip_type_and_design_number(monkeypatch):
    ip_record = IpRecord(id="rec-1", ip_type="UNKNOWN_OTHER", uploader_id="user-1")
    result = SimpleNamespace(
        agent_outputs=[
            {
                "agent_name": "OCRExtractionAgent",
                "confidence": 0.9,
                "extracted_data": {
                    "ip_type": "DESIGN_REGISTRATION",
                    "design_number": [{"value": "459641-001", "source": "ocr_text"}],
                },
            }
        ]
    )
    monkeypatch.setattr(orchestrator_task, "get_session", lambda: _FakeSession())

    orchestrator_task._update_ip_record_from_agents(ip_record, result)

    assert ip_record.ip_type == "DESIGN_REGISTRATION"
    assert ip_record.design_number == "459641-001"


def test_design_registration_date_is_persisted(monkeypatch):
    """Regression for D-004: design certificates only carry a registration date.

    A design registration certificate states its date as "Design No. / Date".
    The extraction service emits that as ``registration_date``, but the
    persistence loop previously mapped only filing/grant/published, so every
    design record was stored with null dates despite a successful OCR. The
    registration date must reach the ``registration_date`` column.
    """
    from datetime import datetime

    ip_record = IpRecord(id="rec-d004", ip_type="DESIGN_REGISTRATION", uploader_id="user-1")
    result = SimpleNamespace(
        agent_outputs=[
            {
                "agent_name": "OCRExtractionAgent",
                "confidence": 0.9,
                "extracted_data": {
                    "ip_type": "DESIGN_REGISTRATION",
                    "design_number": [{"value": "459641-001", "source": "ocr_text"}],
                    "registration_date": [
                        {"value": datetime(2025, 5, 21), "source": "ocr_text", "confidence": 0.9}
                    ],
                },
            }
        ]
    )
    monkeypatch.setattr(orchestrator_task, "get_session", lambda: _FakeSession())

    orchestrator_task._update_ip_record_from_agents(ip_record, result)

    assert ip_record.registration_date is not None
    assert ip_record.registration_date.date().isoformat() == "2025-05-21"
    # The design certificate's date is the registration date, NOT a grant date.
    assert ip_record.grant_date is None


def test_malformed_registration_date_is_skipped_not_crashed(monkeypatch):
    """A bare year or unparseable value must be skipped, never abort the commit."""
    ip_record = IpRecord(id="rec-d004b", ip_type="DESIGN_REGISTRATION", uploader_id="user-1")
    result = SimpleNamespace(
        agent_outputs=[
            {
                "agent_name": "OCRExtractionAgent",
                "confidence": 0.9,
                "extracted_data": {
                    "registration_date": [{"value": "NA", "source": "ocr_text"}],
                    "design_number": [{"value": "410787-001", "source": "ocr_text"}],
                },
            }
        ]
    )
    monkeypatch.setattr(orchestrator_task, "get_session", lambda: _FakeSession())

    orchestrator_task._update_ip_record_from_agents(ip_record, result)

    assert ip_record.registration_date is None
    # The rest of the record is still persisted.
    assert ip_record.design_number == "410787-001"


def test_patent_filing_and_grant_dates_still_persist(monkeypatch):
    """D-004 must not regress the patent path: filing stays, grant stays a date."""
    from datetime import date, datetime

    ip_record = IpRecord(id="rec-d004c", ip_type="PATENT", uploader_id="user-1")
    result = SimpleNamespace(
        agent_outputs=[
            {
                "agent_name": "OCRExtractionAgent",
                "confidence": 0.9,
                "extracted_data": {
                    "filing_date": [{"value": datetime(2024, 12, 27), "source": "ocr_text"}],
                    "grant_date": [{"value": date(2025, 6, 1), "source": "ocr_text"}],
                },
            }
        ]
    )
    monkeypatch.setattr(orchestrator_task, "get_session", lambda: _FakeSession())

    orchestrator_task._update_ip_record_from_agents(ip_record, result)

    assert ip_record.filing_date == datetime(2024, 12, 27)
    # grant_date is a DATE column (migration 009), never a timestamp.
    assert ip_record.grant_date == date(2025, 6, 1)


def test_enum_safe_verification_status_maps_agent_vocab():
    # Values already in the DB enum pass through unchanged.
    assert orchestrator_task._enum_safe_verification_status("VERIFIED") == "VERIFIED"
    assert orchestrator_task._enum_safe_verification_status("MISMATCH") == "MISMATCH"
    assert orchestrator_task._enum_safe_verification_status("UNVERIFIED") == "UNVERIFIED"
    # Wider agent vocabulary must be coerced into the DB enum.
    assert orchestrator_task._enum_safe_verification_status("NEEDS_REVIEW") == "VERIFICATION_REQUIRED"
    assert orchestrator_task._enum_safe_verification_status("NOT_FOUND") == "VERIFICATION_REQUIRED"
    assert orchestrator_task._enum_safe_verification_status("ERROR") == "VERIFICATION_REQUIRED"
    assert orchestrator_task._enum_safe_verification_status("REJECTED") == "VERIFICATION_REQUIRED"
    assert orchestrator_task._enum_safe_verification_status(None) == "VERIFICATION_REQUIRED"


def test_final_verification_needs_review_is_enum_safe(monkeypatch):
    """Regression: FinalVerificationAgent emits NEEDS_REVIEW which must not be
    written verbatim into the verification_status_enum column."""
    ip_record = IpRecord(id="rec-2", ip_type="UNKNOWN_OTHER", uploader_id="user-1")
    result = SimpleNamespace(
        agent_outputs=[
            {
                "agent_name": "FinalVerificationAgent",
                "confidence": 0.4,
                "extracted_data": {
                    "final_verification_status": "NEEDS_REVIEW",
                    "final_verification_rationale": "Insufficient for auto-verification",
                    "final_verification_confidence": 0.4,
                },
            }
        ]
    )
    monkeypatch.setattr(orchestrator_task, "get_session", lambda: _FakeSession())

    orchestrator_task._update_ip_record_from_agents(ip_record, result)

    assert ip_record.verification_status == "VERIFICATION_REQUIRED"
    # The rich decision is preserved for audit/UI purposes.
    assert ip_record.evidence["final_verification"]["status"] == "NEEDS_REVIEW"

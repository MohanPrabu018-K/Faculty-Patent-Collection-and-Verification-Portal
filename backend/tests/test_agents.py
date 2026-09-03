import pytest
import asyncio
from app.agents.classification_agent import DocumentClassificationAgent
from app.agents.qr_agent import QRAnalysisAgent
from app.agents.ocr_extraction_agent import OCRExtractionAgent
from app.agents.document_understanding_agent import DocumentUnderstandingAgent
from app.agents.verification_agent import VerificationAgent
from app.agents.faculty_identity_agent import FacultyIdentityResolutionAgent
from app.agents.duplicate_detection_agent import DuplicateDetectionAgent
from app.agents.conflict_resolution_agent import ConflictResolutionAgent
from app.agents.association_recommendation_agent import AssociationRecommendationAgent
from app.agents.data_quality_agent import DataQualityAgent
from app.agents.report_analytics_agent import ReportAnalyticsAgent
from app.core.ai_contracts import OrchestratorInput, AgentStatus


@pytest.mark.asyncio
async def test_classification_agent_uses_ocr_fallback(monkeypatch):
    class _FakeProcessing:
        class ocr:
            text = "Design Certificate\nDesign No. 466982-001\nSerial No. 213404\nDate : 22/10/2024"

    monkeypatch.setattr("app.services.ocr_pipeline.process_document", lambda *args, **kwargs: _FakeProcessing())

    agent = DocumentClassificationAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"pdf-bytes", filename="Design Certificate 466982-001.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "DocumentClassificationAgent"
    assert result.status == AgentStatus.SUCCESS
    assert result.extracted_data["ip_type"] == "DESIGN_REGISTRATION"


@pytest.mark.asyncio
async def test_qr_agent():
    agent = QRAnalysisAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "QRAnalysisAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]


@pytest.mark.asyncio
async def test_ocr_extraction_agent():
    agent = OCRExtractionAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "OCRExtractionAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]


@pytest.mark.asyncio
async def test_document_understanding_agent():
    agent = DocumentUnderstandingAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "DocumentUnderstandingAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]


@pytest.mark.asyncio
async def test_verification_agent():
    agent = VerificationAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "VerificationAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]


@pytest.mark.asyncio
async def test_faculty_identity_agent():
    agent = FacultyIdentityResolutionAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "FacultyIdentityResolutionAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]


@pytest.mark.asyncio
async def test_duplicate_detection_agent():
    agent = DuplicateDetectionAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "DuplicateDetectionAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]


@pytest.mark.asyncio
async def test_conflict_resolution_agent():
    agent = ConflictResolutionAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "ConflictResolutionAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]


@pytest.mark.asyncio
async def test_association_recommendation_agent():
    agent = AssociationRecommendationAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "AssociationRecommendationAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]


@pytest.mark.asyncio
async def test_data_quality_agent():
    agent = DataQualityAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "DataQualityAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]


@pytest.mark.asyncio
async def test_data_quality_agent_handles_scalar_and_evidence_lists():
    agent = DataQualityAgent()
    input_data = OrchestratorInput(
        upload_id="test",
        file_data=b"",
        filename="test.pdf",
        context={
            "agent_outputs": [
                {
                    "extracted_data": {
                        "patent_number": "459641-001",
                        "design_number": [{"value": "459641-001", "source": "ocr_text"}],
                        "title": [{"value": "A Sample Design"}],
                        "applicant": None,
                        "inventor": [],
                        "registration_date": [{"value": "2025-07-23", "source": "ocr_text"}],
                    }
                }
            ],
            "extracted_data": {
                "patent_number": "459641-001",
                "design_number": [{"value": "459641-001", "source": "ocr_text"}],
                "title": [{"value": "A Sample Design"}],
                "applicant": None,
                "inventor": [],
                "registration_date": [{"value": "2025-07-23", "source": "ocr_text"}],
            },
            "evidence_chain": [],
        },
    )
    result = await agent.process(input_data)
    assert result.agent_name == "DataQualityAgent"
    assert result.status == AgentStatus.SUCCESS
    assert result.extracted_data["patent_number_validity"] == 1.0
    assert result.extracted_data["design_number_validity"] == 1.0
    assert result.extracted_data["date_validity"] == 1.0


@pytest.mark.asyncio
async def test_report_analytics_agent():
    agent = ReportAnalyticsAgent()
    input_data = OrchestratorInput(upload_id="test", file_data=b"", filename="test.pdf")
    result = await agent.process(input_data)
    assert result.agent_name == "ReportAnalyticsAgent"
    assert result.status in [AgentStatus.SUCCESS, AgentStatus.ERROR]
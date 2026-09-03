import pytest
from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
    OrchestratorOutput,
)


def test_agent_output_creation():
    output = AgentOutput(
        agent_name="TestAgent",
        status=AgentStatus.SUCCESS,
        extracted_data={"test": "data"},
        confidence=0.8,
        confidence_level=ConfidenceLevel.HIGH,
        evidence=[{"source": "test", "confidence": 0.8}],
        recommendation="test_recommendation",
        processing_time=0.1,
    )
    assert output.agent_name == "TestAgent"
    assert output.status == AgentStatus.SUCCESS
    assert output.confidence == 0.8
    assert output.confidence_level == ConfidenceLevel.HIGH


def test_agent_output_to_dict():
    output = AgentOutput(
        agent_name="TestAgent",
        status=AgentStatus.SUCCESS,
        confidence=0.8,
        confidence_level=ConfidenceLevel.HIGH,
    )
    d = output.to_dict()
    assert d["agent_name"] == "TestAgent"
    assert d["status"] == "success"
    assert d["confidence"] == 0.8
    assert d["confidence_level"] == "high"


def test_orchestrator_input():
    input_data = OrchestratorInput(
        upload_id="test_001",
        file_data=b"test content",
        filename="test.pdf",
        ip_type="PATENT",
        context={"test": "context"},
    )
    assert input_data.upload_id == "test_001"
    assert input_data.file_data == b"test content"
    assert input_data.filename == "test.pdf"
    assert input_data.ip_type == "PATENT"
    assert input_data.context == {"test": "context"}


def test_orchestrator_output():
    output = OrchestratorOutput(
        overall_status="completed",
        final_recommendation="automatic_processing",
        overall_confidence=0.85,
        overall_requires_human_review=False,
    )
    assert output.overall_status == "completed"
    assert output.final_recommendation == "automatic_processing"
    assert output.overall_confidence == 0.85
    assert output.overall_requires_human_review is False
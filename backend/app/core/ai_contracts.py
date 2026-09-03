from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentStatus(Enum):
    """Status of agent execution."""
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    SKIPPED = "skipped"


class ConfidenceLevel(Enum):
    """Confidence levels for AI outputs."""
    HIGH = "high"      # >= 0.75 - can proceed automatically
    MEDIUM = "medium"  # 0.5 - 0.75 - cross-check required
    LOW = "low"        # < 0.5 - human review required


@dataclass
class AgentOutput:
    """Structured output contract for every AI agent."""
    agent_name: str
    status: AgentStatus
    extracted_data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    evidence: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    recommendation: str | None = None
    requires_human_review: bool = False
    processing_time: float = 0.0
    error: str | None = None
    fallback_available: bool = False
    fallback_name: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "agent_name": self.agent_name,
            "status": self.status.value,
            "extracted_data": self.extracted_data,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level.value,
            "evidence": self.evidence,
            "warnings": self.warnings,
            "conflicts": self.conflicts,
            "recommendation": self.recommendation,
            "requires_human_review": self.requires_human_review,
            "processing_time": self.processing_time,
            "error": self.error,
            "fallback_available": self.fallback_available,
            "fallback_name": self.fallback_name,
        }


@dataclass 
class OrchestratorInput:
    """Input structure for the AI Orchestrator."""
    upload_id: str
    file_data: bytes
    filename: str
    ip_type: str | None = None  # None means let agents determine
    context: dict[str, Any] | None = None


@dataclass
class OrchestratorOutput:
    """Output structure from the AI Orchestrator."""
    overall_status: str
    final_recommendation: str | None = None
    overall_confidence: float = 0.0
    overall_requires_human_review: bool = False
    agent_outputs: list[dict[str, Any]] = field(default_factory=list)
    evidence_chain: list[dict[str, Any]] = field(default_factory=list)
    processing_summary: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    processing_time: float = 0.0
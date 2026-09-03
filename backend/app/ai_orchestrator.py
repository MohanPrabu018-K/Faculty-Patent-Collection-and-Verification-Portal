from __future__ import annotations

import asyncio
import time
from typing import Any

from app.agents.association_recommendation_agent import AssociationRecommendationAgent
from app.agents.classification_agent import DocumentClassificationAgent
from app.agents.conflict_resolution_agent import ConflictResolutionAgent
from app.agents.data_quality_agent import DataQualityAgent
from app.agents.document_understanding_agent import DocumentUnderstandingAgent
from app.agents.duplicate_detection_agent import DuplicateDetectionAgent
from app.agents.faculty_identity_agent import FacultyIdentityResolutionAgent
from app.agents.ocr_extraction_agent import OCRExtractionAgent
from app.agents.qr_agent import QRAnalysisAgent
from app.agents.report_analytics_agent import ReportAnalyticsAgent
from app.agents.verification_agent import VerificationAgent
from app.core.ai_contracts import AgentOutput, AgentStatus, ConfidenceLevel, OrchestratorInput, OrchestratorOutput

AGENT_ORDER = [
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
    "ReportAnalyticsAgent",
]


class AIOrchestrator:
    def __init__(self):
        self._agent_classes: dict[str, type] = {
            "DocumentClassificationAgent": DocumentClassificationAgent,
            "QRAnalysisAgent": QRAnalysisAgent,
            "OCRExtractionAgent": OCRExtractionAgent,
            "DocumentUnderstandingAgent": DocumentUnderstandingAgent,
            "VerificationAgent": VerificationAgent,
            "FacultyIdentityResolutionAgent": FacultyIdentityResolutionAgent,
            "DuplicateDetectionAgent": DuplicateDetectionAgent,
            "ConflictResolutionAgent": ConflictResolutionAgent,
            "AssociationRecommendationAgent": AssociationRecommendationAgent,
            "DataQualityAgent": DataQualityAgent,
            "ReportAnalyticsAgent": ReportAnalyticsAgent,
        }
        self._retry_delay = 0.5

    async def execute(self, input_data: OrchestratorInput) -> OrchestratorOutput:
        pipeline_start = time.time()
        output = OrchestratorOutput(
            overall_status="processing",
            overall_requires_human_review=False,
            processing_summary={},
            errors=[],
            audit_log=[],
        )
        agent_outputs: list[AgentOutput] = []
        evidence_chain: list[dict[str, Any]] = []
        context: dict[str, Any] = {
            "upload_id": input_data.upload_id,
            "filename": input_data.filename,
            "file_data": input_data.file_data,
            "ip_type": input_data.ip_type,
            "context": input_data.context or {},
            "agent_outputs": [],
            "evidence_chain": [],
            "extracted_data": dict((input_data.context or {}).get("extracted_data", {})),
        }

        for agent_name in AGENT_ORDER:
            try:
                agent_result = await self._execute_agent(agent_name, context)
                agent_outputs.append(agent_result)
                context["agent_outputs"] = [ao.to_dict() for ao in agent_outputs]
                if agent_result.evidence:
                    evidence_chain.extend(agent_result.evidence)
                context["evidence_chain"] = evidence_chain
                if agent_result.extracted_data:
                    context["extracted_data"].update(agent_result.extracted_data)
                    context.update(agent_result.extracted_data)
                    if "ip_type" in agent_result.extracted_data:
                        context["ip_type"] = agent_result.extracted_data["ip_type"]
                if agent_result.requires_human_review:
                    output.overall_requires_human_review = True
                if agent_result.status == AgentStatus.ERROR:
                    output.errors.append({"agent": agent_name, "error": agent_result.error or "Unknown error"})
            except Exception as e:
                output.errors.append({"agent": agent_name, "error": str(e)})

        output = await self._finalize_output(output, agent_outputs, evidence_chain, pipeline_start)
        output.agent_outputs = [ao.to_dict() for ao in agent_outputs]
        return output

    async def _execute_agent(self, agent_name: str, context: dict[str, Any]) -> AgentOutput:
        agent_class = self._agent_classes[agent_name]
        agent_instance = agent_class()
        input_data = OrchestratorInput(
            upload_id=context.get("upload_id", ""),
            file_data=context.get("file_data", b""),
            filename=context.get("filename", ""),
            ip_type=context.get("ip_type"),
            context=context,
        )
        result = await agent_instance.process(input_data)
        if not result.agent_name:
            result.agent_name = agent_name
        return result

    async def _finalize_output(self, output: OrchestratorOutput, agent_outputs: list[AgentOutput], evidence_chain: list[dict[str, Any]], pipeline_start: float) -> OrchestratorOutput:
        output.processing_time = time.time() - pipeline_start
        total_agents = len(agent_outputs)
        succeeded = sum(1 for a in agent_outputs if a.status == AgentStatus.SUCCESS)
        failed = sum(1 for a in agent_outputs if a.status == AgentStatus.ERROR)
        output.processing_summary = {
            "total_agents": total_agents,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": round(succeeded / total_agents, 2) if total_agents else 0,
        }
        output.evidence_chain = evidence_chain[-20:]
        if output.errors:
            output.final_recommendation = "partial_results_with_errors"
            output.overall_status = "completed_with_errors"
        elif output.overall_requires_human_review:
            output.final_recommendation = "human_review_required"
            output.overall_status = "human_review_required"
        else:
            output.final_recommendation = "automatic_processing"
            output.overall_status = "completed"
        output.audit_log.append({"event": "orchestrator_completion", "timestamp": time.time(), "overall_status": output.overall_status, "requires_human_review": output.overall_requires_human_review})
        return output

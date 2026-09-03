from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import AgentOutput, AgentStatus, ConfidenceLevel, OrchestratorInput


class ReportAnalyticsAgent:
    name = "ReportAnalyticsAgent"

    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        try:
            previous_outputs = list((input_data.context or {}).get("agent_outputs", []))
            extracted_data: dict[str, Any] = {}
            warnings: list[str] = []
            conflicts: list[dict[str, Any]] = []

            confidences: list[float] = []
            succeeded = 0
            failed = 0
            total_time = 0.0
            all_conflicts: list[dict[str, Any]] = []

            for agent_out in previous_outputs:
                if isinstance(agent_out, dict):
                    confidences.append(float(agent_out.get("confidence", 0.0)))
                    total_time += float(agent_out.get("processing_time", 0.0))
                    if agent_out.get("status") == "success":
                        succeeded += 1
                    else:
                        failed += 1
                    all_conflicts.extend(agent_out.get("conflicts", []))

            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            extracted_data = {
                "ip_type": (input_data.context or {}).get("extracted_data", {}).get("ip_type", input_data.ip_type or "UNKNOWN"),
                "total_agents_executed": len(previous_outputs),
                "confidence_summary": {
                    "average": round(avg_confidence, 2),
                    "high": sum(1 for c in confidences if c >= 0.75),
                    "medium": sum(1 for c in confidences if 0.5 <= c < 0.75),
                    "low": sum(1 for c in confidences if c < 0.5),
                },
                "processing_efficiency": {
                    "agents_succeeded": succeeded,
                    "agents_failed": failed,
                    "average_processing_time": round(total_time / len(previous_outputs), 2) if previous_outputs else 0,
                },
                "conflict_summary": {
                    "total_detected": len(all_conflicts),
                    "by_type": {},
                    "require_review": sum(1 for c in all_conflicts if c.get("severity") in ("high", "medium")),
                },
            }

            for conflict in all_conflicts:
                c_type = conflict.get("type") or conflict.get("conflict_type") or "unknown"
                extracted_data["conflict_summary"]["by_type"][c_type] = extracted_data["conflict_summary"]["by_type"].get(c_type, 0) + 1

            requires_review = failed > 0 or extracted_data["conflict_summary"]["require_review"] > 0
            if requires_review:
                warnings.append("Report analytics indicates review is required")

            confidence_level = ConfidenceLevel.HIGH if avg_confidence >= 0.75 else ConfidenceLevel.MEDIUM if avg_confidence >= 0.5 else ConfidenceLevel.LOW
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=extracted_data,
                confidence=avg_confidence,
                confidence_level=confidence_level,
                evidence=[{"source": "report_analytics", "agents_executed": len(previous_outputs), "avg_confidence": round(avg_confidence, 2)}],
                warnings=warnings,
                conflicts=all_conflicts,
                recommendation="summary_with_review_notes" if requires_review else "full_summary_available",
                requires_human_review=requires_review,
                processing_time=time.time() - start_time,
            )
        except Exception as e:
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                confidence=0.0,
                confidence_level=ConfidenceLevel.LOW,
                evidence=[],
                warnings=[f"Report/analytics agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=time.time() - start_time,
                error=str(e),
            )

from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class QRAnalysisAgent:
    """Agent 2: Detects and decodes QR codes from uploaded documents.
    
    Uses existing pyzbar QR detection from workers/tasks.py.
    Returns QR data if found, with confidence based on successful decode.
    """
    
    name = "QRAnalysisAgent"
    
    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        
        try:
            from app.services.ocr_pipeline import decode_qr_payloads

            qr_result = decode_qr_payloads(input_data.file_data, filename=input_data.filename)

            extracted_data: dict[str, Any] = {
                "qr_data": qr_result.qr_data,
                "qr_payload": qr_result.qr_data[0] if qr_result.qr_data else None,
                "qr_count": len(qr_result.qr_data),
            }
            confidence = 0.9 if qr_result.success else 0.1
            confidence_level = ConfidenceLevel.HIGH if qr_result.success else ConfidenceLevel.LOW
            evidence_list = [
                {
                    "source": item.get("source", "qr"),
                    "type": item.get("type"),
                    "payload": item.get("payload"),
                    "confidence": 0.9,
                }
                for item in qr_result.evidence
            ]
            warnings = list(qr_result.warnings)
            if not qr_result.success:
                warnings.append("No QR code detected in document - OCR fallback will be used")
            conflicts: list[dict[str, Any]] = []
            requires_review = False
            
            processing_time = time.time() - start_time
            
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=extracted_data,
                confidence=confidence,
                confidence_level=confidence_level,
                evidence=evidence_list,
                warnings=warnings,
                conflicts=conflicts,
                recommendation=extracted_data.get("qr_data"),
                requires_human_review=requires_review,
                processing_time=processing_time,
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                confidence=0.0,
                confidence_level=ConfidenceLevel.LOW,
                evidence=[],
                warnings=[f"QR analysis agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=processing_time,
                error=str(e),
            )

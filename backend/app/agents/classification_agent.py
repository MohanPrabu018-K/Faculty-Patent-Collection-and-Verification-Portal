from __future__ import annotations

import time

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class DocumentClassificationAgent:
    """Agent 1: Classifies document as PATENT, DESIGN_REGISTRATION, or UNKNOWN_OTHER.
    
    Reads OCR text and filename to determine IP type.
    Uses existing classify_ip_type logic from workers/tasks.py.
    """
    
    name = "DocumentClassificationAgent"
    
    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        
        try:
            from app.services.ocr_pipeline import classify_document, process_document
            
            ocr_text = input_data.context.get("ocr_text", "") if input_data.context else ""
            if not ocr_text.strip() and input_data.file_data:
                processing = process_document(input_data.file_data, filename=input_data.filename)
                ocr_text = processing.ocr.text or ""
            
            # Use existing classification logic
            classification = classify_document(ocr_text, input_data.filename)
            
            ip_type = classification.get("ip_type", "UNKNOWN_OTHER")
            confidence = classification.get("confidence", 0.5)
            
            # Map confidence level
            if confidence >= 0.75:
                confidence_level = ConfidenceLevel.HIGH
            elif confidence >= 0.5:
                confidence_level = ConfidenceLevel.MEDIUM
            else:
                confidence_level = ConfidenceLevel.LOW
            
            # Build evidence
            evidence = [
                {
                    "source": "text_filename_analysis",
                    "method": "keyword_scoring",
                    "confidence": confidence,
                }
            ]
            
            warnings = []
            conflicts = []
            
            # Determine if human review is required
            requires_review = confidence < 0.5 and ip_type == "UNKNOWN_OTHER"
            
            processing_time = time.time() - start_time
            
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data={"ip_type": ip_type, "confidence": confidence},
                confidence=confidence,
                confidence_level=confidence_level,
                evidence=evidence,
                warnings=warnings,
                conflicts=conflicts,
                recommendation=ip_type,
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
                warnings=[f"Classification agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=processing_time,
                error=str(e),
            )
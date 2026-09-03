from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class DocumentUnderstandingAgent:
    """Agent 4: Performs deep document understanding and semantic analysis.
    
    Analyzes extracted text to identify:
    - Invention titles and abstracts
    - Technical field/category
    - Relationships between entities (inventor-applicant, etc.)
    - Potential priority dates and filing strategies
    - Document structure and section identification
    
    Builds on OCR extraction to provide semantic context.
    """
    
    name = "DocumentUnderstandingAgent"
    
    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        
        try:
            from app.services.extraction import StructuredExtractionService
            
            extracted_data: dict[str, Any] = {}
            evidence_list: List[dict[str, Any]] = []
            warnings: List[str] = []
            conflicts: List[dict[str, Any]] = []
            
            # Get OCR text from input context or previous agent
            ocr_text = ""
            if input_data.context and "ocr_text" in input_data.context:
                ocr_text = input_data.context["ocr_text"]
            elif input_data.file_data:
                # Perform quick OCR to get text
                from app.services.ocr_pipeline import perform_ocr
                ocr_result = perform_ocr(input_data.file_data)
                ocr_text = ocr_result.get("text", "")
            
            if not ocr_text.strip():
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    extracted_data={},
                    confidence=0.1,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[],
                    warnings=["No text available for document understanding"],
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                )
            
            extraction_service = StructuredExtractionService()
            
            # Perform extraction which includes some understanding
            # We reuse the extraction service but focus on higher-level understanding
            ip_type = input_data.ip_type or "UNKNOWN_OTHER"
            extraction_result = extraction_service.extract_from_text(ocr_text, ip_type)
            
            extracted_data = extraction_result.get("normalized_fields", {})
            extracted_data["ip_type"] = ip_type
            
            # Add understanding-specific fields
            understanding_data = {
                "text_length": len(ocr_text),
                "has_title": "title" in extraction_result.get("normalized_fields", {}),
                "has_dates": any("date" in k.lower() for k in extraction_result.get("normalized_fields", {}).keys()) or "registration_date" in extraction_result.get("normalized_fields", {}),
                "has_inventors": "inventors" in extraction_result.get("normalized_fields", {}),
                "has_applicant": "applicant" in extraction_result.get("normalized_fields", {}),
            }
            extracted_data.update(understanding_data)
            
            # Build evidence chain
            evidence_list = extraction_result.get("evidence", [])
            
            # Calculate confidence based on completeness
            evidence_count = len(extraction_result.get("evidence", {}))
            if evidence_count >= 5:
                confidence = 0.7
                confidence_level = ConfidenceLevel.MEDIUM
            elif evidence_count >= 3:
                confidence = 0.5
                confidence_level = ConfidenceLevel.MEDIUM
            else:
                confidence = 0.3
                confidence_level = ConfidenceLevel.LOW
                warnings.append("Limited fields extracted - document may be partially legible")
            
            # Check review requirements
            requires_review = confidence < 0.5 or not understanding_data.get("has_title")
            
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
                recommendation=extracted_data.get("patent_number") or extracted_data.get("design_number"),
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
                warnings=[f"Document understanding agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=processing_time,
                error=str(e),
            )
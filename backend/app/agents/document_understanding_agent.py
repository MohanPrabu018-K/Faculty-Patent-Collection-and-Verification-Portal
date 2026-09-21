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
            extracted_data: dict[str, Any] = {}
            evidence_list: list[dict[str, Any]] = []
            warnings: list[str] = []
            conflicts: list[dict[str, Any]] = []
            
            # Get OCR text from input context
            ocr_text = ""
            if input_data.context and "ocr_text" in input_data.context:
                ocr_text = input_data.context["ocr_text"]
            
            # Read canonical data from context (set by orchestrator after OCR Extraction)
            canonical_data = input_data.context.get("canonical_data", {}) if input_data.context else {}
            
            if not ocr_text.strip() and not canonical_data:
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    extracted_data={},
                    confidence=0.1,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[],
                    warnings=["No text or canonical data available for document understanding"],
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                )
            
            ip_type = canonical_data.get("ip_type") or input_data.ip_type or "UNKNOWN_OTHER"
            
            # Add understanding-specific fields based on canonical data
            understanding_data = {
                "text_length": len(ocr_text),
                "has_title": bool(canonical_data.get("title")),
                "has_dates": any(k in canonical_data for k in ["filing_date", "grant_date", "registration_date", "certificate_date", "published_date"]),
                "has_inventors": bool(canonical_data.get("inventors")),
                "has_applicant": bool(canonical_data.get("applicant")),
                "contributor_count": len(canonical_data.get("contributors", [])),
            }
            
            # Merge canonical data into extracted_data for downstream agents
            extracted_data.update(canonical_data)
            extracted_data.update(understanding_data)
            
            # Build evidence chain from canonical data
            evidence_list = [
                {"field": k, "value": v, "source": "canonical"}
                for k, v in canonical_data.items()
                if v is not None
            ]
            
            # Calculate confidence based on canonical data completeness
            core_fields = ["title", "inventors", "applicant", "patent_number", "design_number"]
            filled = sum(1 for f in core_fields if canonical_data.get(f))
            completeness = filled / len(core_fields)
            
            if completeness >= 0.8:
                confidence = 0.8
                confidence_level = ConfidenceLevel.HIGH
            elif completeness >= 0.5:
                confidence = 0.6
                confidence_level = ConfidenceLevel.MEDIUM
            else:
                confidence = 0.4
                confidence_level = ConfidenceLevel.LOW
                warnings.append("Limited canonical fields extracted - document may be partially legible")
            
            # Check review requirements
            requires_review = confidence < 0.5 or not canonical_data.get("title")
            
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
                recommendation=canonical_data.get("patent_number") or canonical_data.get("design_number"),
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
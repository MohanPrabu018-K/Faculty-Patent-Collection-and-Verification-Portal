from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class OCRExtractionAgent:
    """Agent 3: Performs OCR and extracts structured fields from document text."""

    name = "OCRExtractionAgent"

    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()

        try:
            from app.services.extraction import StructuredExtractionService
            from app.services.ocr_pipeline import process_document

            processing = process_document(input_data.file_data, filename=input_data.filename)
            ocr_text = processing.ocr.text or ""

            if not ocr_text.strip():
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.ERROR,
                    confidence=0.0,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[{"source": "ocr_pipeline", "warnings": processing.warnings}],
                    warnings=processing.warnings or ["OCR failed to extract text"],
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                    error="OCR failed to extract text",
                )

            ip_type = input_data.ip_type
            if not ip_type or ip_type == "UNKNOWN_OTHER":
                text_lower = ocr_text.lower()
                design_keywords = ["design", "registration", "certificate", "serial number"]
                patent_keywords = ["patent", "application number", "inventor", "grant date"]
                design_score = sum(1 for kw in design_keywords if kw in text_lower)
                patent_score = sum(1 for kw in patent_keywords if kw in text_lower)
                if design_score > patent_score:
                    ip_type = "DESIGN_REGISTRATION"
                elif patent_score > 0:
                    ip_type = "PATENT"
                else:
                    ip_type = "UNKNOWN_OTHER"

            extraction_service = StructuredExtractionService()
            extraction_result = extraction_service.extract_from_text(
                ocr_text,
                ip_type,
                qr_data=processing.qr.qr_data[0] if processing.qr.qr_data else None,
            )

            extracted_data = extraction_result.get("normalized_fields", {})
            extracted_data["ip_type"] = ip_type
            extracted_data["ocr_text"] = ocr_text[:500]
            extracted_data["qr_data"] = processing.qr.qr_data
            extracted_data["ocr_has_text_layer"] = processing.has_text_layer
            extracted_data["ocr_engine"] = processing.ocr.source

            evidence_map = extraction_result.get("normalized_fields", {})
            standardized_evidence: list[dict[str, Any]] = []
            for field, entries in evidence_map.items():
                if isinstance(entries, list):
                    for entry in entries:
                        standardized_evidence.append(
                            {
                                "field": field,
                                "value": entry.get("value"),
                                "source": entry.get("source", "ocr_text"),
                                "confidence": entry.get("confidence", 0.0),
                            }
                        )

            overall_confidence = extraction_result.get("confidence", processing.ocr.confidence)
            confidence_level = (
                ConfidenceLevel.HIGH
                if overall_confidence >= 0.75
                else ConfidenceLevel.MEDIUM
                if overall_confidence >= 0.5
                else ConfidenceLevel.LOW
            )
            requires_review = extraction_result.get("requires_review", False) or overall_confidence < 0.5
            warnings = list(processing.ocr.warnings) + list(processing.warnings)
            if overall_confidence < 0.5:
                warnings.append(f"Low OCR confidence: {overall_confidence}")
            if not ocr_text.strip():
                warnings.append("No readable text found in document")

            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=extracted_data,
                confidence=overall_confidence,
                confidence_level=confidence_level,
                evidence=standardized_evidence or processing.ocr.evidence,
                warnings=warnings,
                conflicts=extraction_result.get("conflicts", []),
                recommendation=extracted_data.get("patent_number") or extracted_data.get("design_number"),
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
                warnings=[f"OCR extraction agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=time.time() - start_time,
                error=str(e),
            )

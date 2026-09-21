from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


# Maximum OCR characters forwarded into agent context (extracted_data.ocr_text).
# Downstream agents (understanding, verification, identity, duplicate) read this
# field, so truncating it too aggressively starves canonical extraction: fields
# located later in the document (e.g. journal inventor lists) become invisible.
# 15000 matches the record-isolation cap in StructuredExtractionService and keeps
# full single-document text (~2-4KB typical) while bounding context/DB size.
OCR_TEXT_CONTEXT_CHARS = 15000


class OCRExtractionAgent:
    """Agent 3: Performs OCR and extracts structured fields from document text."""

    name = "OCRExtractionAgent"

    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()

        try:
            from app.services.extraction import StructuredExtractionService
            from app.services.ocr_pipeline import process_document

            # ---------------------------------------------------------
            # 1. OCR
            # ---------------------------------------------------------
            processing = process_document(
                input_data.file_data,
                filename=input_data.filename,
            )

            ocr_text = processing.ocr.text or ""

            if not ocr_text.strip():
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.ERROR,
                    confidence=0.0,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[
                        {
                            "source": "ocr_pipeline",
                            "warnings": processing.warnings,
                        }
                    ],
                    warnings=(
                        processing.warnings
                        or ["OCR failed to extract text"]
                    ),
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                    error="OCR failed to extract text",
                )

            # ---------------------------------------------------------
            # 2. Determine IP type
            # ---------------------------------------------------------
            ip_type = input_data.ip_type

            if not ip_type or ip_type == "UNKNOWN_OTHER":
                text_lower = ocr_text.lower()

                design_keywords = [
                    "design",
                    "registration",
                    "certificate",
                    "serial number",
                ]

                patent_keywords = [
                    "patent",
                    "application number",
                    "inventor",
                    "grant date",
                ]

                design_score = sum(
                    1
                    for keyword in design_keywords
                    if keyword in text_lower
                )

                patent_score = sum(
                    1
                    for keyword in patent_keywords
                    if keyword in text_lower
                )

                if design_score > patent_score:
                    ip_type = "DESIGN_REGISTRATION"

                elif patent_score > 0:
                    ip_type = "PATENT"

                else:
                    ip_type = "UNKNOWN_OTHER"

            # ---------------------------------------------------------
            # 3. Structured extraction
            # ---------------------------------------------------------
            extraction_service = StructuredExtractionService()

            qr_data = None

            if (
                getattr(processing, "qr", None)
                and getattr(processing.qr, "qr_data", None)
            ):
                qr_values = processing.qr.qr_data

                if isinstance(qr_values, list) and qr_values:
                    qr_data = qr_values[0]

                elif isinstance(qr_values, str):
                    qr_data = qr_values

            extraction_result = (
                extraction_service.extract_from_text(
                    ocr_text,
                    ip_type,
                    qr_data=qr_data,
                )
            )

            # Defensive check.
            if not isinstance(extraction_result, dict):
                raise TypeError(
                    "StructuredExtractionService returned "
                    f"{type(extraction_result).__name__}; expected dict"
                )

            # ---------------------------------------------------------
            # 4. Normalized extracted fields
            # ---------------------------------------------------------
            normalized_fields = extraction_result.get(
                "normalized_fields",
                {},
            )

            if not isinstance(normalized_fields, dict):
                normalized_fields = {}

            extracted_data: dict[str, Any] = dict(
                normalized_fields
            )

            extracted_data["ip_type"] = ip_type
            extracted_data["ocr_text"] = ocr_text[:OCR_TEXT_CONTEXT_CHARS]

            qr_values = []

            if (
                getattr(processing, "qr", None)
                and getattr(processing.qr, "qr_data", None)
            ):
                if isinstance(
                    processing.qr.qr_data,
                    list,
                ):
                    qr_values = processing.qr.qr_data

                elif isinstance(
                    processing.qr.qr_data,
                    str,
                ):
                    qr_values = [
                        processing.qr.qr_data
                    ]

            extracted_data["qr_data"] = qr_values

            extracted_data["ocr_has_text_layer"] = (
                processing.has_text_layer
            )

            extracted_data["ocr_engine"] = (
                processing.ocr.source
            )

            # ---------------------------------------------------------
            # 5. Standardized evidence
            #
            # Extraction service normally returns:
            #
            # field -> [
            #     {
            #         "value": ...,
            #         "source": ...,
            #         "confidence": ...
            #     }
            # ]
            #
            # But some fields may contain strings/scalars.
            # Never allow that to crash the pipeline.
            # ---------------------------------------------------------
            standardized_evidence: list[dict[str, Any]] = []

            for field, entries in normalized_fields.items():

                # Case 1:
                # Field value is a list of evidence entries.
                if isinstance(entries, list):

                    for entry in entries:

                        if isinstance(entry, dict):
                            standardized_evidence.append(
                                {
                                    "field": field,
                                    "value": entry.get(
                                        "value"
                                    ),
                                    "source": entry.get(
                                        "source",
                                        "ocr_text",
                                    ),
                                    "confidence": entry.get(
                                        "confidence",
                                        0.0,
                                    ),
                                }
                            )

                        else:
                            # Defensive fallback for strings,
                            # numbers, dates, etc.
                            standardized_evidence.append(
                                {
                                    "field": field,
                                    "value": entry,
                                    "source": "ocr_text",
                                    "confidence": 0.0,
                                }
                            )

                # Case 2:
                # Field itself is a single evidence dictionary.
                elif isinstance(entries, dict):

                    standardized_evidence.append(
                        {
                            "field": field,
                            "value": entries.get("value"),
                            "source": entries.get(
                                "source",
                                "ocr_text",
                            ),
                            "confidence": entries.get(
                                "confidence",
                                0.0,
                            ),
                        }
                    )

                # Case 3:
                # Field itself is a scalar/string.
                elif entries is not None:

                    standardized_evidence.append(
                        {
                            "field": field,
                            "value": entries,
                            "source": "ocr_text",
                            "confidence": 0.0,
                        }
                    )

            # ---------------------------------------------------------
            # 6. Confidence
            # ---------------------------------------------------------
            overall_confidence = extraction_result.get(
                "confidence",
                processing.ocr.confidence,
            )

            # Defensive numeric conversion.
            try:
                overall_confidence = float(
                    overall_confidence
                )
            except (
                TypeError,
                ValueError,
            ):
                overall_confidence = float(
                    processing.ocr.confidence or 0.0
                )

            if overall_confidence >= 0.75:
                confidence_level = ConfidenceLevel.HIGH

            elif overall_confidence >= 0.5:
                confidence_level = ConfidenceLevel.MEDIUM

            else:
                confidence_level = ConfidenceLevel.LOW

            # ---------------------------------------------------------
            # 7. Review / warnings
            # ---------------------------------------------------------
            requires_review = (
                extraction_result.get(
                    "requires_review",
                    False,
                )
                or overall_confidence < 0.5
            )

            warnings: list[str] = []

            if getattr(
                processing.ocr,
                "warnings",
                None,
            ):
                warnings.extend(
                    processing.ocr.warnings
                )

            if getattr(
                processing,
                "warnings",
                None,
            ):
                warnings.extend(
                    processing.warnings
                )

            if overall_confidence < 0.5:
                warnings.append(
                    f"Low OCR confidence: "
                    f"{overall_confidence}"
                )

            # ---------------------------------------------------------
            # 8. Conflicts
            # ---------------------------------------------------------
            conflicts = extraction_result.get(
                "conflicts",
                [],
            )

            if not isinstance(conflicts, list):
                conflicts = [conflicts]

            # ---------------------------------------------------------
            # 9. Recommendation
            # ---------------------------------------------------------
            recommendation = None

            patent_number = extracted_data.get(
                "patent_number"
            )

            design_number = extracted_data.get(
                "design_number"
            )

            if patent_number:
                recommendation = patent_number

            elif design_number:
                recommendation = design_number

            # ---------------------------------------------------------
            # 10. SUCCESS
            # ---------------------------------------------------------
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=extracted_data,
                confidence=overall_confidence,
                confidence_level=confidence_level,
                evidence=(
                    standardized_evidence
                    or processing.ocr.evidence
                ),
                warnings=warnings,
                conflicts=conflicts,
                recommendation=recommendation,
                requires_human_review=requires_review,
                processing_time=(
                    time.time() - start_time
                ),
            )

        except Exception as e:

            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.ERROR,
                confidence=0.0,
                confidence_level=ConfidenceLevel.LOW,
                evidence=[],
                warnings=[
                    "OCR extraction agent error: "
                    f"{str(e)}"
                ],
                conflicts=[],
                requires_human_review=True,
                processing_time=(
                    time.time() - start_time
                ),
                error=str(e),
            )
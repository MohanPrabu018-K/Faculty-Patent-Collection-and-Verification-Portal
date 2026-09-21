from __future__ import annotations

import time

from app.core.ai_contracts import AgentOutput, AgentStatus, ConfidenceLevel, OrchestratorInput


class VerificationAgent:
    name = "VerificationAgent"

    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        try:
            from app.verification.adapters import verify_patent_or_design

            # Read canonical data from context (set by orchestrator after OCR Extraction)
            canonical_data = input_data.context.get("canonical_data", {}) if input_data.context else {}
            
            patent_number = canonical_data.get("patent_number")
            design_number = canonical_data.get("design_number")
            application_number = canonical_data.get("application_number")

            if not patent_number and not design_number and not application_number:
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    extracted_data={"verification_status": "VERIFICATION_REQUIRED"},
                    confidence=0.1,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[{"source": "verification", "status": "VERIFICATION_REQUIRED", "reason": "missing_identifier"}],
                    warnings=["No patent, design, or application number available for verification"],
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                )

            resolved_ip_type = canonical_data.get("ip_type")
            if resolved_ip_type not in ("PATENT", "DESIGN_REGISTRATION"):
                resolved_ip_type = (
                    "PATENT"
                    if (patent_number or application_number)
                    else "DESIGN_REGISTRATION"
                )

            verification_result = await verify_patent_or_design(
                ip_type=resolved_ip_type,
                identifier=patent_number or design_number or application_number or "",
                title=canonical_data.get("title"),
                applicant=canonical_data.get("applicant"),
                inventor=canonical_data.get("inventors", [None])[0] if canonical_data.get("inventors") else None,
                filing_date=str(canonical_data.get("filing_date")) if canonical_data.get("filing_date") else None,
            )

            if verification_result.matched_data:
                canonical_data.update(verification_result.matched_data)

            # Store field comparisons in canonical data for downstream agents
            canonical_data["verification_field_comparisons"] = [
                {
                    "field": fc.field_name,
                    "certificate_value": fc.certificate_value,
                    "official_value": fc.official_value,
                    "status": fc.status,
                    "confidence": fc.confidence,
                }
                for fc in verification_result.field_comparisons
            ]

            status_map = {
                "VERIFIED": "VERIFIED",
                "MISMATCH": "MISMATCH",
                "NOT_FOUND": "NOT_FOUND",
                "ERROR": "ERROR",
                "VERIFICATION_REQUIRED": "VERIFICATION_REQUIRED",
            }
            verification_status = status_map.get(verification_result.status, verification_result.status)
            canonical_data["verification_status"] = verification_status
            canonical_data["verification_source"] = verification_result.source

            # Create conflicts for field mismatches
            conflicts = []
            for fc in verification_result.field_comparisons:
                if fc.status == "MISMATCH":
                    conflicts.append({
                        "type": "verification_mismatch",
                        "field": fc.field_name,
                        "description": f"Field '{fc.field_name}' mismatch: certificate='{fc.certificate_value}' vs official='{fc.official_value}'",
                        "certificate_value": fc.certificate_value,
                        "official_value": fc.official_value,
                        "confidence": fc.confidence,
                        "severity": "high",
                    })

            confidence = verification_result.confidence or 0.0
            confidence_level = ConfidenceLevel.HIGH if confidence >= 0.75 else ConfidenceLevel.MEDIUM if confidence >= 0.5 else ConfidenceLevel.LOW
            requires_review = verification_status in {"MISMATCH", "VERIFICATION_REQUIRED", "NOT_FOUND"} or confidence < 0.5

            # Build evidence including field comparisons
            evidence = [{
                "source": verification_result.source,
                "status": verification_status,
                "matched_data": verification_result.matched_data,
                "error": verification_result.error,
                "field_comparisons": [
                    {
                        "field": fc.field_name,
                        "certificate_value": fc.certificate_value,
                        "official_value": fc.official_value,
                        "status": fc.status,
                        "confidence": fc.confidence,
                    }
                    for fc in verification_result.field_comparisons
                ],
            }]

            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=canonical_data,
                confidence=confidence,
                confidence_level=confidence_level,
                evidence=evidence,
                warnings=[verification_result.error] if verification_result.error else [],
                conflicts=conflicts,
                recommendation=verification_status,
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
                warnings=[f"Verification agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=time.time() - start_time,
                error=str(e),
            )

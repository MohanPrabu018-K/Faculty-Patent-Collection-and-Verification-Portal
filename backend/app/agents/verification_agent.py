from __future__ import annotations

import time

from app.core.ai_contracts import AgentOutput, AgentStatus, ConfidenceLevel, OrchestratorInput


class VerificationAgent:
    name = "VerificationAgent"

    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        try:
            from app.verification.adapters import verify_patent_or_design

            extracted_data = dict((input_data.context or {}).get("extracted_data", {}))
            patent_number = extracted_data.get("patent_number")
            design_number = extracted_data.get("design_number")

            if not patent_number and not design_number:
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    extracted_data={"verification_status": "VERIFICATION_REQUIRED"},
                    confidence=0.1,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[{"source": "verification", "status": "VERIFICATION_REQUIRED", "reason": "missing_identifier"}],
                    warnings=["No patent number or design number available for verification"],
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                )

            verification_result = await verify_patent_or_design(
                ip_type="PATENT" if patent_number else "DESIGN_REGISTRATION",
                identifier=patent_number or design_number or "",
                title=extracted_data.get("title"),
                applicant=extracted_data.get("applicant"),
                inventor=extracted_data.get("inventor") or extracted_data.get("inventors", [None])[0],
                filing_date=str(extracted_data.get("filing_date")) if extracted_data.get("filing_date") else None,
            )

            if verification_result.matched_data:
                extracted_data.update(verification_result.matched_data)

            status_map = {
                "VERIFIED": "VERIFIED",
                "MISMATCH": "MISMATCH",
                "NOT_FOUND": "NOT_FOUND",
                "ERROR": "ERROR",
                "VERIFICATION_REQUIRED": "VERIFICATION_REQUIRED",
            }
            verification_status = status_map.get(verification_result.status, verification_result.status)
            extracted_data["verification_status"] = verification_status
            extracted_data["verification_source"] = verification_result.source

            confidence = verification_result.confidence or 0.0
            confidence_level = ConfidenceLevel.HIGH if confidence >= 0.75 else ConfidenceLevel.MEDIUM if confidence >= 0.5 else ConfidenceLevel.LOW
            requires_review = verification_status in {"MISMATCH", "VERIFICATION_REQUIRED", "NOT_FOUND"} or confidence < 0.5

            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=extracted_data,
                confidence=confidence,
                confidence_level=confidence_level,
                evidence=[{"source": verification_result.source, "status": verification_status, "matched_data": verification_result.matched_data, "error": verification_result.error}],
                warnings=[verification_result.error] if verification_result.error else [],
                conflicts=[],
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

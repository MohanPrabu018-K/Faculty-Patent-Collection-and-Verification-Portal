from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class DuplicateDetectionAgent:
    """Agent 7: Detects duplicate patent/design submissions.
    
    Uses existing DuplicateDetectionService from Phase M.
    Checks for:
    - Same patent number/design number
    - Same inventor combinations
    - Similar document text content
    - File fingerprint (SHA-256) matching
    """
    
    name = "DuplicateDetectionAgent"
    
    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        
        try:
            from app.services.duplicate_detection import DuplicateDetectionService
            
            extracted_data: dict[str, Any] = {}
            evidence_list: list[dict[str, Any]] = []
            warnings: list[str] = []
            conflicts: list[dict[str, Any]] = []
            
            # Get extracted fields (coerce list/dict provenance values to scalars)
            extracted_data_input = input_data.context.get("extracted_data", {}) if input_data.context else {}

            def _scalar(value):
                if isinstance(value, list):
                    value = value[0] if value else None
                if isinstance(value, dict):
                    value = value.get("value") or value.get("name") or value.get("text")
                return value

            patent_number = _scalar(extracted_data_input.get("patent_number"))
            design_number = _scalar(extracted_data_input.get("design_number"))
            inventors = extracted_data_input.get("inventors", []) or []
            
            # Compute the file fingerprint directly (never rely on context).
            file_hash = None
            if input_data.file_data:
                from app.services.duplicate_detection import calculate_file_fingerprint
                file_hash = calculate_file_fingerprint(input_data.file_data)
            
            if not patent_number and not design_number:
                # Can't check for duplicates without an identifier
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    extracted_data={},
                    confidence=0.1,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[],
                    warnings=["No patent number or design number available for duplicate detection"],
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                )
            
            # Initialize duplicate detection service
            dd_service = DuplicateDetectionService()
            
            # Check for duplicates against the REAL database-backed records.
            duplicate_checks: list[dict[str, Any]] = []
            existing_records = self._load_existing_records(patent_number, design_number)
            
            if patent_number or design_number:
                new_record = {
                    "patent_number": patent_number,
                    "design_number": design_number,
                    "inventors": inventors,
                }
                dup_candidates = await dd_service.check_for_duplicates(new_record, existing_records, input_data.file_data)

                if patent_number:
                    duplicate_checks.append({
                        "type": "patent_number",
                        "is_duplicate": False,
                        "confidence": 0.0,
                        "existing_case": None,
                    })
                if design_number:
                    duplicate_checks.append({
                        "type": "design_number",
                        "is_duplicate": False,
                        "confidence": 0.0,
                        "existing_case": None,
                    })
                
                if dup_candidates:
                    best = dup_candidates[0]
                    conflicts.append({
                        "type": "duplicate_record",
                        "description": f"Possible duplicate detected for record {best.record_id}",
                        "existing_case": best.record_id,
                        "confidence": float(best.overall_confidence),
                        "match_method": best.detection_method.value,
                    })
                    warnings.append("Possible duplicate record detected - requires review before proceeding")
            
            # File fingerprint was already computed above and included in
            # existing_records comparison; record it as evidence only.
            if file_hash:
                duplicate_checks.append({
                    "type": "file_fingerprint",
                    "is_duplicate": False,
                    "confidence": 0.0,
                    "existing_case": None,
                })
            
            # Check inventor similarity if inventors available
            if inventors:
                # Preserve the semantic inventor values, but never assume numeric items.
                normalized_inventors = []
                for inventor in inventors:
                    if isinstance(inventor, dict):
                        value = inventor.get("value") or inventor.get("name") or inventor.get("text")
                        if value:
                            normalized_inventors.append(value)
                    elif inventor:
                        normalized_inventors.append(str(inventor))
                duplicate_checks.append({
                    "type": "inventor_combination",
                    "inventors": normalized_inventors or inventors,
                })
            
            # Calculate overall confidence
            if duplicate_checks:
                max_conf = max(c.get("confidence", 0.0) for c in duplicate_checks)
                overall_confidence = max_conf
            else:
                overall_confidence = 0.1
            
            confidence_level = (
                ConfidenceLevel.HIGH if overall_confidence >= 0.75 else
                ConfidenceLevel.MEDIUM if overall_confidence >= 0.5 else
                ConfidenceLevel.LOW
            )
            
            # Build evidence
            evidence_list = duplicate_checks
            
            # Determine if human review is required
            requires_review = (
                overall_confidence >= 0.5 or  # Any duplicate detected needs review
                len(conflicts) > 0
            )
            
            processing_time = time.time() - start_time
            
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=extracted_data,
                confidence=overall_confidence,
                confidence_level=confidence_level,
                evidence=evidence_list,
                warnings=warnings,
                conflicts=conflicts,
                recommendation=conflicts[0]["type"] if conflicts else None,
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
                warnings=[f"Duplicate detection agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=processing_time,
                error=str(e),
            )

    def _load_existing_records(self, patent_number, design_number) -> list[dict[str, Any]]:
        """Load candidate duplicate records from the real PostgreSQL database."""
        try:
            from sqlalchemy import or_, select
            from app.core.database import get_session
            from app.models.base import IpContributor, IpFile, IpRecord

            session = get_session()
            try:
                query = select(IpRecord)
                conditions = []
                if patent_number:
                    conditions.append(IpRecord.patent_number == patent_number)
                if design_number:
                    conditions.append(IpRecord.design_number == design_number)
                if conditions:
                    query = query.where(or_(*conditions))
                else:
                    return []

                records = session.execute(query).scalars().all()
                record_ids = [r.id for r in records]

                fingerprints = {}
                if record_ids:
                    fingerprints = {
                        f.ip_record_id: f.fingerprint
                        for f in session.execute(
                            select(IpFile).where(IpFile.ip_record_id.in_(record_ids))
                        ).scalars().all()
                        if f.fingerprint
                    }

                contributors: dict[str, list[str]] = {}
                if record_ids:
                    contrib_rows = session.execute(
                        select(IpContributor).where(IpContributor.ip_record_id.in_(record_ids))
                    ).scalars().all()
                    for c in contrib_rows:
                        contributors.setdefault(c.ip_record_id, []).append(c.name)
            finally:
                session.close()

            return [
                {
                    "id": r.id,
                    "ip_type": r.ip_type,
                    "patent_number": r.patent_number,
                    "application_number": r.application_number,
                    "design_number": r.design_number,
                    "serial_number": r.serial_number,
                    "title": r.title,
                    "applicant": r.applicant,
                    "inventors": contributors.get(r.id, []),
                    "filing_date": r.filing_date.isoformat() if r.filing_date else None,
                    "fingerprint": fingerprints.get(r.id),
                    "uploader_id": r.uploader_id,
                }
                for r in records
            ]
        except Exception:
            return []
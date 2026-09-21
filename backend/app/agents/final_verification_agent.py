"""Agent 11: Final Verification Decision Gate.

Determines the final verification status based on all evidence:
- Official verification result
- Extraction confidence
- Identity resolution results
- Duplicate/conflict status
- Faculty approval state
- Data quality metrics

This is the deterministic decision gate that ensures no record reaches
VERIFIED without meeting strict criteria.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class FinalVerificationAgent:
    """Final verification decision gate.
    
    Evaluates all pipeline outputs and makes a deterministic decision:
    - VERIFIED: Sufficient evidence for approval
    - REJECTED: Clear evidence against
    - NEEDS_REVIEW: Insufficient evidence or unresolved conflicts
    """
    
    name = "FinalVerificationAgent"
    
    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        
        try:
            extracted_data: dict[str, Any] = {}
            evidence_list: list[dict[str, Any]] = []
            warnings: list[str] = []
            conflicts: list[dict[str, Any]] = []
            
            # Read canonical data from context
            canonical_data = input_data.context.get("canonical_data", {}) if input_data.context else {}
            
            # Collect all agent outputs for decision making
            agent_outputs = input_data.context.get("agent_outputs", []) if input_data.context else []
            
            # Extract key decision factors — use agent_outputs for accurate confidence (canonical_data lacks confidence)
            verification_status = canonical_data.get("verification_status", "VERIFICATION_REQUIRED")
            # Verification confidence from VerificationAgent output (not canonical)
            verification_output = next((a for a in agent_outputs if a.get("agent_name") == "VerificationAgent"), None)
            verification_confidence = 0.0
            if verification_output is not None:
                verification_confidence = float(verification_output.get("confidence", 0.0) or 0.0)
            if verification_confidence == 0.0:
                verification_confidence = float(canonical_data.get("verification_confidence", 0.0) or 0.0)
            # Extraction confidence from OCRExtractionAgent (canonical_data.get("confidence") is wrong location)
            ocr_output = next((a for a in agent_outputs if a.get("agent_name") == "OCRExtractionAgent"), None)
            extraction_confidence = 0.0
            if ocr_output is not None:
                extraction_confidence = float(ocr_output.get("confidence", 0.0) or 0.0)
            if extraction_confidence == 0.0:
                # Fallback to canonical or extracted_data confidence
                extraction_confidence = float(canonical_data.get("confidence", 0.0) or input_data.context.get("extracted_data", {}).get("confidence", 0.0) or 0.0)
            
            # Get identity resolution results
            identity_output = next(
                (a for a in agent_outputs if a.get("agent_name") == "FacultyIdentityResolutionAgent"),
                None
            )
            resolved_entities = (identity_output or {}).get("extracted_data", {}).get("resolved_entities", []) or []
            
            # Get duplicate detection results
            duplicate_output = next(
                (a for a in agent_outputs if a.get("agent_name") == "DuplicateDetectionAgent"),
                None
            )
            duplicate_conflicts = (duplicate_output or {}).get("conflicts", []) or []
            
            # Get conflict resolution results
            conflict_output = next(
                (a for a in agent_outputs if a.get("agent_name") == "ConflictResolutionAgent"),
                None
            )
            critical_conflicts = (conflict_output or {}).get("conflicts", []) or []
            
            # Get data quality results
            quality_output = next(
                (a for a in agent_outputs if a.get("agent_name") == "DataQualityAgent"),
                None
            )
            field_completeness = (quality_output or {}).get("extracted_data", {}).get("field_completeness", 0.0)
            evidence_coverage = (quality_output or {}).get("extracted_data", {}).get("evidence_coverage", 0.0)
            
            # Check for faculty approval state (from real association workflow)
            record_id = getattr(input_data, "upload_id", None)
            has_faculty_approval = self._check_faculty_approval(
                resolved_entities, record_id
            )
            
            # Apply decision rules
            final_status, rationale, final_confidence = self._decide_verification(
                verification_status=verification_status,
                verification_confidence=verification_confidence,
                extraction_confidence=extraction_confidence,
                resolved_entities=resolved_entities,
                duplicate_conflicts=duplicate_conflicts,
                critical_conflicts=critical_conflicts,
                field_completeness=field_completeness,
                evidence_coverage=evidence_coverage,
                has_faculty_approval=has_faculty_approval,
            )
            
            # Build evidence
            evidence_list = [
                {
                    "source": "final_verification",
                    "verification_status": verification_status,
                    "verification_confidence": verification_confidence,
                    "extraction_confidence": extraction_confidence,
                    "field_completeness": field_completeness,
                    "evidence_coverage": evidence_coverage,
                    "has_faculty_approval": has_faculty_approval,
                    "unresolved_duplicates": len(duplicate_conflicts),
                    "unresolved_conflicts": len([c for c in critical_conflicts if c.get("severity") in ("high", "medium")]),
                    "decision": final_status,
                    "rationale": rationale,
                }
            ]
            
            # Determine confidence level
            if final_confidence >= 0.75:
                confidence_level = ConfidenceLevel.HIGH
            elif final_confidence >= 0.5:
                confidence_level = ConfidenceLevel.MEDIUM
            else:
                confidence_level = ConfidenceLevel.LOW
            
            # Requires review if not VERIFIED or REJECTED
            requires_review = final_status == "NEEDS_REVIEW"
            
            # Add warnings for NEEDS_REVIEW
            if requires_review:
                warnings.append(f"Final verification: {rationale}")
            
            # Add conflicts from critical conflicts
            conflicts.extend(critical_conflicts)
            
            # Store final verification in canonical data
            canonical_data["final_verification_status"] = final_status
            canonical_data["final_verification_rationale"] = rationale
            canonical_data["final_verification_confidence"] = final_confidence
            
            extracted_data = {
                "final_verification_status": final_status,
                "final_verification_rationale": rationale,
                "final_verification_confidence": final_confidence,
            }
            
            processing_time = time.time() - start_time
            
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=extracted_data,
                confidence=final_confidence,
                confidence_level=confidence_level,
                evidence=evidence_list,
                warnings=warnings,
                conflicts=conflicts,
                recommendation=final_status,
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
                warnings=[f"Final verification agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=processing_time,
                error=str(e),
            )
    
    def _check_faculty_approval(
        self,
        resolved_entities: list[dict[str, Any]],
        record_id: str | None = None,
    ) -> bool:
        """Check real association workflow state for internal contributors.

        Returns True only when every credibly matched internal faculty member
        other than the uploader has an ACCEPTED/APPROVED association request
        linking them to this record (or its master). The uploader approves by
        the act of uploading. Anything uncertain — missing record, DB error,
        no acceptance on file — stays False (conservative).
        """
        from app.workers.orchestrator_task import _IDENTITY_INTERNAL_THRESHOLD

        internal_ids: list[str] = []
        for entity in resolved_entities or []:
            if not isinstance(entity, dict):
                continue
            best = entity.get("best_match") or {}
            if not isinstance(best, dict):
                continue
            try:
                confidence = float(best.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            user_id = best.get("id") or best.get("faculty_id")
            if user_id and confidence >= _IDENTITY_INTERNAL_THRESHOLD:
                uid = str(user_id)
                if uid not in internal_ids:
                    internal_ids.append(uid)

        if not record_id:
            return False

        try:
            from sqlalchemy import or_, select

            from app.core.database import get_session
            from app.models.base import AssociationRequest, IpRecord

            session = get_session()
            try:
                record = session.execute(
                    select(IpRecord).where(IpRecord.id == record_id)
                ).scalar_one_or_none()
                if not record:
                    return False
                uploader_id = str(record.uploader_id or "")
                master_id = record.master_ip_id

                others = [uid for uid in internal_ids if uid != uploader_id]
                if not others:
                    # No other internal contributors: nothing pending approval,
                    # but the uploader must be a matched internal faculty member
                    # for the upload itself to count as approval.
                    return uploader_id in internal_ids

                for uid in others:
                    pair = or_(
                        or_(
                            AssociationRequest.requesting_faculty_id == uploader_id,
                            AssociationRequest.requester_id == uploader_id,
                        )
                        & or_(
                            AssociationRequest.target_faculty_id == uid,
                            AssociationRequest.recipient_id == uid,
                        ),
                        or_(
                            AssociationRequest.requesting_faculty_id == uid,
                            AssociationRequest.requester_id == uid,
                        )
                        & or_(
                            AssociationRequest.target_faculty_id == uploader_id,
                            AssociationRequest.recipient_id == uploader_id,
                        ),
                    )
                    scope = AssociationRequest.ip_record_id == record_id
                    if master_id:
                        scope = or_(
                            scope,
                            AssociationRequest.master_ip_id == master_id,
                        )
                    accepted = session.execute(
                        select(AssociationRequest).where(
                            pair,
                            scope,
                            AssociationRequest.status.in_(
                                ("ACCEPTED", "APPROVED")
                            ),
                        ).limit(1)
                    ).scalar_one_or_none()
                    if not accepted:
                        return False
                return True
            finally:
                session.close()
        except Exception:
            return False
    
    def _decide_verification(
        self,
        verification_status: str,
        verification_confidence: float,
        extraction_confidence: float,
        resolved_entities: list[dict[str, Any]],
        duplicate_conflicts: list[dict[str, Any]],
        critical_conflicts: list[dict[str, Any]],
        field_completeness: float,
        evidence_coverage: float,
        has_faculty_approval: bool,
    ) -> tuple[str, str, float]:
        """Apply deterministic decision rules.
        
        Returns:
            (final_status, rationale, confidence)
        """
        
        # Rule 1: Official verification is VERIFIED with high confidence — still requires no unresolved duplicates/conflicts and complete evidence
        if verification_status == "VERIFIED" and verification_confidence >= 0.85:
            # Even with official VERIFIED, unresolved duplicates/critical conflicts block auto-VERIFIED
            has_unresolved_dup = len(duplicate_conflicts) > 0
            has_unresolved_critical = any(c.get("severity") in ("high", "medium") for c in critical_conflicts) or any(
                c.get("type") in ("duplicate_design", "duplicate_patent", "duplicate_record") for c in duplicate_conflicts
            )
            # Check field completeness and evidence as well
            if has_unresolved_dup or has_unresolved_critical or field_completeness < 0.75 or evidence_coverage < 0.8 or not has_faculty_approval:
                missing = []
                if has_unresolved_dup:
                    missing.append(f"{len(duplicate_conflicts)} unresolved duplicate(s)")
                if has_unresolved_critical:
                    missing.append("unresolved critical conflicts")
                if field_completeness < 0.75:
                    missing.append(f"field completeness {field_completeness:.2f} < 0.75")
                if evidence_coverage < 0.8:
                    missing.append(f"evidence coverage {evidence_coverage:.2f} < 0.8")
                if not has_faculty_approval:
                    missing.append("faculty approval pending")
                return "NEEDS_REVIEW", f"Official VERIFIED but insufficient for auto-verification: {', '.join(missing)}", 0.4
            return "VERIFIED", "Official source confirmed with high confidence", max(verification_confidence, 0.9)
        
        # Rule 2: Official verification is MISMATCH and unresolved
        if verification_status == "MISMATCH":
            return "NEEDS_REVIEW", "Official verification mismatch - requires manual resolution", 0.3
        
        # Rule 3: Official verification is VERIFICATION_REQUIRED (unavailable)
        if verification_status == "VERIFICATION_REQUIRED":
            # Only allow VERIFIED if all conditions met
            all_conditions_met = (
                extraction_confidence >= 0.75 and
                field_completeness >= 0.75 and
                evidence_coverage >= 0.8 and
                len(duplicate_conflicts) == 0 and
                len([c for c in critical_conflicts if c.get("severity") in ("high", "medium")]) == 0 and
                has_faculty_approval
            )
            
            if all_conditions_met:
                return "VERIFIED", "High-confidence extraction with complete evidence and faculty approval", 0.8
            else:
                missing = []
                if extraction_confidence < 0.75:
                    missing.append(f"extraction confidence {extraction_confidence:.2f} < 0.75")
                if field_completeness < 0.75:
                    missing.append(f"field completeness {field_completeness:.2f} < 0.75")
                if evidence_coverage < 0.8:
                    missing.append(f"evidence coverage {evidence_coverage:.2f} < 0.8")
                if duplicate_conflicts:
                    missing.append(f"{len(duplicate_conflicts)} unresolved duplicate(s)")
                if any(c.get("severity") in ("high", "medium") for c in critical_conflicts):
                    missing.append("unresolved critical conflicts")
                if not has_faculty_approval:
                    missing.append("faculty approval pending")
                
                return "NEEDS_REVIEW", f"Insufficient for auto-verification: {', '.join(missing)}", 0.4
        
        # Rule 4: Official verification NOT_FOUND
        if verification_status == "NOT_FOUND":
            if (extraction_confidence >= 0.85 and 
                field_completeness >= 0.8 and
                evidence_coverage >= 0.8 and
                len(duplicate_conflicts) == 0 and
                len([c for c in critical_conflicts if c.get("severity") in ("high", "medium")]) == 0):
                return "VERIFIED", "High-confidence extraction, official record not found (may be lag)", 0.75
            else:
                return "NEEDS_REVIEW", "Official record not found, insufficient evidence for auto-verification", 0.3
        
        # Rule 5: Official verification ERROR
        if verification_status == "ERROR":
            return "NEEDS_REVIEW", "Official verification error - manual review required", 0.2
        
        # Default: NEEDS_REVIEW
        return "NEEDS_REVIEW", "Default conservative decision - manual review required", 0.2
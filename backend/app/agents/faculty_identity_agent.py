from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class FacultyIdentityResolutionAgent:
    """Agent 6: Resolves faculty identity - normalizes names, detects 
    same-name collisions, and identifies potential duplicate faculty records.
    
    Uses existing IdentityResolutionService from Phase L.
    Ensures AI does NOT directly finalize faculty identity - only recommends.
    """
    
    name = "FacultyIdentityResolutionAgent"
    
    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        
        try:
            from app.services.identity_resolution import IdentityResolutionService
            
            extracted_data: dict[str, Any] = {}
            evidence_list: list[dict[str, Any]] = []
            warnings: list[str] = []
            conflicts: list[dict[str, Any]] = []
            
            # Get faculty name from extracted data or context
            extracted_data_input = input_data.context.get("extracted_data", {}) if input_data.context else {}
            faculty_name = extracted_data_input.get("applicant") or extracted_data_input.get("inventor")
            
            if not faculty_name:
                # No faculty name available - mark for review later
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    extracted_data={},
                    confidence=0.1,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[],
                    warnings=["No faculty name available for identity resolution"],
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                )
            
            # Initialize identity resolution service
            ir_service = IdentityResolutionService()

            # Normalize the name and coerce list/dict values to a clean string.
            if isinstance(faculty_name, list):
                faculty_name = faculty_name[0] if faculty_name else ""
            if isinstance(faculty_name, dict):
                faculty_name = faculty_name.get("value") or faculty_name.get("name") or ""
            faculty_name = str(faculty_name).strip()
            if not faculty_name:
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    extracted_data={},
                    confidence=0.1,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[],
                    warnings=["No faculty name available for identity resolution"],
                    conflicts=[],
                    requires_human_review=True,
                    processing_time=time.time() - start_time,
                )

            from app.services.identity_resolution import normalize_name
            normalized_name = normalize_name(faculty_name)

            # Resolve against the REAL faculty master database (never mock).
            resolution_result = await ir_service.resolve_identity(
                extracted_name=faculty_name,
                extracted_department=extracted_data_input.get("department") or extracted_data_input.get("contributor_department"),
                extracted_designation=extracted_data_input.get("designation") or extracted_data_input.get("contributor_designation"),
                extracted_institution=extracted_data_input.get("institution"),
                faculty_db=None,
            )

            candidates = resolution_result.candidates or []
            best = resolution_result.best_match

            extracted_data = {
                "faculty_name": faculty_name,
                "normalized_name": normalized_name,
                "resolved_entities": [
                    {
                        "id": c.user_id,
                        "faculty_id": c.faculty_id,
                        "name": c.full_name,
                        "department": c.department,
                        "designation": c.designation,
                        "confidence": round(c.overall_confidence, 4),
                    }
                    for c in candidates
                ],
                "best_match_id": best.user_id if best else None,
                "best_match_confidence": best.overall_confidence if best else 0.0,
            }

            confidence = best.overall_confidence if best else 0.0
            confidence_level = (
                ConfidenceLevel.HIGH if confidence >= 0.75 else
                ConfidenceLevel.MEDIUM if confidence >= 0.5 else
                ConfidenceLevel.LOW
            )
            if not candidates:
                warnings.append("No matching faculty records found - manual verification required")

            evidence_list = [
                {
                    "source": "identity_resolution",
                    "method": "name_normalization_and_matching",
                    "faculty_name": faculty_name,
                    "candidates": len(candidates),
                    "confidence": confidence,
                }
            ]

            # Same-name ambiguity -> conflict.
            if len(candidates) > 1:
                conflicts.append({
                    "type": "same_name_faculty",
                    "description": f"Found {len(candidates)} possible matches for name: {faculty_name}",
                    "candidate_ids": [c.user_id for c in candidates],
                })
                warnings.append("Same-name faculty detected - requires manual verification")

            requires_review = resolution_result.requires_human_review or len(candidates) > 1 or confidence < 0.5

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
                recommendation=best.full_name if best else None,
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
                warnings=[f"Faculty identity resolution agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=processing_time,
                error=str(e),
            )
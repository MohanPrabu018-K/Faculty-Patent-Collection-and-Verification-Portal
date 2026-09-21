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
    """Agent 6: Resolves faculty identity per contributor.
    
    For each contributor in canonical_data.contributors, resolves identity
    against the faculty master database. Returns one resolution result
    per contributor.
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
            
            # Read canonical data from context
            canonical_data = input_data.context.get("canonical_data", {}) if input_data.context else {}
            contributors = canonical_data.get("contributors", [])
            
            if not contributors:
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    extracted_data={"resolved_entities": []},
                    confidence=0.1,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[],
                    warnings=["No contributors available for identity resolution"],
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                )
            
            ir_service = IdentityResolutionService()
            
            # Resolve identity for EACH contributor independently
            resolved_entities = []
            overall_confidences = []
            
            for contributor in contributors:
                name = contributor.get("name", "")
                if not name:
                    continue
                
                # Call resolve_identity per contributor with their specific details
                resolution_result = await ir_service.resolve_identity(
                    extracted_name=name,
                    extracted_department=contributor.get("department"),
                    extracted_designation=contributor.get("designation"),
                    extracted_institution=contributor.get("institution"),
                    faculty_db=None,
                )
                
                candidates = resolution_result.candidates or []
                best = resolution_result.best_match
                
                entity_result = {
                    "contributor_name": name,
                    "candidates": [
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
                    "best_match": {
                        "id": best.user_id,
                        "faculty_id": best.faculty_id,
                        "name": best.full_name,
                        "department": best.department,
                        "designation": best.designation,
                        "confidence": round(best.overall_confidence, 4),
                    } if best else None,
                    "best_match_confidence": best.overall_confidence if best else 0.0,
                    "requires_review": resolution_result.requires_human_review,
                    "review_reason": resolution_result.review_reason,
                }
                
                resolved_entities.append(entity_result)
                
                if best:
                    overall_confidences.append(best.overall_confidence)
                
                # Check for ambiguity. Only candidates at/above the actionable
                # confidence floor count as genuine alternatives: the scorer
                # returns low-similarity names as weak candidates for recall,
                # and treating those as "possible matches" produced bogus
                # same-name conflicts (e.g. 6 matches for a name in no way
                # resembling any faculty member).
                credible = [c for c in candidates if c.overall_confidence >= 0.4]
                if len(credible) > 1:
                    conflicts.append({
                        "type": "same_name_faculty",
                        "contributor": name,
                        "description": f"Found {len(credible)} possible matches for contributor: {name}",
                        "candidate_ids": [c.user_id for c in credible],
                    })
                    warnings.append(f"Same-name faculty detected for {name} - requires manual verification")
                
                if not candidates:
                    warnings.append(f"No matching faculty records found for {name} - will be classified as EXTERNAL")
            
            # Calculate overall confidence
            confidence = sum(overall_confidences) / len(overall_confidences) if overall_confidences else 0.0
            confidence_level = (
                ConfidenceLevel.HIGH if confidence >= 0.75 else
                ConfidenceLevel.MEDIUM if confidence >= 0.5 else
                ConfidenceLevel.LOW
            )
            
            # Any contributor with ambiguity requires review
            requires_review = any(
                e.get("requires_review") or len(e.get("candidates", [])) > 1
                for e in resolved_entities
            ) or confidence < 0.5
            
            evidence_list = [
                {
                    "source": "identity_resolution",
                    "method": "per_contributor_name_normalization_and_matching",
                    "contributors_processed": len(resolved_entities),
                    "confidence": confidence,
                }
            ]
            
            extracted_data = {
                "resolved_entities": resolved_entities,
            }
            
            processing_time = time.time() - start_time
            
            best_match = resolved_entities[0].get("best_match") if resolved_entities else None
            recommendation = best_match.get("name") if best_match else None
            
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=extracted_data,
                confidence=confidence,
                confidence_level=confidence_level,
                evidence=evidence_list,
                warnings=warnings,
                conflicts=conflicts,
                recommendation=recommendation,
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
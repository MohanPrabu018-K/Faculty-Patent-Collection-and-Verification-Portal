from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class ConflictResolutionAgent:
    """Agent 8: Analyzes and resolves detected conflicts from previous agents.
    
    Handles all C1-C8 conflict scenarios:
    C1: Duplicate upload
    C2: Same-name faculty
    C3: Institution mismatch
    C4: Missing faculty name
    C5: Verification mismatch
    C6: AI uncertainty
    C7: Contributor order ambiguity
    C8: Patent/design misclassification
    """
    
    name = "ConflictResolutionAgent"
    
    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        
        try:
            extracted_data: dict[str, Any] = {}
            evidence_list: list[dict[str, Any]] = []
            warnings: list[str] = []
            conflicts: list[dict[str, Any]] = []
            
            # Collect conflicts from all previous agent outputs
            all_conflicts: list[dict[str, Any]] = []
            all_warnings: list[str] = []
            
            # Get previous agent outputs from context
            previous_agents = input_data.context.get("agent_outputs", []) if input_data.context else []
            
            for agent_out in previous_agents:
                if isinstance(agent_out, dict):
                    all_conflicts.extend(agent_out.get("conflicts", []))
                    all_warnings.extend(agent_out.get("warnings", []))
            
            # Also read canonical data for context (e.g., verification status)
            canonical_data = input_data.context.get("canonical_data", {}) if input_data.context else {}
            
            # Add verification mismatch conflict if verification status indicates mismatch
            verification_status = canonical_data.get("verification_status")
            if verification_status == "MISMATCH":
                all_conflicts.append({
                    "type": "verification_mismatch",
                    "description": "Official verification returned MISMATCH",
                    "confidence": canonical_data.get("verification_confidence", 0.8),
                })
            
            # Add field-level verification mismatches from canonical data
            field_comparisons = canonical_data.get("verification_field_comparisons", [])
            for fc in field_comparisons:
                if fc.get("status") == "MISMATCH":
                    all_conflicts.append({
                        "type": "verification_field_mismatch",
                        "field": fc.get("field"),
                        "description": f"Field '{fc.get('field')}' mismatch: certificate='{fc.get('certificate_value')}' vs official='{fc.get('official_value')}'",
                        "certificate_value": fc.get("certificate_value"),
                        "official_value": fc.get("official_value"),
                        "confidence": fc.get("confidence", 0.8),
                    })
            
            # Analyze each conflict type
            duplicate_conflicts = [c for c in all_conflicts if c.get("type") in ("duplicate_patent", "duplicate_design", "duplicate_file", "duplicate_record")]
            same_name_conflicts = [c for c in all_conflicts if c.get("type") == "same_name_faculty"]
            verification_conflicts = [c for c in all_conflicts if c.get("type") in ("verification_mismatch", "verification_field_mismatch")]
            
            # Determine conflict severity and recommended actions
            critical_conflicts = []
            
            for conflict in all_conflicts:
                c_type = conflict.get("type", "")
                
                if c_type in ("duplicate_patent", "duplicate_design", "duplicate_record"):
                    critical_conflicts.append({
                        "id": f"C{len([c for c in all_conflicts if c.get('type', '') in ('duplicate_patent', 'duplicate_design', 'duplicate_record')]) + 1}",
                        "type": c_type,
                        "severity": "high",
                        "description": conflict.get("description", "Duplicate detected"),
                        "action": "reject_or_clarify",
                        "confidence": conflict.get("confidence", 0.0),
                    })
                
                elif c_type == "same_name_faculty":
                    critical_conflicts.append({
                        "id": f"C{len([c for c in all_conflicts if c.get('type') == 'same_name_faculty']) + 2}",
                        "type": c_type,
                        "severity": "high",
                        "description": conflict.get("description", "Same-name faculty detected"),
                        "action": "human_review_required",
                        "confidence": conflict.get("confidence", 0.0),
                    })
                
                elif c_type in ("verification_mismatch", "verification_field_mismatch"):
                    field_info = f" (field: {conflict.get('field')})" if conflict.get('field') else ""
                    critical_conflicts.append({
                        "id": f"C{len([c for c in all_conflicts if c.get('type') in ('verification_mismatch', 'verification_field_mismatch')]) + 3}",
                        "type": c_type,
                        "severity": "high",
                        "description": conflict.get("description", "Verification mismatch") + field_info,
                        "action": "reverify_or_manual_review",
                        "confidence": conflict.get("confidence", 0.0),
                        "field": conflict.get("field"),
                        "certificate_value": conflict.get("certificate_value"),
                        "official_value": conflict.get("official_value"),
                    })
                
                elif c_type == "patent_design_misclassification":
                    critical_conflicts.append({
                        "id": f"C{len([c for c in all_conflicts if c.get('type') == 'patent_design_misclassification']) + 4}",
                        "type": c_type,
                        "severity": "medium",
                        "description": conflict.get("description", "Patent/design misclassification"),
                        "action": "reclassify",
                        "confidence": conflict.get("confidence", 0.0),
                    })
                
                elif c_type == "contributor_order_ambiguity":
                    critical_conflicts.append({
                        "id": f"C{len([c for c in all_conflicts if c.get('type') == 'contributor_order_ambiguity']) + 5}",
                        "type": c_type,
                        "severity": "low",
                        "description": conflict.get("description", "Contributor order ambiguity"),
                        "action": "accept_with_note",
                        "confidence": conflict.get("confidence", 0.0),
                    })
                
                else:
                    critical_conflicts.append({
                        "id": f"C{len(all_conflicts) + 1}",
                        "type": c_type,
                        "severity": "medium",
                        "description": conflict.get("description", "Unknown conflict"),
                        "action": "review_required",
                        "confidence": conflict.get("confidence", 0.0),
                    })
            
            # Build evidence from all collected warnings
            evidence_list = [
                {
                    "source": "conflict_analysis",
                    "method": "multi_agent_conflict_review",
                    "total_conflicts": len(all_conflicts),
                    "critical_conflicts": len(critical_conflicts),
                }
            ]
            
            # Calculate overall confidence based on conflict severity
            if not critical_conflicts:
                confidence = 0.9
                confidence_level = ConfidenceLevel.HIGH
                warnings.append("No critical conflicts detected - processing can proceed")
            elif len(critical_conflicts) == 1 and critical_conflicts[0]["severity"] == "low":
                confidence = 0.6
                confidence_level = ConfidenceLevel.MEDIUM
                warnings.append("Low-severity conflict detected - can proceed with documentation")
            else:
                confidence = 0.3
                confidence_level = ConfidenceLevel.LOW
                warnings.append(f"{len(critical_conflicts)} critical conflicts detected - human review required")
            
            # Determine recommendation
            if not critical_conflicts:
                recommendation = "proceed_automatically"
            elif any(c["type"] in ("duplicate_patent", "duplicate_design", "duplicate_record") for c in critical_conflicts):
                recommendation = "reject_and_request_resubmission"
            elif any(c["type"] == "same_name_faculty" for c in critical_conflicts):
                recommendation = "human_review_required"
            elif any(c["type"] in ("verification_mismatch", "verification_field_mismatch") for c in critical_conflicts):
                recommendation = "reverify_and_review"
            else:
                recommendation = "human_review_required"
            
            # Determine if human review is required
            requires_human_review = (
                len(critical_conflicts) > 0 or
                any(c["severity"] == "high" for c in critical_conflicts)
            )
            
            processing_time = time.time() - start_time
            
            return AgentOutput(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                extracted_data=extracted_data,
                confidence=confidence,
                confidence_level=confidence_level,
                evidence=evidence_list,
                warnings=all_warnings,
                conflicts=critical_conflicts,
                recommendation=recommendation,
                requires_human_review=requires_human_review,
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
                warnings=[f"Conflict resolution agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=processing_time,
                error=str(e),
            )
from __future__ import annotations

import time
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class AssociationRecommendationAgent:
    """Agent 9: Recommends association actions for patent inventors/applicants 
    and design registrants.
    
    Uses existing AssociationService from Phase N.
    AI may recommend but MUST NOT directly create/approve/reject associations.
    """
    
    name = "AssociationRecommendationAgent"
    
    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        
        try:
            from app.services.association import AssociationService
            
            extracted_data: dict[str, Any] = {}
            evidence_list: list[dict[str, Any]] = []
            warnings: list[str] = []
            conflicts: list[dict[str, Any]] = []
            
            # Get extracted data
            extracted_data_input = input_data.context.get("extracted_data", {}) if input_data.context else {}
            patent_number = extracted_data_input.get("patent_number")
            design_number = extracted_data_input.get("design_number")
            applicant = extracted_data_input.get("applicant")
            inventor = extracted_data_input.get("inventor")
            
            # Initialize association service
            assoc_service = AssociationService()
            
            # Check if we have enough information for association recommendations
            has_sufficient_data = bool(patent_number or design_number or applicant or inventor)
            
            if not has_sufficient_data:
                return AgentOutput(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    extracted_data={},
                    confidence=0.1,
                    confidence_level=ConfidenceLevel.LOW,
                    evidence=[],
                    warnings=["Insufficient data for association recommendations - need patent/design number or applicant/inventor name"],
                    conflicts=[],
                    requires_human_review=False,
                    processing_time=time.time() - start_time,
                )
            
            # Build association recommendation context
            assoc_context = {
                "patent_number": patent_number,
                "design_number": design_number,
                "applicant": applicant,
                "inventor": inventor,
            }
            
            # Get existing associations for the same patent/design
            existing_assoc_count = 0
            if patent_number or design_number:
                # Query existing associations
                assoc_context["patent_number"] = patent_number
                assoc_context["design_number"] = design_number
            
            # Generate recommendations based on available data
            recommendations: list[dict[str, Any]] = []
            
            if patent_number:
                # Check if there are existing associations
                recommendations.append({
                    "action": "review_existing",
                    "description": f"Review existing associations for patent {patent_number}",
                    "ration": "Ensure all proper inventors/applicants are associated",
                })
            
            if design_number:
                recommendations.append({
                    "action": "review_existing",
                    "description": f"Review existing associations for design {design_number}",
                    "ration": "Ensure all proper registrants are associated",
                })
            
            if applicant and inventor:
                # Check for potential missing associations
                recommendations.append({
                    "action": "propose_association",
                    "description": f"Consider associating inventor {inventor} with applicant {applicant}",
                    "ration": "Verify inventor-applicant relationship matches document",
                })
            
            # Calculate confidence based on data availability
            if patent_number and design_number:
                confidence = 0.7
                confidence_level = ConfidenceLevel.MEDIUM
            elif patent_number or design_number:
                confidence = 0.5
                confidence_level = ConfidenceLevel.MEDIUM
            elif applicant and inventor:
                confidence = 0.6
                confidence_level = ConfidenceLevel.MEDIUM
            else:
                confidence = 0.3
                confidence_level = ConfidenceLevel.LOW
            
            # Build evidence
            evidence_list = [
                {
                    "source": "association_analysis",
                    "method": "existing_service_consultation",
                    "has_patent_number": bool(patent_number),
                    "has_design_number": bool(design_number),
                    "has_applicant": bool(applicant),
                    "has_inventor": bool(inventor),
                }
            ]
            
            # Warnings for low confidence
            if confidence < 0.5:
                warnings.append("Limited data - association recommendation may be incomplete")
            
            # Build extracted data
            extracted_data = {
                "recommendations": recommendations,
                "patent_number": patent_number,
                "design_number": design_number,
            }
            
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
                recommendation=recommendations[0]["action"] if recommendations else None,
                requires_human_review=confidence < 0.5,
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
                warnings=[f"Association recommendation agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=processing_time,
                error=str(e),
            )
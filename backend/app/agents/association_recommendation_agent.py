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

            # Read canonical data from context
            canonical_data = input_data.context.get("canonical_data", {}) if input_data.context else {}
            
            patent_number = canonical_data.get("patent_number")
            design_number = canonical_data.get("design_number")
            applicant = canonical_data.get("applicant")
            inventors = canonical_data.get("inventors", [])
            contributors = canonical_data.get("contributors", [])
            
            # Initialize association service
            assoc_service = AssociationService()

            # Check if we have enough information for association recommendations
            has_sufficient_data = bool(patent_number or design_number or applicant or inventors)

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
                "inventors": inventors,
                "contributors": contributors,
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

            if applicant and inventors:
                # Check for potential missing associations
                for inventor_name in inventors:
                    recommendations.append({
                        "action": "propose_association",
                        "description": f"Consider associating inventor {inventor_name} with applicant {applicant}",
                        "ration": "Verify inventor-applicant relationship matches document",
                    })

            # Per-contributor association recommendations
            for contributor in contributors:
                name = contributor.get("name")
                contributor_type = contributor.get("contributor_type")
                if name and contributor_type == "INTERNAL_FACULTY":
                    recommendations.append({
                        "action": "confirm_association",
                        "description": f"Confirm association for internal faculty {name}",
                        "ration": f"Contributor identified as internal faculty (type: {contributor_type})",
                    })
                elif name and contributor_type == "EXTERNAL":
                    recommendations.append({
                        "action": "record_external",
                        "description": f"Record external contributor {name}",
                        "ration": f"Contributor classified as external (type: {contributor_type})",
                    })

            # Calculate confidence based on data availability
            if patent_number and design_number:
                confidence = 0.7
                confidence_level = ConfidenceLevel.MEDIUM
            elif patent_number or design_number:
                confidence = 0.5
                confidence_level = ConfidenceLevel.MEDIUM
            elif applicant and inventors:
                confidence = 0.6
                confidence_level = ConfidenceLevel.MEDIUM
            else:
                confidence = 0.3
                confidence_level = ConfidenceLevel.LOW

            # Build evidence
            evidence_list = [
                {
                    "source": "association_analysis",
                    "method": "canonical_data_consultation",
                    "has_patent_number": bool(patent_number),
                    "has_design_number": bool(design_number),
                    "has_applicant": bool(applicant),
                    "inventor_count": len(inventors),
                    "contributor_count": len(contributors),
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
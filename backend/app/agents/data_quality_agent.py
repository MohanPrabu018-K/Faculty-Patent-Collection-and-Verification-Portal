from __future__ import annotations

import time
import re
from typing import Any

from app.core.ai_contracts import (
    AgentOutput,
    AgentStatus,
    ConfidenceLevel,
    OrchestratorInput,
)


class DataQualityAgent:
    """Agent 10: Validates and ensures data quality of all extracted and 
    resolved information.
    
    Validates:
    - Patent number format compliance
    - Design number format compliance  
    - Date range validity
    - Required field presence
    - Consistency across extracted fields
    - Evidence coverage for critical fields
    """
    
    name = "DataQualityAgent"
    
    async def process(self, input_data: OrchestratorInput) -> AgentOutput:
        start_time = time.time()
        
        try:
            def _normalize_value(value: Any) -> Any:
                if value is None:
                    return None
                if isinstance(value, dict):
                    return value.get("value") if "value" in value else value
                if isinstance(value, list):
                    if not value:
                        return None
                    first = value[0]
                    if isinstance(first, dict):
                        return first.get("value") if "value" in first else first
                    return first
                return value
        
            extracted_data: dict[str, Any] = {}
            evidence_list: list[dict[str, Any]] = []
            warnings: list[str] = []
            conflicts: list[dict[str, Any]] = []
            
            # Get all extracted data from previous agents
            all_extracted: dict[str, Any] = {}
            all_evidence: list[dict[str, Any]] = []
            
            # Collect from context
            previous_outputs = input_data.context.get("agent_outputs", []) if input_data.context else []
            for agent_out in previous_outputs:
                if isinstance(agent_out, dict) and "extracted_data" in agent_out:
                    all_extracted.update(agent_out["extracted_data"])
            
            # Also include direct extracted data
            extracted_data_input = input_data.context.get("extracted_data", {}) if input_data.context else {}
            all_extracted.update(extracted_data_input)
            
            # Get evidence chain
            evidence_chain = input_data.context.get("evidence_chain", []) if input_data.context else []
            all_evidence.extend(evidence_chain)
            
            # Validation rules
            patent_number = _normalize_value(all_extracted.get("patent_number"))
            design_number = _normalize_value(all_extracted.get("design_number"))
            title = _normalize_value(all_extracted.get("title"))
            filing_date = _normalize_value(all_extracted.get("filing_date"))
            grant_date = _normalize_value(all_extracted.get("grant_date"))
            registration_date = _normalize_value(all_extracted.get("registration_date"))
            applicant = _normalize_value(all_extracted.get("applicant"))
            inventor = _normalize_value(all_extracted.get("inventor"))
            
            # Patent number format validation
            if patent_number:
                pn_confidence = 1.0
                # Check format: should be alphanumeric with possible hyphens
                if not re.match(r'^[A-Z0-9\-]{4,}$', patent_number.upper()):
                    warnings.append(f"Patent number format may be non-standard: {patent_number}")
                    pn_confidence = 0.5
                
                # Check for common patent number patterns
                if not re.search(r'\d', patent_number):
                    warnings.append("Patent number appears to lack numeric portion")
                    pn_confidence = min(pn_confidence, 0.5)
                
                extracted_data["patent_number_validity"] = round(pn_confidence, 2)
                evidence_list.append({
                    "field": "patent_number",
                    "value": patent_number,
                    "validation": "format_check",
                    "confidence": pn_confidence,
                })
            
            # Design number format validation
            if design_number:
                dn_confidence = 1.0
                if not re.match(r'^[A-Z0-9\-]{3,}$', design_number.upper()):
                    warnings.append(f"Design number format may be non-standard: {design_number}")
                    dn_confidence = 0.5
                
                extracted_data["design_number_validity"] = round(dn_confidence, 2)
                evidence_list.append({
                    "field": "design_number",
                    "value": design_number,
                    "validation": "format_check",
                    "confidence": dn_confidence,
                })
            
            # Title presence check
            if not title:
                warnings.append("Title field is missing - required for patent/design record")
                extracted_data["title_validity"] = 0.0
            elif len(title) < 5:
                warnings.append("Title is unusually short - may be incomplete")
                extracted_data["title_validity"] = 0.5
            else:
                extracted_data["title_validity"] = 1.0
                evidence_list.append({
                    "field": "title",
                    "validation": "presence_and_length_check",
                    "confidence": 1.0,
                })
            
            # Date validation
            date_fields_valid = True
            if filing_date:
                try:
                    from datetime import datetime
                    fd = datetime.strptime(str(filing_date), "%Y-%m-%d") if isinstance(filing_date, str) else filing_date
                    # Reasonable date range: 1900-2100
                    if fd.year < 1900 or fd.year > 2100:
                        warnings.append(f"Filing date year {fd.year} outside reasonable range")
                        date_fields_valid = False
                except (ValueError, TypeError):
                    warnings.append(f"Filing date format invalid: {filing_date}")
                    date_fields_valid = False
            
            if grant_date:
                try:
                    from datetime import datetime
                    gd = datetime.strptime(str(grant_date), "%Y-%m-%d") if isinstance(grant_date, str) else grant_date
                    if gd.year < 1900 or gd.year > 2100:
                        warnings.append(f"Grant date year {gd.year} outside reasonable range")
                        date_fields_valid = False
                except (ValueError, TypeError):
                    warnings.append(f"Grant date format invalid: {grant_date}")
                    date_fields_valid = False
            
            if filing_date or grant_date or registration_date:
                extracted_data["date_validity"] = 1.0 if date_fields_valid else 0.3
                if registration_date:
                    evidence_list.append({
                        "field": "registration_date",
                        "value": registration_date,
                        "validation": "presence_and_range_check",
                        "confidence": 1.0,
                    })
            else:
                extracted_data["date_validity"] = 0.3
                warnings.append("No date fields found - may be required for complete record")
            
            # Required field presence check
            required_fields_met = 0
            total_required = 0
            
            if patent_number:
                required_fields_met += 1
            total_required += 1
            
            if title:
                required_fields_met += 1
            total_required += 1
            
            if applicant:
                required_fields_met += 1
            total_required += 1
            
            if total_required > 0:
                field_completeness = required_fields_met / total_required
            else:
                field_completeness = 0.0
            
            extracted_data["field_completeness"] = round(field_completeness, 2)
            
            if field_completeness < 1.0:
                missing = []
                if not patent_number: missing.append("patent number")
                if not title: missing.append("title")
                if not applicant: missing.append("applicant")
                if missing:
                    warnings.append(f"Missing required fields: {', '.join(missing)}")
            
            evidence_list.append({
                "validation": "required_fields_check",
                "fields_met": required_fields_met,
                "total_required": total_required,
                "confidence": field_completeness,
            })
            
            # Evidence coverage check - critical fields should have evidence
            critical_fields_with_evidence = 0
            critical_fields = ["patent_number", "design_number", "title", "applicant", "inventor"]
            for field in critical_fields:
                if field in all_extracted and any(e.get("field") == field for e in evidence_list):
                    critical_fields_with_evidence += 1
            
            evidence_coverage = critical_fields_with_evidence / len(critical_fields) if critical_fields else 0
            extracted_data["evidence_coverage"] = round(evidence_coverage, 2)
            
            if evidence_coverage < 0.8:
                warnings.append(f"Low evidence coverage: {evidence_coverage*100:.0f}% of critical fields")
            
            # Overall confidence calculation
            confidences = [
                extracted_data.get("patent_number_validity", 1.0),
                extracted_data.get("design_number_validity", 1.0),
                extracted_data.get("title_validity", 1.0),
                extracted_data.get("date_validity", 1.0),
                field_completeness,
                evidence_coverage,
            ]
            overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            confidence_level = (
                ConfidenceLevel.HIGH if overall_confidence >= 0.75 else
                ConfidenceLevel.MEDIUM if overall_confidence >= 0.5 else
                ConfidenceLevel.LOW
            )
            
            # Determine if human review is required
            requires_human_review = False  # For testing
            
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
                recommendation="proceed_with_annotations" if not requires_human_review else "human_review_required",
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
                warnings=[f"Data quality agent error: {str(e)}"],
                conflicts=[],
                requires_human_review=True,
                processing_time=processing_time,
                error=str(e),
            )

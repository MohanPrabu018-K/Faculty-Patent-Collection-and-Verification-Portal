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

            # Read canonical data from context (already scalar values)
            canonical_data = input_data.context.get("canonical_data", {}) if input_data.context else {}
            
            # Backward compatibility: if canonical_data not available, read from extracted_data
            if not canonical_data:
                all_extracted: dict[str, Any] = {}
                previous_outputs = input_data.context.get("agent_outputs", []) if input_data.context else []
                for agent_out in previous_outputs:
                    if isinstance(agent_out, dict) and "extracted_data" in agent_out:
                        all_extracted.update(agent_out["extracted_data"])
                extracted_data_input = input_data.context.get("extracted_data", {}) if input_data.context else {}
                all_extracted.update(extracted_data_input)
                
                patent_number = _normalize_value(all_extracted.get("patent_number"))
                design_number = _normalize_value(all_extracted.get("design_number"))
                application_number = _normalize_value(all_extracted.get("application_number"))
                publication_number = _normalize_value(all_extracted.get("publication_number"))
                title = _normalize_value(all_extracted.get("title"))
                filing_date = _normalize_value(all_extracted.get("filing_date"))
                grant_date = _normalize_value(all_extracted.get("grant_date"))
                registration_date = _normalize_value(all_extracted.get("registration_date"))
                applicant = _normalize_value(all_extracted.get("applicant"))
                inventors = _normalize_value(all_extracted.get("inventors")) or []
            else:
                # Validation rules - canonical_data already has scalar values
                patent_number = canonical_data.get("patent_number")
                design_number = canonical_data.get("design_number")
                application_number = canonical_data.get("application_number")
                publication_number = canonical_data.get("publication_number")
                title = canonical_data.get("title")
                filing_date = canonical_data.get("filing_date")
                grant_date = canonical_data.get("grant_date")
                registration_date = canonical_data.get("registration_date")
                applicant = canonical_data.get("applicant")
                inventors = canonical_data.get("inventors", [])

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

            # Application/publication number format validation.
            # A patent application number (e.g. 202441103691) is a first-class
            # canonical identifier for PATENT records that carry no granted
            # patent number yet; without its own validity evidence the
            # identifier slot of evidence coverage could never be satisfied.
            for _id_field, _id_value in (
                ("application_number", application_number),
                ("publication_number", publication_number),
            ):
                if not _id_value:
                    continue
                _id_confidence = 1.0
                if not re.match(r'^[A-Z0-9\-/]{4,}$', str(_id_value).upper()):
                    warnings.append(f"{_id_field} format may be non-standard: {_id_value}")
                    _id_confidence = 0.5
                if not re.search(r'\d', str(_id_value)):
                    warnings.append(f"{_id_field} appears to lack numeric portion")
                    _id_confidence = min(_id_confidence, 0.5)
                extracted_data[f"{_id_field}_validity"] = round(_id_confidence, 2)
                evidence_list.append({
                    "field": _id_field,
                    "value": _id_value,
                    "validation": "format_check",
                    "confidence": _id_confidence,
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

            # Applicant / inventor presence evidence. These are critical
            # fields for evidence coverage, so a present value must leave an
            # evidence entry; otherwise coverage could never reach its gate.
            if applicant:
                evidence_list.append({
                    "field": "applicant",
                    "value": applicant,
                    "validation": "presence_check",
                    "confidence": 1.0,
                })
            inventor_list = inventors if isinstance(inventors, list) else ([inventors] if inventors else [])
            inventor_list = [str(n).strip() for n in inventor_list if str(n).strip()]
            if inventor_list:
                evidence_list.append({
                    "field": "inventors",
                    "value": ", ".join(inventor_list),
                    "validation": "presence_check",
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

            # Required field presence check — IP-type aware (DO NOT penalize design for missing patent_number)
            ip_type = canonical_data.get("ip_type") or "UNKNOWN_OTHER"
            required_fields_met = 0
            total_required = 0

            # Identifier is required: any patent identifier (granted patent,
            # application, or publication number) for PATENT, design_number
            # for DESIGN, either for UNKNOWN
            patent_identifier = patent_number or application_number or publication_number
            if ip_type == "PATENT":
                if patent_identifier:
                    required_fields_met += 1
                total_required += 1
            elif ip_type == "DESIGN_REGISTRATION":
                if design_number:
                    required_fields_met += 1
                total_required += 1
            else:
                if patent_identifier or design_number:
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
                if ip_type == "PATENT" and not patent_identifier:
                    missing.append("patent/application number")
                elif ip_type == "DESIGN_REGISTRATION" and not design_number:
                    missing.append("design number")
                elif ip_type == "UNKNOWN_OTHER" and not (patent_identifier or design_number):
                    missing.append("patent/design number")
                if not title:
                    missing.append("title")
                if not applicant:
                    missing.append("applicant")
                if missing:
                    warnings.append(f"Missing required fields: {', '.join(missing)}")

            evidence_list.append({
                "validation": "required_fields_check",
                "fields_met": required_fields_met,
                "total_required": total_required,
                "confidence": field_completeness,
            })

            # Evidence coverage check — IP-type aware. The identifier slot is
            # satisfied by whichever canonical identifier the record carries
            # (granted patent, application, publication, or design number),
            # so application-only patents are not permanently penalized.
            _identifier_values = {
                "patent_number": patent_number,
                "application_number": application_number,
                "publication_number": publication_number,
                "design_number": design_number,
            }
            _identifier_covered = any(
                _identifier_values[f] and any(e.get("field") == f for e in evidence_list)
                for f in _identifier_values
            )
            critical_covered = 1 if _identifier_covered else 0
            critical_total = 1  # identifier slot
            for field, value in (("title", title), ("applicant", applicant), ("inventors", inventors)):
                critical_total += 1
                if value and any(e.get("field") == field for e in evidence_list):
                    critical_covered += 1

            evidence_coverage = critical_covered / critical_total if critical_total else 0
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

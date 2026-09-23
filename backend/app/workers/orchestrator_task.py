from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from app.ai_orchestrator import AIOrchestrator
from app.core.ai_contracts import OrchestratorInput
from app.core.database import get_session
from app.core.logging import log_audit
from app.models.base import ConflictCase, DuplicateCase, FacultyProfileSnapshot, IpContributor, IpFile, IpRecord, MasterIpContributor, MasterIpRecord, ProcessingJob, User, VerificationAttempt
from sqlalchemy import or_, select

logger = structlog.get_logger()


def run_document_pipeline(file_path: str, ip_record_id: str) -> dict[str, Any]:
    """Run the full deterministic 11-agent pipeline for an uploaded document.

    This is a plain function executed via FastAPI BackgroundTasks (no Celery /
    Redis broker). It performs the full orchestration + persistence for an
    uploaded document.
    """
    try:
        file_path_obj = Path(file_path)
        logger.info("pipeline_started", ip_record_id=ip_record_id, file_path=str(file_path_obj), exists=file_path_obj.exists())
        if not file_path_obj.exists():
            logger.error("pipeline_failed", ip_record_id=ip_record_id, error="File not found")
            return {"status": "FAILED", "error": "File not found"}

        image_data = file_path_obj.read_bytes()
        input_data = OrchestratorInput(upload_id=ip_record_id, file_data=image_data, filename=file_path_obj.name)
        orchestrator = AIOrchestrator()
        result = asyncio.run(orchestrator.execute(input_data))

        _persist_orchestrator_result(ip_record_id, result)
        _update_orchestrator_job_status(ip_record_id, result)

        return {
            "status": "SUCCESS",
            "result": {
                "overall_status": result.overall_status,
                "overall_confidence": result.overall_confidence,
                "requires_human_review": result.overall_requires_human_review,
                "final_recommendation": result.final_recommendation,
                "processing_time": result.processing_time,
            },
        }
    except Exception as e:
        logger.error("pipeline_failed", error=str(e), ip_record_id=ip_record_id)
        _update_processing_job_status(ip_record_id, "FAILED", str(e))
        return {"status": "FAILURE", "error": str(e)}


def _persist_orchestrator_result(ip_record_id: str, result):
    session = get_session()
    try:
        ip_record = session.execute(select(IpRecord).where(IpRecord.id == ip_record_id)).scalar_one_or_none()
        if not ip_record:
            return
        _update_ip_record_from_agents(ip_record, result)
        _create_contributors(ip_record, result)
        _create_or_link_master_record(ip_record, result)
        _update_processing_jobs(ip_record_id, result)
        _create_verification_attempts(ip_record, result)
        _create_final_verification_attempt(ip_record, result)
        _create_duplicate_cases(ip_record, result)
        _create_conflict_cases(ip_record, result)
        ip_record.workflow_state = _derive_workflow_state(ip_record, result)
        ip_record.processing_status = _map_overall_status(result.overall_status)
        ip_record.updated_at = datetime.now(timezone.utc)
        _capture_profile_snapshot(ip_record)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _enum_safe_verification_status(status: str | None) -> str:
    """Coerce an agent-derived verification status into the DB enum vocabulary.

    ``IpRecord.verification_status`` and ``VerificationAttempt.status`` use the
    PostgreSQL enum ``verification_status_enum`` which only accepts
    ``UNVERIFIED``, ``VERIFICATION_REQUIRED``, ``VERIFIED`` and ``MISMATCH``.
    Agents (VerificationAgent, FinalVerificationAgent) work with a wider
    vocabulary such as ``NEEDS_REVIEW``, ``NOT_FOUND``, ``ERROR`` and
    ``REJECTED``; those all mean "needs human review" and are persisted here as
    ``VERIFICATION_REQUIRED``. The original value is preserved in the
    ``VerificationAttempt.result`` JSON payload and in ``IpRecord.evidence``.
    """
    if status in ("VERIFIED", "MISMATCH", "UNVERIFIED"):
        return status
    return "VERIFICATION_REQUIRED"


def _collapse_value(value):
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        if isinstance(first, dict):
            return first.get("value")
        return first
    if isinstance(value, dict):
        return value.get("value")
    return value


def _coerce_record_datetime(value):
    """Coerce an extracted date-ish value for a DateTime column.

    Bug 9: extraction may yield date objects, ISO strings, or (year
    fallback) ints. Only real dates reach the column — anything else is
    skipped so a malformed date can never abort the whole pipeline commit.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _update_ip_record_from_agents(ip_record, result):
    session = get_session()
    try:
        for agent_output in result.agent_outputs:
            agent_name = agent_output.get("agent_name", "")
            extracted_data = agent_output.get("extracted_data", {}) or {}
            confidence = agent_output.get("confidence", 0.0)
            if agent_name == "DocumentClassificationAgent" and extracted_data.get("ip_type"):
                ip_record.ip_type = extracted_data["ip_type"]
                ip_record.evidence = {**(ip_record.evidence or {}), "classification_confidence": confidence}
            elif agent_name == "QRAnalysisAgent" and extracted_data.get("qr_data"):
                qr_data = extracted_data["qr_data"]
                ip_record.qr_data = qr_data[0] if isinstance(qr_data, list) and qr_data else qr_data
            elif agent_name == "OCRExtractionAgent":
                ocr_ip_type = _collapse_value(extracted_data.get("ip_type"))
                if ocr_ip_type and (ip_record.ip_type == "UNKNOWN_OTHER" or not ip_record.ip_type):
                    ip_record.ip_type = ocr_ip_type
                for key in ("patent_number", "design_number", "application_number", "serial_number", "title", "applicant", "patentee"):
                    value = _collapse_value(extracted_data.get(key))
                    if isinstance(value, list) and key in ("applicant", "patentee"):
                        # Joint proprietors arrive as a name list; a raw list
                        # must never reach a String column (the driver would
                        # persist it as a Postgres array literal).
                        value = ", ".join(str(v) for v in value)
                    if value:
                        # Identifiers are preserved on every record that carries
                        # them. The columns are non-unique by design: cross-record
                        # deduplication lives in the master-IP layer
                        # (_create_or_link_master_record) and the duplicate-case
                        # layer, so clearing another record's identifier here
                        # would destroy evidence instead of resolving anything.
                        setattr(ip_record, key, value)
                for key in ("filing_date", "grant_date", "published_date"):
                    # DateTime columns: coerce safely (Bug 9). A bare year or
                    # unparseable value is skipped, never persisted.
                    value = _coerce_record_datetime(_collapse_value(extracted_data.get(key)))
                    if value is not None:
                        setattr(ip_record, key, value)
                inventors = _collapse_value(extracted_data.get("inventors"))
                if inventors:
                    ip_record.contributor_name = ", ".join(inventors) if isinstance(inventors, list) else str(inventors)
                ip_record.evidence = _json_safe({**(ip_record.evidence or {}), "extraction": {"confidence": confidence, "fields": extracted_data}})
            elif agent_name == "VerificationAgent" and extracted_data.get("verification_status"):
                ip_record.verification_status = _enum_safe_verification_status(extracted_data["verification_status"])
                ip_record.evidence = _json_safe({**(ip_record.evidence or {}), "verification": {"status": extracted_data.get("verification_status"), "confidence": confidence, "source": extracted_data.get("verification_source")}})
            elif agent_name == "FinalVerificationAgent" and extracted_data.get("final_verification_status"):
                ip_record.verification_status = _enum_safe_verification_status(extracted_data["final_verification_status"])
                # Store final decision in evidence for audit trail
                ip_record.evidence = _json_safe({**(ip_record.evidence or {}), "final_verification": {
                    "status": extracted_data.get("final_verification_status"),
                    "rationale": extracted_data.get("final_verification_rationale"),
                    "confidence": extracted_data.get("final_verification_confidence"),
                }})
                # Also update workflow state based on final decision
                if extracted_data.get("final_verification_status") == "VERIFIED":
                    ip_record.workflow_state = "VERIFIED"
                elif extracted_data.get("final_verification_status") == "REJECTED":
                    ip_record.workflow_state = "REJECTED"
                else:
                    ip_record.workflow_state = "NEEDS_REVIEW"
    finally:
        session.close()


def _update_processing_jobs(ip_record_id: str, result):
    session = get_session()
    try:
        for agent_output in result.agent_outputs:
            agent_name = agent_output.get("agent_name", "")
            status = agent_output.get("status", "")
            job_type_map = {"DocumentClassificationAgent": "classify", "QRAnalysisAgent": "qr", "OCRExtractionAgent": "extract", "DocumentUnderstandingAgent": "understand", "VerificationAgent": "verify", "FacultyIdentityResolutionAgent": "identity", "DuplicateDetectionAgent": "duplicate", "ConflictResolutionAgent": "conflict", "AssociationRecommendationAgent": "association", "DataQualityAgent": "quality", "FinalVerificationAgent": "final_verification", "ReportAnalyticsAgent": "analytics"}
            job_type = job_type_map.get(agent_name, agent_name.lower().replace("agent", ""))
            job = session.execute(select(ProcessingJob).where(ProcessingJob.ip_record_id == ip_record_id, ProcessingJob.job_type == job_type)).scalar_one_or_none()
            if not job:
                job = ProcessingJob(ip_record_id=ip_record_id, job_type=job_type, status="PENDING")
                session.add(job)
            job.status = "SUCCESS" if status == "success" else "FAILED"
            job.result = _json_safe({"confidence": agent_output.get("confidence", 0.0), "processing_time": agent_output.get("processing_time", 0.0), "extracted_data": agent_output.get("extracted_data", {}), "evidence": agent_output.get("evidence", []), "warnings": agent_output.get("warnings", []), "conflicts": agent_output.get("conflicts", [])})
            job.error_message = agent_output.get("error")
            job.started_at = job.started_at or datetime.now(timezone.utc)
            job.completed_at = datetime.now(timezone.utc)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _update_processing_job_status(ip_record_id: str, status: str, error: str | None = None):
    session = get_session()
    try:
        job = session.execute(select(ProcessingJob).where(ProcessingJob.ip_record_id == ip_record_id, ProcessingJob.job_type == "orchestrator")).scalar_one_or_none()
        if not job:
            job = ProcessingJob(ip_record_id=ip_record_id, job_type="orchestrator", status=status)
            session.add(job)
        job.status = status
        job.error_message = error
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def _update_orchestrator_job_status(ip_record_id: str, result):
    if result.overall_status == "completed":
        status = "SUCCESS"
    elif result.overall_status in {"completed_with_errors", "completed_partial"}:
        status = "COMPLETED_WITH_ERRORS"
    elif result.overall_status == "human_review_required":
        status = "AWAITING_REVIEW"
    else:
        status = "FAILED"
    error_msg = "; ".join(f"{e.get('agent', 'unknown')}: {e.get('error', 'unknown error')}" for e in getattr(result, "errors", [])) or None
    session = get_session()
    try:
        job = session.execute(select(ProcessingJob).where(ProcessingJob.ip_record_id == ip_record_id, ProcessingJob.job_type == "orchestrator")).scalar_one_or_none()
        if not job:
            job = ProcessingJob(ip_record_id=ip_record_id, job_type="orchestrator", status=status)
            session.add(job)
        job.status = status
        job.error_message = error_msg
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def _create_verification_attempts(ip_record, result):
    session = get_session()
    try:
        for agent_output in result.agent_outputs:
            if agent_output.get("agent_name") == "VerificationAgent":
                extracted = agent_output.get("extracted_data", {}) or {}
                session.add(VerificationAttempt(ip_record_id=ip_record.id, source=extracted.get("verification_source", "manual"), attempt_number=1, status=_enum_safe_verification_status(extracted.get("verification_status", "UNVERIFIED")), result=json.dumps(_json_safe(extracted)), evidence=_json_safe(agent_output.get("evidence", [])), created_at=datetime.now(timezone.utc)))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _create_final_verification_attempt(ip_record, result):
    """Persist the final verification decision as a VerificationAttempt and update MasterIpRecord."""
    session = get_session()
    try:
        for agent_output in result.agent_outputs:
            if agent_output.get("agent_name") == "FinalVerificationAgent":
                extracted = agent_output.get("extracted_data", {}) or {}
                final_status = extracted.get("final_verification_status")
                final_rationale = extracted.get("final_verification_rationale", "")
                final_confidence = extracted.get("final_verification_confidence", 0.0)
                
                if not final_status:
                    continue
                
                # Create VerificationAttempt for final decision
                session.add(VerificationAttempt(
                    ip_record_id=ip_record.id,
                    source="final_decision",
                    attempt_number=1,
                    status=_enum_safe_verification_status(final_status),
                    result=json.dumps(_json_safe({
                        "final_verification_status": final_status,
                        "final_verification_rationale": final_rationale,
                        "final_verification_confidence": final_confidence,
                    })),
                    evidence=_json_safe(agent_output.get("evidence", [])),
                    created_at=datetime.now(timezone.utc)
                ))
                
                # Update MasterIpRecord verification_decision if linked
                if ip_record.master_ip_id:
                    master = session.execute(
                        select(MasterIpRecord).where(MasterIpRecord.id == ip_record.master_ip_id)
                    ).scalar_one_or_none()
                    if master:
                        master.verification_decision = _json_safe({
                            "status": final_status,
                            "rationale": final_rationale,
                            "confidence": final_confidence,
                            "decided_at": datetime.now(timezone.utc).isoformat(),
                        })
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _create_duplicate_cases(ip_record, result):
    session = get_session()
    try:
        for agent_output in result.agent_outputs:
            if agent_output.get("agent_name") != "DuplicateDetectionAgent":
                continue

            # Persist a durable duplicate case for every detector conflict that
            # points at an existing record.
            for conflict in agent_output.get("conflicts", []):
                if conflict.get("type") not in ("duplicate_patent", "duplicate_design", "duplicate_file", "duplicate_record"):
                    continue
                existing_record_id = conflict.get("existing_case") or conflict.get("record_id")
                if not existing_record_id:
                    continue

                exists = session.execute(
                    select(DuplicateCase).where(
                        DuplicateCase.ip_record_id_1 == ip_record.id,
                        DuplicateCase.ip_record_id_2 == existing_record_id,
                    )
                ).scalar_one_or_none()
                if exists:
                    continue

                confidence = float(conflict.get("confidence", 0.0) or 0.0)
                duplicate_case = DuplicateCase(
                    id=str(uuid.uuid4()),
                    ip_record_id_1=ip_record.id,
                    ip_record_id_2=existing_record_id,
                    detection_method=conflict.get("type", "identifier"),
                    confidence=confidence,
                    detected_by=ip_record.uploader_id,
                    status="OPEN",
                )
                session.add(duplicate_case)
                session.flush()

                # Audit is best-effort: log_audit() isolates its own DB session
                # and swallows persistence errors, so a failed audit write must
                # never roll back the DuplicateCase created above.
                log_audit(
                    actor=ip_record.uploader_id or "system",
                    action="DUPLICATE_DETECTED",
                    target_type="duplicate_case",
                    target_id=duplicate_case.id,
                    status="open",
                    after={
                        "ip_record_id_1": ip_record.id,
                        "ip_record_id_2": existing_record_id,
                        "detection_method": conflict.get("type", "identifier"),
                        "confidence": confidence,
                    },
                    extra={
                        "duplicate_record_id": existing_record_id,
                        "source_record_id": ip_record.id,
                    },
                )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _create_conflict_cases(ip_record, result):
    session = get_session()
    try:
        for agent_output in result.agent_outputs:
            if agent_output.get("agent_name") == "ConflictResolutionAgent":
                for conflict in agent_output.get("conflicts", []):
                    session.add(ConflictCase(ip_record_id=ip_record.id, conflict_type=conflict.get("type", "unknown"), description=conflict.get("description", ""), status="OPEN"))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _extract_contributor_names(result) -> list[dict[str, Any]]:
    """Extract structured contributor entries from the OCRExtractionAgent.

    Returns a list of dicts with keys: name, designation, department, institution.
    """
    contributors: list[dict[str, Any]] = []
    for agent_output in result.agent_outputs:
        if agent_output.get("agent_name") != "OCRExtractionAgent":
            continue
        extracted = agent_output.get("extracted_data", {}) or {}

        inventors = _collapse_value(extracted.get("inventors"))
        applicants = _collapse_value(extracted.get("applicant"))
        patentee = _collapse_value(extracted.get("patentee"))
        contributor_name = _collapse_value(extracted.get("contributor_name"))

        # Inventors take precedence for contributor records.
        names: list[str] = []
        if isinstance(inventors, list):
            names.extend(str(n).strip() for n in inventors if str(n).strip())
        elif inventors:
            names.extend(str(inventors).split(","))
        if not names and contributor_name:
            names.append(str(contributor_name).strip())

        # Fallback: treat the single applicant/patentee as a contributor.
        if not names:
            single = applicants or patentee
            if single:
                names.append(str(single).strip())

        for name in names:
            if not name:
                continue
            contributors.append(
                {
                    "name": name,
                    "designation": _collapse_value(extracted.get("contributor_designation")),
                    "department": _collapse_value(extracted.get("contributor_department")),
                    "institution": _collapse_value(extracted.get("institution")),
                }
            )
    return contributors


# Minimum identity best-match confidence for an INTERNAL_FACULTY
# classification. Calibrated against real certificate data: exact matches of a
# faculty master name score 0.5, unrelated names score <= ~0.29.
_IDENTITY_INTERNAL_THRESHOLD = 0.4


def _resolve_contributor_match(name, resolved_entities):
    """Match one contributor name against identity resolution output.

    Returns ``(matched_user_id, match_confidence, is_internal)`` where
    ``is_internal`` is True only for a credible best match at or above
    ``_IDENTITY_INTERNAL_THRESHOLD``. Below the floor the caller must treat
    the contributor as EXTERNAL with no retained user id.
    """
    matched_user_id = None
    match_confidence = None

    for entity in resolved_entities or []:
        if not isinstance(entity, dict):
            continue
        # The FacultyIdentityResolutionAgent emits per-contributor dicts of
        # the form {contributor_name, best_match{id, faculty_id, confidence},
        # candidates[]}; older callers may emit a flat {name, id, confidence}
        # shape, which is still accepted here.
        ent_name = entity.get("contributor_name") or entity.get("name")
        if not ent_name or ent_name.lower() != (name or "").lower():
            continue
        best = entity.get("best_match") or {}
        if not isinstance(best, dict):
            best = {}
        matched_user_id = (
            best.get("id")
            or best.get("faculty_id")
            or entity.get("id")
            or entity.get("faculty_id")
        )
        try:
            match_confidence = float(
                best.get("confidence", entity.get("confidence") or 0.0) or 0.0
            )
        except (TypeError, ValueError):
            match_confidence = 0.0
        break

    is_internal = bool(
        matched_user_id
        and (match_confidence or 0.0) >= _IDENTITY_INTERNAL_THRESHOLD
    )
    if not is_internal:
        return None, None, False
    return matched_user_id, match_confidence, True


def _create_contributors(ip_record, result):
    """Persist extracted contributors with INTERNAL/EXTERNAL/UNKNOWN classification.

    Identity resolution results (FacultyIdentityResolutionAgent) are used to
    classify a contributor as INTERNAL_FACULTY when a real DB user was matched,
    otherwise the contributor is classified EXTERNAL (or UNKNOWN when no name).
    """
    from app.models.base import User

    session = get_session()
    try:
        # Load identity matches keyed by best-match user id.
        identity_output = next(
            (a for a in result.agent_outputs if a.get("agent_name") == "FacultyIdentityResolutionAgent"),
            None,
        )
        resolved_entities = (identity_output or {}).get("extracted_data", {}).get("resolved_entities", []) or []
        best_match_id = (identity_output or {}).get("extracted_data", {}).get("best_match_id")

        contributors = _extract_contributor_names(result)

        # Remove any existing contributor rows for this record to keep idempotent.
        existing = session.execute(
            select(IpContributor).where(IpContributor.ip_record_id == ip_record.id)
        ).scalars().all()
        for c in existing:
            session.delete(c)
        session.flush()

        for idx, contributor in enumerate(contributors):
            name = contributor.get("name") or "UNKNOWN"
            contributor_type = "UNKNOWN"
            matched_user_id = None
            match_confidence = None
            match_status = "VERIFICATION_REQUIRED"

            # Try to find a matching resolved entity for this contributor name.
            (
                matched_user_id,
                match_confidence,
                is_internal,
            ) = _resolve_contributor_match(name, resolved_entities)
            if is_internal:
                contributor_type = "INTERNAL_FACULTY"
                match_status = (
                    "CONFIRMED"
                    if (match_confidence or 0.0) >= 0.75
                    else "VERIFICATION_REQUIRED"
                )

            # If no per-name match but a single unambiguous best match exists and
            # there is only one contributor, associate it with that faculty.
            if matched_user_id is None and best_match_id and len(contributors) == 1:
                best = next((e for e in resolved_entities if (e.get("id") or e.get("faculty_id")) == best_match_id), None)
                if best:
                    matched_user_id = best.get("id") or best.get("faculty_id")
                    match_confidence = float(best.get("confidence") or 0.0)
                    contributor_type = "INTERNAL_FACULTY"
                    match_status = (
                        "CONFIRMED" if match_confidence >= 0.75 else "VERIFICATION_REQUIRED"
                    )

            if contributor_type == "UNKNOWN" and name != "UNKNOWN":
                # A name was extracted but did not match any faculty → external.
                contributor_type = "EXTERNAL"
                match_status = "NO_MATCH"

            if contributor_type != "INTERNAL_FACULTY":
                # EXTERNAL/UNKNOWN rows must never retain a candidate user id:
                # the best match below the internal floor is lookalike noise,
                # and persisting it points review, master linkage and
                # association targeting at the wrong faculty member.
                matched_user_id = None
                match_confidence = None

            session.add(
                IpContributor(
                    id=str(uuid.uuid4()),
                    ip_record_id=ip_record.id,
                    user_id=matched_user_id,
                    name=name,
                    designation=contributor.get("designation"),
                    department=contributor.get("department"),
                    institution=contributor.get("institution"),
                    contributor_type=contributor_type,
                    author_position=idx + 1,
                    match_confidence=match_confidence,
                    match_status=match_status,
                    source="CERTIFICATE_OCR",
                    is_external=(contributor_type == "EXTERNAL"),
                    contributor_order=idx,
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _master_identifier_present(ip_record) -> bool:
    """Whether the record carries any canonical master-linking identifier."""
    return bool(
        ip_record.patent_number
        or ip_record.design_number
        or ip_record.application_number
    )


def _create_or_link_master_record(ip_record, result):
    """Create (or link to) a canonical MasterIpRecord for a verified identifier.

    A master record represents one underlying patent/design, deduplicated across
    multiple submissions (certificate, grant, publication, supporting docs). The
    uploaded IpRecord and IpFile are linked to it, and MasterIpContributor rows
    are materialized from the per-submission contributors.
    """
    session = get_session()
    try:
        # Only create a master record when an identifier was extracted.
        # A patent application number is a first-class canonical identifier:
        # application publications carry no grant patent number yet, so
        # requiring patent/design numbers here would leave every pure
        # application without a master record.
        if not _master_identifier_present(ip_record):
            return

        patent_number = ip_record.patent_number
        design_number = ip_record.design_number
        application_number = ip_record.application_number

        # Find an existing master record by identifier (dedupe layer).
        query = select(MasterIpRecord)
        conditions = []
        if patent_number:
            conditions.append(MasterIpRecord.patent_number == patent_number)
        if design_number:
            conditions.append(MasterIpRecord.design_number == design_number)
        if application_number:
            conditions.append(MasterIpRecord.application_number == application_number)
        if conditions:
            query = query.where(or_(*conditions))
        else:
            return

        master = session.execute(query).scalars().first()

        if not master:
            master = MasterIpRecord(
                id=str(uuid.uuid4()),
                ip_type=ip_record.ip_type,
                patent_number=patent_number,
                application_number=application_number,
                design_number=design_number,
                title=ip_record.title,
                filing_date=ip_record.filing_date,
                registration_date=ip_record.registration_date,
                grant_date=ip_record.grant_date,
                status="ACTIVE",
                workflow_state=ip_record.workflow_state or "UPLOADED",
            )
            session.add(master)
            session.flush()

        # Link the IpRecord to the master record.
        ip_record.master_ip_id = master.id
        if not ip_record.workflow_state:
            ip_record.workflow_state = "UPLOADED"

        # Link IpFile records to the master record.
        files = session.execute(
            select(IpFile).where(IpFile.ip_record_id == ip_record.id)
        ).scalars().all()
        for f in files:
            f.master_ip_id = master.id

        # Materialize master contributors from submission contributors.
        contributors = session.execute(
            select(IpContributor).where(IpContributor.ip_record_id == ip_record.id)
        ).scalars().all()
        existing_master_contributor_names = {
            mc.name.lower()
            for mc in session.execute(
                select(MasterIpContributor).where(MasterIpContributor.master_ip_id == master.id)
            ).scalars().all()
        }
        for c in contributors:
            if (c.name or "").lower() in existing_master_contributor_names:
                continue
            session.add(
                MasterIpContributor(
                    id=str(uuid.uuid4()),
                    master_ip_id=master.id,
                    name=c.name,
                    contributor_type=c.contributor_type,
                    matched_faculty_id=c.user_id,
                    author_position=c.author_position,
                    match_confidence=c.match_confidence,
                    match_status=c.match_status,
                    institution=c.institution,
                    source=c.source or "CERTIFICATE_OCR",
                )
            )

        session.commit()
        logger.info(
            "master_record_linked",
            ip_record_id=ip_record.id,
            master_ip_id=master.id,
            patent_number=patent_number,
            design_number=design_number,
        )
    except Exception as exc:
        session.rollback()
        # Master-record linking is best-effort: a failure must not fail the whole
        # pipeline, but it should be visible in logs for follow-up.
        logger.warning("master_record_link_failed", ip_record_id=ip_record.id, error=str(exc))
    finally:
        session.close()


def _capture_profile_snapshot(ip_record):
    """Capture an immutable faculty profile snapshot for historical preservation.

    Stores the faculty's name, department, and designation at the moment the IP
    record is associated with them. This preserves the historical context even if
    the faculty later changes departments or designations.
    """
    session = get_session()
    try:
        uploader_id = ip_record.uploader_id
        master_ip_id = ip_record.master_ip_id
        if not uploader_id or not master_ip_id:
            return

        faculty = session.execute(select(User).where(User.id == uploader_id)).scalar_one_or_none()
        if not faculty:
            return

        from app.models.base import Department, Designation

        dept = session.execute(select(Department).where(Department.id == faculty.department_id)).scalar_one_or_none()
        desig = session.execute(select(Designation).where(Designation.id == faculty.designation_id)).scalar_one_or_none()

        # Avoid duplicate snapshots for the same faculty+master record.
        existing = session.execute(
            select(FacultyProfileSnapshot).where(
                FacultyProfileSnapshot.faculty_id == faculty.id,
                FacultyProfileSnapshot.master_ip_id == master_ip_id,
            )
        ).scalars().first()
        if existing:
            return

        session.add(
            FacultyProfileSnapshot(
                id=str(uuid.uuid4()),
                faculty_id=faculty.id,
                master_ip_id=master_ip_id,
                full_name=faculty.full_name,
                department_name=dept.name if dept else None,
                designation_name=desig.name or desig.title if desig else None,
            )
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.warning("profile_snapshot_failed", ip_record_id=ip_record.id, error=str(exc))
    finally:
        session.close()


def _map_overall_status(overall_status: str) -> str:
    # Keep the persisted status inside the legacy enum values supported by the DB.
    return {"completed": "COMPLETED", "completed_partial": "AWAITING_REVIEW", "completed_with_errors": "AWAITING_REVIEW", "human_review_required": "AWAITING_REVIEW", "failed": "FAILED"}.get(overall_status, "FAILED")


def _derive_workflow_state(ip_record, result) -> str:
    """Derive and advance the workflow state using the state machine.

    This consolidates verification, conflict, duplicate, and review signals into a
    single canonical ``workflow_state`` on the IpRecord.
    """
    from app.services.workflow import (
        WorkflowState,
        advance_through,
        coerce_state,
        derive_state_from_verification,
    )

    current = ip_record.workflow_state
    verification_status = ip_record.verification_status

    target = derive_state_from_verification(verification_status)

    open_duplicates = any(
        a.get("agent_name") == "DuplicateDetectionAgent" and a.get("conflicts")
        for a in result.agent_outputs
    )
    open_conflicts = any(
        a.get("agent_name") == "ConflictResolutionAgent" and a.get("conflicts")
        for a in result.agent_outputs
    )
    open_identity_review = any(
        a.get("agent_name") == "FacultyIdentityResolutionAgent" and a.get("conflicts")
        for a in result.agent_outputs
    )
    # Check for faculty approval pending
    faculty_approval_pending = any(
        a.get("agent_name") == "AssociationRecommendationAgent" and a.get("extracted_data", {}).get("recommendations")
        for a in result.agent_outputs
    )

    if open_duplicates:
        target = WorkflowState.DUPLICATE_REVIEW
    elif open_conflicts:
        target = WorkflowState.DATA_CONFLICT
    elif open_identity_review:
        target = WorkflowState.IDENTITY_REVIEW
    elif faculty_approval_pending:
        target = WorkflowState.FACULTY_APPROVAL_PENDING
    elif target == WorkflowState.VERIFIED and result.overall_requires_human_review:
        target = WorkflowState.NEEDS_REVIEW

    if target in (WorkflowState.VERIFICATION_PENDING, WorkflowState.VERIFICATION_REQUIRED):
        if not (verification_status or ip_record.patent_number or ip_record.design_number):
            target = (
                WorkflowState.IDENTIFIER_FOUND
                if (ip_record.patent_number or ip_record.design_number)
                else coerce_state(current)
            )

    return advance_through(current, target)











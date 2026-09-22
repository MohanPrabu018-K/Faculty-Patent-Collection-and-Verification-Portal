from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, UploadFile, File, Request, status, Query
from fastapi.responses import JSONResponse
import structlog

from app.core.config import app_settings, upload_settings
from app.api.deps import get_current_user
from app.core.exceptions import PortalError
from app.core.database import get_async_session
from app.models.base import (
    AssociationRequest,
    AuditLog,
    ConflictCase,
    Department,
    Designation,
    DuplicateCase,
    FieldProvenance,
    IpContributor,
    IpFile,
    IpRecord,
    ProcessingJob,
    User,
)
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/faculty", tags=["faculty"])


def _qr_data_list(value: str | None) -> list[str]:
    """Normalize the persisted scalar qr_data string into a list for the API.

    The database stores QR payloads as a single Text value; the API contract
    (and the frontend) exposes them as a list so that multiple QR codes remain
    representable without a schema change.
    """
    if value:
        return [value]
    return []


@router.get("/profile", status_code=status.HTTP_200_OK)
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    user_id = current_user.get("id")

    user = (
        await db.execute(
            select(User).where(User.id == user_id)
        )
    ).scalar_one_or_none()

    if not user:
        return {
            "id": user_id,
            "email": current_user.get("email"),
            "full_name": current_user.get("full_name"),
            "role": current_user.get("role"),
            "faculty_id": current_user.get("faculty_id"),
        }

    dept = (
        (
            await db.execute(
                select(Department).where(
                    Department.id == user.department_id
                )
            )
        ).scalar_one_or_none()
        if user.department_id
        else None
    )

    desig = (
        (
            await db.execute(
                select(Designation).where(
                    Designation.id == user.designation_id
                )
            )
        ).scalar_one_or_none()
        if user.designation_id
        else None
    )

    base = (
        select(func.count())
        .select_from(IpRecord)
        .where(IpRecord.uploader_id == user_id)
    )

    total_documents = (await db.execute(base)).scalar_one()
    patents = (
        await db.execute(
            base.where(IpRecord.ip_type == "PATENT")
        )
    ).scalar_one()

    designs = (
        await db.execute(
            base.where(IpRecord.ip_type == "DESIGN_REGISTRATION")
        )
    ).scalar_one()

    verified = (
        await db.execute(
            base.where(IpRecord.verification_status == "VERIFIED")
        )
    ).scalar_one()

    pending_verification = (
        await db.execute(
            base.where(
                IpRecord.verification_status.in_(
                    ["UNVERIFIED", "VERIFICATION_REQUIRED"]
                )
            )
        )
    ).scalar_one()

    awaiting_review = (
        await db.execute(
            base.where(
                IpRecord.processing_status == "AWAITING_REVIEW"
            )
        )
    ).scalar_one()

    return {
        "id": user.id,
        "email": user.email,
        "official_email": user.official_email,
        "full_name": user.full_name,
        "role": user.role,
        "faculty_id": user.faculty_id,
        "department_id": user.department_id,
        "department_name": dept.name if dept else None,
        "designation_id": user.designation_id,
        "designation_name": (
            (desig.name or desig.title)
            if desig
            else None
        ),
        "joining_date": (
            user.joining_date.isoformat()
            if user.joining_date
            else None
        ),
        "status": user.status,
        "is_active": user.is_active,
        "created_at": (
            user.created_at.isoformat()
            if user.created_at
            else None
        ),
        "counts": {
            "total_documents": total_documents,
            "patents": patents,
            "designs": designs,
            "verified": verified,
            "pending_verification": pending_verification,
            "awaiting_review": awaiting_review,
        },
    }


@router.get("/history", status_code=status.HTTP_200_OK)
async def faculty_history(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
):
    """
    Faculty-scoped activity timeline.

    Includes:
    - audit events performed by the faculty
    - events on records uploaded by the faculty
    - upload/review/correction/verification events
    - duplicate/conflict events
    - association events
    - status changes
    """

    user_id = current_user.get("id")

    record_ids = (
        select(IpRecord.id)
        .where(IpRecord.uploader_id == user_id)
    )

    # Association requests initiated by this user: their full lifecycle
    # (sent / accepted / rejected / not-me / clarification) belongs in the
    # requester's timeline even though the responding actor is another user.
    sent_association_ids = (
        select(AssociationRequest.id)
        .where(
            or_(
                AssociationRequest.requesting_faculty_id == user_id,
                AssociationRequest.requester_id == user_id,
            )
        )
    )

    scope = or_(
        AuditLog.actor_id == user_id,
        AuditLog.entity_id.in_(record_ids),
        AuditLog.target_id.in_(record_ids),
        AuditLog.entity_id.in_(sent_association_ids),
        AuditLog.target_id.in_(sent_association_ids),
    )

    total = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(scope)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(AuditLog)
            .where(scope)
            .order_by(AuditLog.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    return {
        "events": [
            {
                "id": r.id,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "actor_id": r.actor_id,
                "previous_value": r.previous_value,
                "new_value": r.new_value,
                "created_at": (
                    r.created_at.isoformat()
                    if r.created_at
                    else None
                ),
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (
            (total + per_page - 1) // per_page
        ),
    }


@router.get("/dashboard", status_code=status.HTTP_200_OK)
async def get_dashboard(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    faculty_id = current_user.get("faculty_id")
    user_id = current_user.get("id")

    # Processing status counts
    query = (
        select(
            IpRecord.processing_status,
            func.count(IpRecord.id).label("count"),
        )
        .where(IpRecord.uploader_id == user_id)
        .group_by(IpRecord.processing_status)
    )

    result = await db.execute(query)
    status_counts = {
        row.processing_status: row.count
        for row in result
    }

    # Verification status counts
    query = (
        select(
            IpRecord.verification_status,
            func.count(IpRecord.id).label("count"),
        )
        .where(IpRecord.uploader_id == user_id)
        .group_by(IpRecord.verification_status)
    )

    result = await db.execute(query)
    verification_counts = {
        row.verification_status: row.count
        for row in result
    }

    # IP type counts
    query = (
        select(
            IpRecord.ip_type,
            func.count(IpRecord.id).label("count"),
        )
        .where(IpRecord.uploader_id == user_id)
        .group_by(IpRecord.ip_type)
    )

    result = await db.execute(query)
    ip_type_counts = {
        row.ip_type: row.count
        for row in result
    }

    # Recent records
    query = (
        select(IpRecord)
        .where(IpRecord.uploader_id == user_id)
        .order_by(IpRecord.created_at.desc())
        .limit(5)
    )

    result = await db.execute(query)
    recent_records = result.scalars().all()

    records_summary = {
        "total": sum(status_counts.values()),
        "pending": (
            status_counts.get("PENDING", 0)
            + status_counts.get("QUEUED", 0)
        ),
        "processing": status_counts.get("PROCESSING", 0),
        "completed": status_counts.get("COMPLETED", 0),
        "awaiting_review": status_counts.get(
            "AWAITING_REVIEW",
            0,
        ),
        "failed": status_counts.get("FAILED", 0),
    }

    return {
        "faculty_id": faculty_id,
        "role": current_user.get("role", ""),
        "records_summary": records_summary,
        "verification_summary": verification_counts,
        "ip_type_summary": ip_type_counts,
        "recent_records": [
            {
                "id": r.id,
                "ip_type": r.ip_type,
                "patent_number": r.patent_number,
                "design_number": r.design_number,
                "title": r.title,
                "processing_status": r.processing_status,
                "verification_status": r.verification_status,
                "created_at": (
                    r.created_at.isoformat()
                    if r.created_at
                    else None
                ),
            }
            for r in recent_records
        ],
    }


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_certificate(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Backwards-compatible faculty upload endpoint.

    The actual full upload-processing pipeline is handled by
    /api/v1/uploads/.
    """

    original_filename = file.filename or "unknown"

    file_extension = (
        original_filename.rsplit(".", 1)[-1].lower()
        if "." in original_filename
        else ""
    )

    # IMPORTANT:
    # allowed_extensions belongs to UploadSettings,
    # not AppSettings.
    if f".{file_extension}" not in upload_settings.allowed_extensions:
        raise PortalError(
            message=(
                f"Unsupported file extension: "
                f".{file_extension}"
            ),
            error_code="UPLOAD_ERROR",
            status_code=400,
        )

    content = await file.read()

    # IMPORTANT:
    # max_upload_bytes belongs to UploadSettings + Super Admin runtime override.
    from app.core.runtime_settings import get_max_upload_bytes as _max_bytes
    _limit = _max_bytes(upload_settings.max_upload_bytes)
    if len(content) > _limit:
        raise PortalError(
            message=(
                f"File too large: {len(content)} bytes "
                f"(max: {_limit})"
            ),
            error_code="UPLOAD_ERROR",
            status_code=400,
        )

    faculty_id = current_user.get("faculty_id")

    logger.info(
        "certificate_upload_initiated",
        faculty_id=faculty_id,
        request_id=getattr(
            request.state,
            "request_id",
            None,
        ),
        filename=original_filename,
        file_size=len(content),
        content_type=file.content_type,
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "pending",
            "message": (
                "Certificate upload received - "
                "use /api/v1/uploads/ for full processing"
            ),
            "filename": original_filename,
            "faculty_id": faculty_id,
        },
    )


@router.get(
    "/my-records",
    status_code=status.HTTP_200_OK,
)
async def my_ip_records(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
    verification_status: str = Query(None),
    ip_type: str = Query(None),
    processing_status: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    faculty_id = current_user.get("faculty_id")
    user_id = current_user.get("id")

    query = (
        select(IpRecord)
        .where(IpRecord.uploader_id == user_id)
    )

    if verification_status:
        query = query.where(
            IpRecord.verification_status
            == verification_status
        )

    if ip_type:
        query = query.where(
            IpRecord.ip_type == ip_type
        )

    if processing_status:
        query = query.where(
            IpRecord.processing_status
            == processing_status
        )

    count_query = (
        select(func.count())
        .select_from(query.subquery())
    )

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = (
        query
        .order_by(IpRecord.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )

    result = await db.execute(query)
    records = result.scalars().all()

    return {
        "records": [
            {
                "id": r.id,
                "ip_type": r.ip_type,
                "patent_number": r.patent_number,
                "design_number": r.design_number,
                "application_number": r.application_number,
                "serial_number": r.serial_number,
                "title": r.title,
                "applicant": r.applicant,
                "patentee": r.patentee,
                "verification_status": r.verification_status,
                "processing_status": r.processing_status,
                "filing_date": (
                    r.filing_date.isoformat()
                    if r.filing_date
                    else None
                ),
                "grant_date": (
                    r.grant_date.isoformat()
                    if r.grant_date
                    else None
                ),
                "published_date": (
                    r.published_date.isoformat()
                    if r.published_date
                    else None
                ),
                "department_id": r.department_id,
                "designation_id": r.designation_id,
                "evidence": r.evidence,
                "qr_data": _qr_data_list(r.qr_data),
                "created_at": (
                    r.created_at.isoformat()
                    if r.created_at
                    else None
                ),
                "updated_at": (
                    r.updated_at.isoformat()
                    if r.updated_at
                    else None
                ),
            }
            for r in records
        ],
        "count": len(records),
        "total": total,
        "faculty_id": faculty_id,
        "filters_applied": {
            "verification_status": verification_status,
            "ip_type": ip_type,
            "processing_status": processing_status,
        },
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_pages": (
                (total + per_page - 1) // per_page
            ),
        },
    }


@router.get(
    "/{record_id}/status",
    status_code=status.HTTP_200_OK,
)
async def get_record_status(
    record_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    user_id = current_user.get("id")
    user_role = current_user.get("role", "faculty")

    query = (
        select(
            IpRecord,
            User.faculty_id.label("faculty_id"),
            User.full_name.label("faculty_name"),
        )
        .join(
            User,
            User.id == IpRecord.uploader_id,
        )
        .where(IpRecord.id == record_id)
    )

    if user_role == "faculty":
        query = query.where(
            IpRecord.uploader_id == user_id
        )

    elif user_role == "hod_admin":
        dept = current_user.get("department_id")

        if not dept:
            raise PortalError(
                message="HOD account is missing a department",
                error_code="AUTHORIZATION_ERROR",
                status_code=403,
            )

        query = query.where(
            IpRecord.department_id == dept
        )

    result = await db.execute(query)
    row = result.first()

    if not row:
        raise PortalError(
            message="Record not found",
            error_code="NOT_FOUND",
            status_code=404,
        )

    ip_record = row[0]
    faculty_id = row[1]
    faculty_name = row[2]

    designation_name = None

    if ip_record.designation_id:
        designation = (
            await db.execute(
                select(Designation).where(
                    Designation.id
                    == ip_record.designation_id
                )
            )
        ).scalar_one_or_none()

        designation_name = (
            (designation.name or designation.title)
            if designation
            else None
        )

    # Processing jobs
    jobs_result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.ip_record_id
            == record_id
        )
    )

    jobs = jobs_result.scalars().all()

    # Files
    files_result = await db.execute(
        select(IpFile).where(
            IpFile.ip_record_id
            == record_id
        )
    )

    files = files_result.scalars().all()

    # Contributors
    contributors_result = await db.execute(
        select(IpContributor).where(
            IpContributor.ip_record_id
            == record_id
        )
    )

    contributors = contributors_result.scalars().all()

    # Resolved college identities for contributors, so the record detail
    # page can offer the uploader a "send association request" action that
    # targets the existing POST /associations/ endpoint (faculty lookup by
    # faculty_id). Read-only map; no authorization changes.
    _contributor_faculty: dict[str, str | None] = {}
    _contributor_user_ids = {
        c.user_id for c in contributors if c.user_id
    }
    if _contributor_user_ids:
        for _u in (
            await db.execute(
                select(User).where(
                    User.id.in_(_contributor_user_ids)
                )
            )
        ).scalars().all():
            _contributor_faculty[_u.id] = _u.faculty_id

    # Field provenance
    provenance_result = await db.execute(
        select(FieldProvenance).where(
            FieldProvenance.ip_record_id
            == record_id
        )
    )

    provenance = provenance_result.scalars().all()

    # Duplicate case
    duplicate_case = (
        await db.execute(
            select(DuplicateCase)
            .where(
                or_(
                    DuplicateCase.ip_record_id_1
                    == record_id,
                    DuplicateCase.ip_record_id_2
                    == record_id,
                )
            )
            .order_by(
                DuplicateCase.detected_at.desc()
            )
        )
    ).scalars().first()

    # Conflict case
    conflict_case = (
        await db.execute(
            select(ConflictCase)
            .where(
                ConflictCase.ip_record_id
                == record_id
            )
            .order_by(
                ConflictCase.created_at.desc()
            )
        )
    ).scalars().first()

    other_dup_id = None

    if duplicate_case:
        other_dup_id = (
            duplicate_case.ip_record_id_2
            if duplicate_case.ip_record_id_1
            == record_id
            else duplicate_case.ip_record_id_1
        )

    return {
        "record_id": ip_record.id,
        "uploader_id": ip_record.uploader_id,
        "faculty_id": faculty_id,
        "faculty_name": faculty_name,
        "workflow_state": ip_record.workflow_state,
        "master_ip_id": ip_record.master_ip_id,
        "department_id": ip_record.department_id,
        "department_name": (
            ip_record.historical_department_name
        ),
        "designation_name": designation_name,
        "duplicate_status": (
            duplicate_case.status
            if duplicate_case
            else None
        ),
        "duplicate_case_id": (
            duplicate_case.id
            if duplicate_case
            else None
        ),
        "duplicate_confidence": (
            duplicate_case.confidence
            if duplicate_case
            else None
        ),
        "duplicate_of_record_id": other_dup_id,
        "conflict_status": (
            conflict_case.status
            if conflict_case
            else None
        ),
        "conflict_type": (
            conflict_case.conflict_type
            if conflict_case
            else None
        ),
        "conflict_description": (
            conflict_case.description
            if conflict_case
            else None
        ),
        "ip_type": ip_record.ip_type,
        "patent_number": ip_record.patent_number,
        "design_number": ip_record.design_number,
        "application_number": ip_record.application_number,
        "serial_number": ip_record.serial_number,
        "title": ip_record.title,
        "applicant": ip_record.applicant,
        "patentee": ip_record.patentee,
        "verification_status": (
            ip_record.verification_status
        ),
        "processing_status": (
            ip_record.processing_status
        ),
        "filing_date": (
            ip_record.filing_date.isoformat()
            if ip_record.filing_date
            else None
        ),
        "grant_date": (
            ip_record.grant_date.isoformat()
            if ip_record.grant_date
            else None
        ),
        "published_date": (
            ip_record.published_date.isoformat()
            if ip_record.published_date
            else None
        ),
        "contributor_name": (
            ip_record.contributor_name
        ),
        "contributor_designation": (
            ip_record.contributor_designation
        ),
        "contributor_department": (
            ip_record.contributor_department
        ),
        "contributor_country": (
            ip_record.contributor_country
        ),
        "evidence": ip_record.evidence,
        "qr_data": _qr_data_list(ip_record.qr_data),
        "certificate_type": (
            ip_record.certificate_type
        ),
        "source_reference": (
            ip_record.source_reference
        ),
        "created_at": (
            ip_record.created_at.isoformat()
            if ip_record.created_at
            else None
        ),
        "updated_at": (
            ip_record.updated_at.isoformat()
            if ip_record.updated_at
            else None
        ),
        "jobs": [
            {
                "job_type": job.job_type,
                "status": job.status,
                "retry_count": job.retry_count,
                "error_message": job.error_message,
                "result": job.result,
                "created_at": (
                    job.created_at.isoformat()
                    if job.created_at
                    else None
                ),
                "completed_at": (
                    job.completed_at.isoformat()
                    if job.completed_at
                    else None
                ),
            }
            for job in jobs
        ],
        "files": [
            {
                "id": f.id,
                "storage_key": f.storage_key,
                "original_filename": (
                    f.original_filename
                ),
                "file_extension": (
                    f.file_extension
                ),
                "file_size_bytes": (
                    f.file_size_bytes
                ),
                "mime_type": f.mime_type,
                "fingerprint": f.fingerprint,
                "page_count": f.page_count,
                "width_px": f.width_px,
                "height_px": f.height_px,
                "upload_status": (
                    f.upload_status
                ),
            }
            for f in files
        ],
        "contributors": [
            {
                "id": c.id,
                "name": c.name,
                "designation": c.designation,
                "department": c.department,
                "contributor_type": (
                    c.contributor_type
                ),
                "match_confidence": (
                    c.match_confidence
                ),
                "match_status": c.match_status,
                "is_external": c.is_external,
                "contributor_order": (
                    c.contributor_order
                ),
                # Resolved college identity (None when unresolved/external).
                # The record detail page needs these so the uploader can send
                # association requests to internal co-contributors via the
                # existing POST /associations/ endpoint (which looks faculty
                # up by faculty_id). No authorization logic changes.
                "user_id": c.user_id,
                "faculty_id": _contributor_faculty.get(
                    c.user_id
                )
                if c.user_id
                else None,
            }
            for c in contributors
        ],
        "field_provenance": [
            {
                "id": p.id,
                "field_name": p.field_name,
                "value": p.value,
                "source": p.source,
                "confidence": p.confidence,
                "status": p.status,
                "certificate_value": (
                    p.certificate_value
                ),
                "official_value": (
                    p.official_value
                ),
            }
            for p in provenance
        ],
    }


_REVIEWABLE_FIELDS = (
    "title",
    "applicant",
    "patentee",
    "patent_number",
    "design_number",
    "application_number",
    "serial_number",
    "filing_date",
    "grant_date",
    "published_date",
    "contributor_name",
    "contributor_designation",
    "contributor_department",
)


@router.post(
    "/{record_id}/review",
    status_code=status.HTTP_200_OK,
)
async def submit_record_review(
    request: Request,
    record_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Uploader review.

    Faculty can confirm extracted fields or submit corrections.
    Corrections are recorded in field_provenance and the
    corresponding IpRecord field is updated.
    """

    from app.core.logging import log_audit

    user_id = current_user.get("id")

    body = (
        await request.json()
        if request.headers.get(
            "content-type",
            "",
        ).startswith("application/json")
        else {}
    )

    record = (
        await db.execute(
            select(IpRecord).where(
                IpRecord.id == record_id
            )
        )
    ).scalar_one_or_none()

    if not record:
        raise PortalError(
            message="Record not found",
            error_code="NOT_FOUND",
            status_code=404,
        )

    if record.uploader_id != user_id:
        raise PortalError(
            message="Only the uploader may review this record",
            error_code="AUTHORIZATION_ERROR",
            status_code=403,
        )

    corrections = (
        body.get("corrections")
        or body.get("fields")
        or {}
    )

    if not isinstance(corrections, dict):
        raise PortalError(
            message="corrections must be an object",
            error_code="VALIDATION_ERROR",
            status_code=422,
        )

    for field, value in corrections.items():

        if field not in _REVIEWABLE_FIELDS:
            continue

        old_value = getattr(
            record,
            field,
            None,
        )

        if (
            field == "filing_date"
            and isinstance(value, str)
            and value
        ):
            try:
                from app.services.extraction import normalize_date

                parsed = normalize_date(value)
                record.filing_date = parsed
            except Exception:
                pass

        elif (
            field in (
                "grant_date",
                "published_date",
            )
            and isinstance(value, str)
            and value
        ):
            try:
                from app.services.extraction import normalize_date

                setattr(
                    record,
                    field,
                    normalize_date(value),
                )
            except Exception:
                pass

        else:
            try:
                setattr(
                    record,
                    field,
                    value,
                )
            except Exception:
                pass

        # Upsert field provenance row
        existing = (
            await db.execute(
                select(FieldProvenance).where(
                    and_(
                        FieldProvenance.ip_record_id
                        == record_id,
                        FieldProvenance.field_name
                        == field,
                    )
                )
            )
        ).scalars().all()

        if existing:
            for row in existing:
                row.certificate_value = (
                    row.value
                    or str(old_value)
                    if old_value is not None
                    else row.certificate_value
                )

                row.value = (
                    str(value)
                    if value is not None
                    else row.value
                )

                row.source = "FACULTY_CONFIRMED"
                row.status = "CONFIRMED"
                row.confidence = 1.0

        else:
            db.add(
                FieldProvenance(
                    id=str(uuid.uuid4()),
                    ip_record_id=record_id,
                    master_ip_id=record.master_ip_id,
                    field_name=field,
                    value=(
                        str(value)
                        if value is not None
                        else None
                    ),
                    source="FACULTY_CONFIRMED",
                    confidence=1.0,
                    status="CONFIRMED",
                    certificate_value=(
                        str(old_value)
                        if old_value is not None
                        else None
                    ),
                )
            )

    if corrections:
        record.processing_status = "AWAITING_REVIEW"

    await db.commit()

    log_audit(
        actor=user_id,
        action="RECORD_REVIEWED",
        target_type="ip_record",
        target_id=record_id,
        status="reviewed",
        after={
            "fields": list(corrections.keys())
        },
    )

    return {
        "record_id": record_id,
        "status": "reviewed",
        "corrected_fields": list(
            corrections.keys()
        ),
        "message": (
            "Review recorded - changes are "
            "pending final verification"
        ),
    }


@router.post(
    "/{record_id}/request-verification",
    status_code=status.HTTP_200_OK,
)
async def request_verification(
    request: Request,
    record_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    user_id = current_user.get("id")
    user_role = current_user.get(
        "role",
        "faculty",
    )

    query = (
        select(
            IpRecord,
            User.faculty_id.label("faculty_id"),
            User.full_name.label("faculty_name"),
        )
        .join(
            User,
            User.id == IpRecord.uploader_id,
        )
        .where(IpRecord.id == record_id)
    )

    if user_role == "faculty":
        query = query.where(
            IpRecord.uploader_id == user_id
        )

    result = await db.execute(query)
    row = result.first()

    if not row:
        raise PortalError(
            message="Record not found",
            error_code="NOT_FOUND",
            status_code=404,
        )

    ip_record = row[0]

    if (
        not ip_record.patent_number
        and not ip_record.design_number
        and not ip_record.application_number
    ):
        raise PortalError(
            message=(
                "Cannot verify record without "
                "patent, design, or application number"
            ),
            error_code="VERIFICATION_ERROR",
            status_code=400,
        )

    ip_record.verification_status = (
        "VERIFICATION_REQUIRED"
    )

    await db.commit()

    from app.core.logging import log_audit

    log_audit(
        actor=user_id,
        action="VERIFICATION_REQUESTED",
        target_type="ip_record",
        target_id=record_id,
        status="initiated",
        before={
            "verification_status": "UNVERIFIED"
        },
        after={
            "verification_status":
                "VERIFICATION_REQUIRED"
        },
        extra={
            "requested_by": user_id
        },
    )

    return {
        "record_id": record_id,
        "status": "verification_initiated",
        "message": (
            "Verification requested - will be "
            "processed asynchronously"
        ),
    }


@router.post(
    "/{record_id}/associate/{other_faculty_id}",
    status_code=status.HTTP_201_CREATED,
)
async def request_association(
    request: Request,
    record_id: str,
    other_faculty_id: str,
    reason: str = "",
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    user_id = current_user.get("id")
    user_role = current_user.get(
        "role",
        "faculty",
    )

    # Verify record and access
    query = (
        select(
            IpRecord,
            User.faculty_id.label("faculty_id"),
            User.full_name.label("faculty_name"),
        )
        .join(
            User,
            User.id == IpRecord.uploader_id,
        )
        .where(IpRecord.id == record_id)
    )

    if user_role == "faculty":
        query = query.where(
            IpRecord.uploader_id == user_id
        )

    result = await db.execute(query)
    row = result.first()

    if not row:
        raise PortalError(
            message="Record not found",
            error_code="NOT_FOUND",
            status_code=404,
        )

    ip_record = row[0]

    # Verify target faculty
    other_faculty = await db.execute(
        select(User).where(
            User.faculty_id
            == other_faculty_id
        )
    )

    other_user = (
        other_faculty.scalar_one_or_none()
    )

    if not other_user:
        raise PortalError(
            message="Target faculty not found",
            error_code="NOT_FOUND",
            status_code=404,
        )

    # Create association request
    from app.models.base import AssociationRequest

    association = AssociationRequest(
        id=str(uuid.uuid4()),
        ip_record_id=record_id,
        master_ip_id=ip_record.master_ip_id,
        requesting_faculty_id=user_id,
        target_faculty_id=other_user.id,
        requester_id=user_id,
        recipient_id=other_user.id,
        reason=reason,
        status="PENDING",
    )

    db.add(association)
    await db.commit()

    from app.core.logging import log_audit

    log_audit(
        actor=user_id,
        action="ASSOCIATION_REQUESTED",
        target_type="ip_record",
        target_id=record_id,
        status="pending",
        before={},
        after={
            "recipient_faculty_id":
                other_faculty_id,
            "reason": reason,
        },
    )

    from app.services.notifications import (
        NotificationPriority,
        NotificationType,
        get_notification_service,
    )

    try:
        await get_notification_service().create_notification(
            user_id=other_user.id,
            notification_type=(
                NotificationType.ASSOCIATION_REQUEST
            ),
            title="New association request",
            message=(
                f"{current_user.get('full_name', 'A faculty member')} "
                "requested an association review for "
                "your record."
            ),
            priority=NotificationPriority.HIGH,
            related_entity_type="association_request",
            related_entity_id=association.id,
            action_url=(
                f"/faculty/associations"
            ),
            action_label="Review request",
            metadata={
                "request_id": association.id,
                "record_id": record_id,
            },
        )

    except Exception:
        logger.warning(
            "association_notification_failed",
            association_id=association.id,
            recipient_id=other_user.id,
        )

    return {
        "association_id": association.id,
        "status": association.status,
        "record_id": record_id,
        "recipient_faculty_id": other_faculty_id,
        "reason": reason,
        "message": "Association request sent",
    }
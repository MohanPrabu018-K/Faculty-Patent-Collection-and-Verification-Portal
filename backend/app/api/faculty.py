from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, UploadFile, File, Request, status, Query
from fastapi.responses import JSONResponse
import structlog

from app.core.config import app_settings, upload_settings
from app.api.deps import get_current_user
from app.core.exceptions import AuthorizationError, NotFoundError, PortalError
from app.core.database import get_async_session
from app.services.export_renderers import api_date_only
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
    MasterIpContributor,
    MasterIpRecord,
    ProcessingJob,
    User,
)
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.identity_resolution import calculate_name_similarity, normalize_name


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


def _faculty_record_scope(user_id: str):
    """WHERE clause matching every record visible to a faculty member.

    Bug 1: an accepted association links the recipient to the record
    (IpContributor row created on accept). Faculty B must see accepted
    patents in dashboard/profile/records/detail — not just uploads.
    Scope = uploader OR accepted internal contributor OR accepted/approved
    association party (covers associations accepted before the contributor
    link existed). Backend rows remain the source of truth; this only
    widens read visibility, never writes workflow state.
    """
    contributor_ids = (
        select(IpContributor.ip_record_id)
        .where(
            IpContributor.user_id == user_id,
            IpContributor.match_status.in_(("CONFIRMED", "CONFIRMED_INTERNAL", "ACCEPTED", "APPROVED")),
        )
    )
    accepted_assoc_ids = (
        select(AssociationRequest.ip_record_id)
        .where(
            or_(
                AssociationRequest.requesting_faculty_id == user_id,
                AssociationRequest.requester_id == user_id,
                AssociationRequest.target_faculty_id == user_id,
                AssociationRequest.recipient_id == user_id,
            ),
            AssociationRequest.status.in_(("ACCEPTED", "APPROVED")),
            AssociationRequest.ip_record_id.is_not(None),
        )
    )
    return or_(
        IpRecord.uploader_id == user_id,
        IpRecord.id.in_(contributor_ids),
        IpRecord.id.in_(accepted_assoc_ids),
    )


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
        .where(_faculty_record_scope(user_id))
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

    # Processing status counts (own uploads + accepted associations)
    query = (
        select(
            IpRecord.processing_status,
            func.count(IpRecord.id).label("count"),
        )
        .where(_faculty_record_scope(user_id))
        .group_by(IpRecord.processing_status)
    )

    result = await db.execute(query)
    status_counts = {
        row.processing_status: row.count
        for row in result
    }

    # Verification status counts (own uploads + accepted associations)
    query = (
        select(
            IpRecord.verification_status,
            func.count(IpRecord.id).label("count"),
        )
        .where(_faculty_record_scope(user_id))
        .group_by(IpRecord.verification_status)
    )

    result = await db.execute(query)
    verification_counts = {
        row.verification_status: row.count
        for row in result
    }

    # IP type counts (own uploads + accepted associations)
    query = (
        select(
            IpRecord.ip_type,
            func.count(IpRecord.id).label("count"),
        )
        .where(_faculty_record_scope(user_id))
        .group_by(IpRecord.ip_type)
    )

    result = await db.execute(query)
    ip_type_counts = {
        row.ip_type: row.count
        for row in result
    }

    # Recent records (own uploads + accepted associations)
    query = (
        select(IpRecord)
        .where(_faculty_record_scope(user_id))
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
        .where(_faculty_record_scope(user_id))
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
                "filing_date": api_date_only(r.filing_date),
                "registration_date": (
                    r.registration_date.isoformat()
                    if r.registration_date
                    else None
                ),
                "grant_date": api_date_only(r.grant_date),
                "certificate_date": api_date_only(r.certificate_date),
                "published_date": api_date_only(r.published_date or getattr(r, "publication_date", None)),
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
        # Bug 1: uploader plus accepted contributors/associates may view the
        # record detail. Mutations (review, request-verification) stay
        # uploader-scoped in their own endpoints.
        query = query.where(
            _faculty_record_scope(user_id)
        )

    elif user_role == "hod_admin":
        dept = current_user.get("department_id")

        if not dept:
            raise PortalError(
                message="HOD account is missing a department",
                error_code="AUTHORIZATION_ERROR",
                status_code=403,
            )

        # B12: no record-department SQL filter here. Multi-department patents
        # are governed by the shared HOD visibility rule enforced below, so a
        # record listed in GET /hod/documents is also readable here.

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

    if user_role == "hod_admin":
        # B12: enforce the exact HOD visibility rule shared with
        # GET /hod/documents (past-faculty-stage records whose represented
        # departments — uploader/contributor/record departments — include the
        # HOD's department). Records still in faculty association stay
        # invisible. The 404 contract is byte-identical to before, so account
        # or record existence cannot be probed through status differences.
        from app.api.hod import _hod_visible_record_ids

        visible = await _hod_visible_record_ids(db, user_id, dept)
        if not visible or ip_record.id not in visible:
            raise PortalError(
                message="Record not found",
                error_code="NOT_FOUND",
                status_code=404,
            )

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
    _contributor_name: dict[str, str | None] = {}
    _contributor_active: dict[str, bool] = {}
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
            _contributor_name[_u.id] = _u.full_name
            # Bug 8: the UI must hide "Send Association Request" for
            # deactivated faculty (backend still enforces on create).
            _contributor_active[_u.id] = bool(_u.is_active)

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
        "filing_date": api_date_only(ip_record.filing_date),
        "registration_date": (
            ip_record.registration_date.isoformat()
            if ip_record.registration_date
            else None
        ),
        "grant_date": api_date_only(ip_record.grant_date),
        "certificate_date": api_date_only(ip_record.certificate_date),
        "published_date": api_date_only(ip_record.published_date or getattr(ip_record, "publication_date", None)),
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
                "faculty_name": _contributor_name.get(
                    c.user_id
                )
                if c.user_id
                else None,
                "is_active": (
                    _contributor_active.get(c.user_id, True)
                    if c.user_id
                    else None
                ),
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
                if record.master_ip_id:
                    master_rec = (await db.execute(select(MasterIpRecord).where(MasterIpRecord.id == record.master_ip_id))).scalar_one_or_none()
                    if master_rec:
                        master_rec.filing_date = parsed
            except Exception:
                pass

        elif (
            field in (
                "grant_date",
                "published_date",
                "publication_date",
                "filing_date",
            )
            and isinstance(value, str)
            and value
        ):
            try:
                from app.services.extraction import normalize_date

                parsed_d = normalize_date(value)
                dt_val = (
                    datetime.combine(parsed_d, datetime.min.time())
                    if parsed_d
                    else None
                )
                if field in ("published_date", "publication_date"):
                    record.published_date = dt_val
                    record.publication_date = dt_val
                    if record.master_ip_id:
                        master_rec = (
                            await db.execute(
                                select(MasterIpRecord).where(
                                    MasterIpRecord.id == record.master_ip_id
                                )
                            )
                        ).scalar_one_or_none()
                        if master_rec:
                            master_rec.publication_date = dt_val
                elif field == "filing_date":
                    record.filing_date = dt_val
                    if record.master_ip_id:
                        master_rec = (
                            await db.execute(
                                select(MasterIpRecord).where(
                                    MasterIpRecord.id == record.master_ip_id
                                )
                            )
                        ).scalar_one_or_none()
                        if master_rec:
                            master_rec.filing_date = dt_val
                elif field == "grant_date":
                    record.grant_date = parsed_d
                    if record.master_ip_id:
                        master_rec = (
                            await db.execute(
                                select(MasterIpRecord).where(
                                    MasterIpRecord.id == record.master_ip_id
                                )
                            )
                        ).scalar_one_or_none()
                        if master_rec:
                            master_rec.grant_date = parsed_d
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
    "/{record_id}/contributors/{contributor_id}/review",
    status_code=status.HTTP_200_OK,
)
async def review_contributor_identity(
    request: Request,
    record_id: str,
    contributor_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Review and confirm or reject an unconfirmed contributor identity.

    Authorized roles:
    - Record uploader
    - Department HOD (HOD of the record's department)
    - Super Admin

    Actions:
    - confirm: sets match_status=CONFIRMED_INTERNAL, contributor_type=INTERNAL_FACULTY,
      is_external=False, and idempotently generates an AssociationRequest for the
      faculty candidate if not uploader.
    - reject: sets match_status=CONFIRMED_EXTERNAL, contributor_type=EXTERNAL,
      is_external=True, user_id=None.
    """
    actor_id = current_user.get("id")
    actor_role = current_user.get("role", "")
    actor_dept = current_user.get("department_id")

    record = (
        await db.execute(select(IpRecord).where(IpRecord.id == record_id))
    ).scalar_one_or_none()
    if not record:
        raise NotFoundError("IP record", record_id)

    # Authorization check
    is_uploader = bool(actor_id and record.uploader_id == actor_id)
    is_admin = (actor_role == "super_admin")
    is_hod = bool(actor_role == "hod_admin" and actor_dept and actor_dept == record.department_id)

    if not (is_uploader or is_admin or is_hod):
        raise AuthorizationError(
            "Only the record uploader, department HOD, or Super Admin may review contributor identity"
        )

    # FIX 3: Lock review after verification
    # Reject identity-review mutation with HTTP 409 Conflict if record is already in VERIFIED state
    is_verified_state = (
        record.workflow_state in ("VERIFIED", "GRANTED")
        or record.verification_status == "VERIFIED"
    )
    if is_verified_state:
        raise PortalError(
            message="Cannot review contributor identity for a record that has already completed verification",
            error_code="RECORD_ALREADY_VERIFIED",
            status_code=409,
        )

    contributor = (
        await db.execute(
            select(IpContributor).where(
                IpContributor.id == contributor_id,
                IpContributor.ip_record_id == record.id,
            )
        )
    ).scalar_one_or_none()
    if not contributor:
        raise NotFoundError("Contributor", contributor_id)

    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    action = str(body.get("action", "confirm")).lower().strip()
    target_faculty_id = body.get("faculty_id") or body.get("user_id") or contributor.user_id
    notes = body.get("notes") or body.get("resolution_notes")

    if action not in ("confirm", "reject"):
        raise PortalError(
            message="action must be 'confirm' or 'reject'",
            error_code="VALIDATION_ERROR",
            status_code=422,
        )

    master_contrib = None
    if record.master_ip_id:
        master_contrib = (
            await db.execute(
                select(MasterIpContributor).where(
                    MasterIpContributor.master_ip_id == record.master_ip_id,
                    func.lower(MasterIpContributor.name) == contributor.name.lower(),
                )
            )
        ).scalar_one_or_none()

    if action == "confirm":
        # Contributor name must not be empty or malformed
        raw_contrib_name = (contributor.name or "").strip()
        norm_contrib_name = normalize_name(raw_contrib_name)
        if not raw_contrib_name or not norm_contrib_name:
            raise PortalError(
                message="Contributor name is empty or invalid for identity confirmation",
                error_code="INVALID_CONTRIBUTOR_NAME",
                status_code=422,
            )

        if not target_faculty_id:
            raise PortalError(
                message="A target faculty candidate must be specified to confirm identity",
                error_code="VALIDATION_ERROR",
                status_code=422,
            )

        target_user = (
            await db.execute(
                select(User).where(
                    or_(
                        User.id == target_faculty_id,
                        User.faculty_id == target_faculty_id,
                    )
                )
            )
        ).scalar_one_or_none()

        if not target_user or not target_user.is_active:
            raise PortalError(
                message="Target faculty member not found or is inactive",
                error_code="VALIDATION_ERROR",
                status_code=422,
            )

        if target_user.role == "hod_admin":
            raise PortalError(
                message="HOD accounts cannot be associated as faculty contributors",
                error_code="VALIDATION_ERROR",
                status_code=422,
            )

        raw_target_name = (target_user.full_name or "").strip()
        norm_target_name = normalize_name(raw_target_name)
        if not raw_target_name or not norm_target_name:
            raise PortalError(
                message="Target user does not have a valid name registered for identity association",
                error_code="INVALID_TARGET_USER_NAME",
                status_code=422,
            )

        # Name plausibility validation (FIX 2)
        # Conservative threshold: similarity >= 0.40 (matches _IDENTITY_INTERNAL_THRESHOLD)
        # If below 0.40, require explicit review notes (minimum 10 characters) explaining the identity association
        similarity = calculate_name_similarity(raw_contrib_name, raw_target_name)
        if similarity < 0.40:
            if not notes or len(str(notes).strip()) < 10:
                raise PortalError(
                    message=(
                        f"Candidate '{target_user.full_name}' is not plausible for contributor '{contributor.name}' "
                        f"(similarity {similarity:.2f} < 0.40). For legitimate alternate names, explicit review notes "
                        f"(minimum 10 characters) explaining the identity association are required."
                    ),
                    error_code="IMPLAUSIBLE_CANDIDATE",
                    status_code=422,
                )

        # Update contributor (FIX 1: mark source as HUMAN_REVIEW)
        contributor.user_id = target_user.id
        contributor.contributor_type = "INTERNAL_FACULTY"
        contributor.match_status = "CONFIRMED_INTERNAL"
        contributor.is_external = False
        contributor.source = "HUMAN_REVIEW"

        if master_contrib:
            master_contrib.matched_faculty_id = target_user.id
            master_contrib.contributor_type = "INTERNAL_FACULTY"
            master_contrib.match_status = "CONFIRMED_INTERNAL"
            master_contrib.match_status = "CONFIRMED_INTERNAL"

        # Generate association request if target is not the uploader (uploader is auto-accepted)
        assoc_created = False
        if target_user.id != record.uploader_id:
            existing_req = (
                await db.execute(
                    select(AssociationRequest).where(
                        AssociationRequest.ip_record_id == record.id,
                        or_(
                            AssociationRequest.target_faculty_id == target_user.id,
                            AssociationRequest.recipient_id == target_user.id,
                        ),
                        AssociationRequest.status.in_((
                            "PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW", "ACCEPTED", "APPROVED"
                        )),
                    ).limit(1)
                )
            ).scalar_one_or_none()

            if not existing_req:
                new_req = AssociationRequest(
                    id=str(uuid.uuid4()),
                    ip_record_id=record.id,
                    master_ip_id=record.master_ip_id,
                    contributor_id=master_contrib.id if master_contrib else None,
                    requesting_faculty_id=record.uploader_id or actor_id,
                    target_faculty_id=target_user.id,
                    requester_id=record.uploader_id or actor_id,
                    recipient_id=target_user.id,
                    reason="Identity confirmed by reviewer: named in patent; explicit acceptance required",
                    status="PENDING",
                )
                db.add(new_req)
                assoc_created = True

        # Check if any unresolved contributors remain
        unresolved_count = (
            await db.execute(
                select(func.count()).select_from(IpContributor).where(
                    IpContributor.ip_record_id == record.id,
                    IpContributor.id != contributor.id,
                    IpContributor.match_status.in_(("PROBABLE_INTERNAL", "AMBIGUOUS_INTERNAL")),
                )
            )
        ).scalar_one()

        if unresolved_count == 0 and record.workflow_state == "IDENTITY_REVIEW":
            from app.services.workflow import WorkflowState, advance_through
            record.workflow_state = advance_through(
                record.workflow_state, WorkflowState.FACULTY_ASSOCIATION_PENDING
            )

        from app.core.logging import log_audit
        log_audit(
            actor=actor_id,
            action="CONTRIBUTOR_IDENTITY_CONFIRMED",
            target_type="ip_contributor",
            target_id=contributor.id,
            status="confirmed",
            after={
                "contributor_id": contributor.id,
                "contributor_name": contributor.name,
                "confirmed_user_id": target_user.id,
                "confirmed_faculty_id": target_user.faculty_id,
                "association_request_created": assoc_created,
                "notes": notes,
                "name_similarity": similarity,
                "source": "HUMAN_REVIEW",
            },
        )
        await db.commit()
        return {
            "status": "success",
            "action": "confirmed",
            "contributor_id": contributor.id,
            "contributor_name": contributor.name,
            "matched_user_id": target_user.id,
            "match_status": contributor.match_status,
            "is_external": contributor.is_external,
            "association_request_created": assoc_created,
            "workflow_state": record.workflow_state,
        }

    else:  # reject
        contributor.user_id = None
        contributor.contributor_type = "EXTERNAL"
        contributor.match_status = "CONFIRMED_EXTERNAL"
        contributor.is_external = True
        contributor.source = "HUMAN_REVIEW"

        if master_contrib:
            master_contrib.matched_faculty_id = None
            master_contrib.contributor_type = "EXTERNAL"
            master_contrib.match_status = "CONFIRMED_EXTERNAL"

        # Check if any unresolved contributors remain
        unresolved_count = (
            await db.execute(
                select(func.count()).select_from(IpContributor).where(
                    IpContributor.ip_record_id == record.id,
                    IpContributor.id != contributor.id,
                    IpContributor.match_status.in_(("PROBABLE_INTERNAL", "AMBIGUOUS_INTERNAL")),
                )
            )
        ).scalar_one()

        if unresolved_count == 0 and record.workflow_state == "IDENTITY_REVIEW":
            from app.services.workflow import WorkflowState, advance_through
            other_internal = (
                await db.execute(
                    select(IpContributor.user_id).where(
                        IpContributor.ip_record_id == record.id,
                        IpContributor.id != contributor.id,
                        IpContributor.is_external.is_(False),
                        IpContributor.user_id.is_not(None),
                        IpContributor.user_id != record.uploader_id,
                        IpContributor.match_status.in_(("CONFIRMED", "CONFIRMED_INTERNAL", "ACCEPTED", "APPROVED")),
                    )
                )
            ).scalars().all()

            if other_internal:
                record.workflow_state = advance_through(
                    record.workflow_state, WorkflowState.FACULTY_ASSOCIATION_PENDING
                )
            else:
                identifier = record.patent_number or record.application_number or record.design_number or record.serial_number
                if identifier:
                    record.workflow_state = advance_through(
                        record.workflow_state, WorkflowState.FACULTY_ASSOCIATION_COMPLETE
                    )
                    record.verification_status = "VERIFIED"
                else:
                    record.workflow_state = advance_through(
                        record.workflow_state, WorkflowState.FACULTY_ASSOCIATION_PENDING
                    )

        from app.core.logging import log_audit
        log_audit(
            actor=actor_id,
            action="CONTRIBUTOR_IDENTITY_REJECTED",
            target_type="ip_contributor",
            target_id=contributor.id,
            status="rejected",
            after={
                "contributor_id": contributor.id,
                "contributor_name": contributor.name,
                "notes": notes,
                "source": "HUMAN_REVIEW",
            },
        )
        await db.commit()
        return {
            "status": "success",
            "action": "rejected",
            "contributor_id": contributor.id,
            "contributor_name": contributor.name,
            "match_status": contributor.match_status,
            "is_external": contributor.is_external,
            "workflow_state": record.workflow_state,
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

    # BUG 5: deactivated accounts cannot initiate new workflow actions.
    _requester = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if _requester is None or not _requester.is_active:
        raise PortalError(
            message="Deactivated accounts cannot send association requests",
            error_code="AUTHORIZATION_ERROR",
            status_code=403,
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

    # Bug 8: deactivated faculty must never receive association requests.
    if not other_user.is_active:
        raise PortalError(
            message=(
                "Association requests cannot be sent "
                "to deactivated faculty"
            ),
            error_code="VALIDATION_ERROR",
            status_code=422,
        )

    # Authoritative rule (B/D): only the record's uploader (or a super admin)
    # may initiate association requests, addressed to OTHER internal faculty
    # only. HOD accounts are never association recipients (read-only HODs).
    if user_id != ip_record.uploader_id and user_role != "super_admin":
        raise PortalError(
            message="Only the uploader may send association requests",
            error_code="AUTHORIZATION_ERROR",
            status_code=403,
        )
    if other_user.role == "hod_admin":
        raise PortalError(
            message="HOD accounts cannot receive association requests",
            error_code="VALIDATION_ERROR",
            status_code=422,
        )

    # Staged workflow: faculty-stage requests stay blocked while the HOD
    # association for the record is still pending. Requests addressed to
    # an HOD are HOD-stage and are never blocked by this rule.
    if other_user.role != "hod_admin":
        from app.api.associations import _live_hod_request

        pending_hod = await _live_hod_request(
            db, record_id, ip_record.master_ip_id
        )
        if pending_hod is not None:
            raise PortalError(
                message="HOD association acceptance is required before faculty association requests",
                error_code="HOD_ASSOCIATION_PENDING",
                status_code=409,
            )

    # Create association request (secondary path mirrors the primary
    # POST /associations/ contract exactly):
    #  - self-association is rejected (400, same message/code as primary),
    #  - a live request for the same record+pair is rejected (409, same
    #    message/code as primary) instead of inserting a duplicate row.
    if other_user.id == user_id:
        raise PortalError(
            message="Self-association is not allowed",
            error_code="VALIDATION_ERROR",
            status_code=400,
        )
    from app.models.base import AssociationRequest

    duplicate = (
        await db.execute(
            select(AssociationRequest).where(
                AssociationRequest.ip_record_id == record_id,
                or_(
                    AssociationRequest.requesting_faculty_id == user_id,
                    AssociationRequest.requester_id == user_id,
                ),
                or_(
                    AssociationRequest.target_faculty_id == other_user.id,
                    AssociationRequest.recipient_id == other_user.id,
                ),
                AssociationRequest.status.in_(
                    ["PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW", "ACCEPTED", "APPROVED"]
                ),
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise PortalError(
            message=f"Association request already {duplicate.status} for this record and faculty",
            error_code="VALIDATION_ERROR",
            status_code=409,
        )

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
    # A9 backstop: same race contract as the primary endpoint. On a live-pair
    # conflict the message mirrors this endpoint's app-level duplicate 409
    # (including the live status); any other integrity error propagates.
    from sqlalchemy.exc import IntegrityError

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        from app.api.associations import _is_live_pair_conflict

        if not _is_live_pair_conflict(exc):
            raise
        live_status = (
            await db.execute(
                select(AssociationRequest.status).where(
                    AssociationRequest.ip_record_id == record_id,
                    or_(
                        AssociationRequest.requesting_faculty_id == user_id,
                        AssociationRequest.requester_id == user_id,
                    ),
                    or_(
                        AssociationRequest.target_faculty_id == other_user.id,
                        AssociationRequest.recipient_id == other_user.id,
                    ),
                    AssociationRequest.status.in_(
                        ["PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW", "ACCEPTED", "APPROVED"]
                    ),
                ).limit(1)
            )
        ).scalar_one_or_none() or "PENDING"
        raise PortalError(
            message=f"Association request already {live_status} for this record and faculty",
            error_code="VALIDATION_ERROR",
            status_code=409,
        ) from exc

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
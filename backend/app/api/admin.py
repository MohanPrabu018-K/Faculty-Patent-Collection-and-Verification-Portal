from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, inspect as sa_inspect, or_, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_super_admin
from app.core.database import get_async_session
from app.core.exceptions import NotFoundError, PortalError
from app.core.logging import log_audit
from app.models.base import (
    ASSOCIATION_STATUS_CHOICES,
    IP_TYPE_CHOICES,
    PROCESSING_STATUS_CHOICES,
    VERIFICATION_STATUS_CHOICES,
    AssociationRequest,
    ConflictCase,
    Department,
    Designation,
    DuplicateCase,
    IpContributor,
    IpRecord,
    MasterIpContributor,
    MasterIpRecord,
    Notification,
    ProcessingJob,
    User,
    VerificationAttempt,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_super_admin)])


def _page_slice(page: int, per_page: int) -> tuple[int, int]:
    offset = (page - 1) * per_page
    return offset, per_page


def _validate_enum_filter(field_name: str, value: str | None, choices: tuple[str, ...]) -> None:
    """Reject unknown PG-enum filter values with 422.

    Comparing a raw string against a Postgres ENUM column raises
    InvalidTextRepresentationError (surfaced as 500 INTERNAL_ERROR).
    GRANTED, for example, is a workflow_state — not a verification_status —
    so ?verification_status=GRANTED must fail cleanly instead of 500ing.
    """
    if value is not None and value not in choices:
        raise PortalError(
            message=f"Unknown {field_name} filter: {value}",
            error_code="VALIDATION_ERROR",
            status_code=422,
        )


_SENSITIVE_COLUMNS = {"password_hash"}


def _model_to_dict(obj, exclude: set[str] | None = None) -> dict:
    """Flatten one ORM instance into a flat JSON-serializable dict of its mapped
    columns.

    ``select(Model)`` + ``.mappings()`` yields ``{"Model": <instance>}`` rows, so
    the previous ``dict(row)`` produced nested ``{"Model": {...}}`` payloads. This
    returns the columns directly and drops sensitive fields.
    """
    if obj is None:
        return {}
    skip = _SENSITIVE_COLUMNS | (exclude or set())
    out: dict = {}
    for attr in sa_inspect(obj).mapper.column_attrs:
        if attr.key in skip:
            continue
        value = getattr(obj, attr.key)
        out[attr.key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


async def _serialize_count(session: AsyncSession, query):
    result = await session.execute(query)
    return result.scalar_one()


def _parse_datetime(value):
    """Parse an ISO-8601 date/datetime string, returning None for empty values."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


@router.get("/dashboard", status_code=status.HTTP_200_OK)
async def get_admin_dashboard(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    # Consolidate user counts into two parallel queries instead of 4 sequential ones.
    user_q = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(User.role == "faculty").label("faculty_count"),
            func.count().filter(User.role == "hod_admin").label("hod_count"),
            func.count().filter(User.is_active.is_(True)).label("active"),
        ).select_from(User).where(User.role.in_(["faculty", "hod_admin"]))
    )
    ur = user_q.one()

    # Consolidate IP record counts into a single query instead of 5 sequential ones.
    ip_q = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(IpRecord.ip_type == "PATENT").label("patents"),
            func.count().filter(IpRecord.ip_type == "DESIGN_REGISTRATION").label("designs"),
            func.count().filter(IpRecord.processing_status == "PENDING").label("pending"),
            func.count().filter(IpRecord.verification_status == "VERIFIED").label("verified"),
            func.count().filter(func.date_trunc("month", IpRecord.created_at) == func.date_trunc("month", func.now())).label("uploads_this_month"),
        ).select_from(IpRecord)
    )
    ir = ip_q.one()

    # Remaining single-table counts (fast, one round-trip each but negligible individually).
    # Pending verifications = every non-terminal automated state (UNVERIFIED +
    # VERIFICATION_REQUIRED). Counting UNVERIFIED alone undercounts because the
    # pipeline persists NEEDS_REVIEW/NOT_FOUND/ERROR outcomes as
    # VERIFICATION_REQUIRED (see _enum_safe_verification_status).
    pending_verifications, open_conflicts, pending_duplicates, pending_associations = await asyncio.gather(
        _serialize_count(db, select(func.count()).select_from(VerificationAttempt).where(VerificationAttempt.status.in_(["UNVERIFIED", "VERIFICATION_REQUIRED"]))),
        _serialize_count(db, select(func.count()).select_from(ConflictCase).where(ConflictCase.status == "OPEN")),
        _serialize_count(db, select(func.count()).select_from(DuplicateCase).where(DuplicateCase.status == "OPEN")),
        _serialize_count(db, select(func.count()).select_from(AssociationRequest).where(AssociationRequest.status == "PENDING")),
    )

    recent = await db.execute(
        select(IpRecord.id, IpRecord.title, IpRecord.ip_type, IpRecord.processing_status, IpRecord.created_at)
        .order_by(IpRecord.created_at.desc())
        .limit(10)
    )

    return {
        "kpis": {
            "total_faculty": ur.faculty_count,
            "total_hods": ur.hod_count,
            "total_faculty_all": ur.total,
            "active_faculty": ur.active,
            "total_ip_records": ir.total,
            "total_patents": ir.patents,
            "total_designs": ir.designs,
            "pending_records": ir.pending,
            "verified_records": ir.verified,
            "pending_verifications": pending_verifications,
            "open_conflicts": open_conflicts,
            "pending_duplicates": pending_duplicates,
            "pending_associations": pending_associations,
            "uploads_this_month": ir.uploads_this_month,
        },
        "recent_activity": [dict(row._mapping) for row in recent.all()],
    }


@router.get("/dashboard/activity", status_code=status.HTTP_200_OK)
async def get_recent_activity(current_user: dict = Depends(get_current_user), limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_async_session)):
    rows = await db.execute(select(Notification).order_by(Notification.created_at.desc()).limit(limit))
    return {"activities": [_model_to_dict(row) for row in rows.scalars().all()], "count": limit}


@router.get("/queues/verifications", status_code=status.HTTP_200_OK)
async def get_verification_queue(current_user: dict = Depends(get_current_user), status: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    query = select(VerificationAttempt).order_by(VerificationAttempt.created_at.desc())
    count_query = select(func.count()).select_from(VerificationAttempt)
    if status:
        query = query.where(VerificationAttempt.status == status)
        count_query = count_query.where(VerificationAttempt.status == status)
    total = await _serialize_count(db, count_query)
    result = await db.execute(query.offset(offset).limit(limit))
    return {"verifications": [_model_to_dict(r) for r in result.scalars().all()], "total": total, "page": page, "per_page": per_page}


@router.get("/queues/conflicts", status_code=status.HTTP_200_OK)
async def get_conflict_queue(current_user: dict = Depends(get_current_user), conflict_type: str | None = Query(None), priority: str | None = Query(None), status: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    query = select(ConflictCase).order_by(ConflictCase.created_at.desc())
    count_query = select(func.count()).select_from(ConflictCase)
    if conflict_type:
        query = query.where(ConflictCase.conflict_type == conflict_type)
        count_query = count_query.where(ConflictCase.conflict_type == conflict_type)
    if status:
        query = query.where(ConflictCase.status == status)
        count_query = count_query.where(ConflictCase.status == status)
    total = await _serialize_count(db, count_query)
    result = await db.execute(query.offset(offset).limit(limit))
    return {"conflicts": [_model_to_dict(r) for r in result.scalars().all()], "total": total, "page": page, "per_page": per_page}


@router.get("/queues/associations", status_code=status.HTTP_200_OK)
async def get_association_queue(current_user: dict = Depends(get_current_user), status: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    query = select(AssociationRequest).order_by(AssociationRequest.created_at.desc())
    count_query = select(func.count()).select_from(AssociationRequest)
    if status:
        query = query.where(AssociationRequest.status == status)
        count_query = count_query.where(AssociationRequest.status == status)
    total = await _serialize_count(db, count_query)
    result = await db.execute(query.offset(offset).limit(limit))
    return {"associations": [_model_to_dict(r) for r in result.scalars().all()], "total": total, "page": page, "per_page": per_page}


@router.get("/faculty", status_code=status.HTTP_200_OK)
async def list_faculty(current_user: dict = Depends(get_current_user), search: str | None = Query(None), department_id: str | None = Query(None), designation_id: str | None = Query(None), is_active: bool | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    query = select(User).where(User.role.in_(["faculty", "hod_admin"]))
    count_query = select(func.count()).select_from(User).where(User.role.in_(["faculty", "hod_admin"]))
    if search:
        like = f"%{search}%"
        query = query.where(or_(User.full_name.ilike(like), User.email.ilike(like), User.faculty_id.ilike(like)))
        count_query = count_query.where(or_(User.full_name.ilike(like), User.email.ilike(like), User.faculty_id.ilike(like)))
    if is_active is not None:
        query = query.where(User.is_active.is_(is_active))
        count_query = count_query.where(User.is_active.is_(is_active))
    if department_id:
        query = query.where(User.department_id == department_id)
        count_query = count_query.where(User.department_id == department_id)
    if designation_id:
        query = query.where(User.designation_id == designation_id)
        count_query = count_query.where(User.designation_id == designation_id)
    total = await _serialize_count(db, count_query)
    rows = (await db.execute(query.order_by(User.created_at.desc()).offset(offset).limit(limit))).scalars().all()

    dept_map = {d.id: d.name for d in (await db.execute(select(Department))).scalars().all()}
    desig_map = {d.id: (d.name or d.title) for d in (await db.execute(select(Designation))).scalars().all()}

    # Batch-fetch per-faculty IP counts in a single GROUP BY query
    # instead of N×4 individual COUNT queries (N+1 optimization).
    user_ids = [u.id for u in rows]
    counts_map: dict[str, dict[str, int]] = {}
    if user_ids:
        count_q = (
            select(
                IpRecord.uploader_id,
                func.count().label("documents"),
                func.count().filter(IpRecord.ip_type == "PATENT").label("patents"),
                func.count().filter(IpRecord.ip_type == "DESIGN_REGISTRATION").label("designs"),
                func.count().filter(IpRecord.verification_status == "VERIFIED").label("verified"),
            )
            .where(IpRecord.uploader_id.in_(user_ids))
            .group_by(IpRecord.uploader_id)
        )
        for row_cnt in (await db.execute(count_q)).all():
            uid = row_cnt.uploader_id
            counts_map[uid] = {
                "documents": row_cnt.documents,
                "patents": row_cnt.patents,
                "designs": row_cnt.designs,
                "verified": row_cnt.verified,
            }

    empty_counts = {"documents": 0, "patents": 0, "designs": 0, "verified": 0}
    faculty = []
    for u in rows:
        row = _model_to_dict(u)
        row["department_name"] = dept_map.get(u.department_id)
        row["designation_name"] = desig_map.get(u.designation_id)
        row["counts"] = counts_map.get(u.id, empty_counts)
        faculty.append(row)

    return {"faculty": faculty, "total": total, "page": page, "per_page": per_page}


@router.post("/faculty", status_code=status.HTTP_201_CREATED)
async def create_faculty(request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    from app.core.security import generate_temporary_password, hash_password

    if "email" not in body or "full_name" not in body:
        raise PortalError(message="email and full_name are required", error_code="VALIDATION_ERROR", status_code=422)

    password = body.get("password") or body.get("temporary_password")
    if body.get("password_hash") not in (None, ""):
        password_hash = body["password_hash"]
        temporary_password = None
    elif password:
        password_hash = hash_password(password)
        temporary_password = None
    else:
        temporary_password = generate_temporary_password()
        password_hash = hash_password(temporary_password)

    # Determine role from designation: HOD designation -> hod_admin, else faculty
    designation_id = body.get("designation_id")
    role = "faculty"
    if designation_id:
        desig_row = (await db.execute(select(Designation).where(Designation.id == designation_id))).scalar_one_or_none()
        if desig_row and (desig_row.title or "").strip().upper() == "HOD":
            role = "hod_admin"

    user = User(
        id=str(uuid.uuid4()),
        email=body["email"],
        official_email=body.get("official_email", body["email"]),
        password_hash=password_hash,
        full_name=body["full_name"],
        role=role,
        faculty_id=body.get("faculty_id") or str(uuid.uuid4()),
        department_id=body.get("department_id"),
        designation_id=designation_id,
        joining_date=_parse_datetime(body.get("joining_date")),
        status=body.get("status", "active"),
        is_active=body.get("is_active", True),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log_audit(actor=current_user.get("id"), action="FACULTY_CREATED", target_type="user", target_id=user.id, status="success", after={"email": user.email, "faculty_id": user.faculty_id})
    response_payload: dict = {"id": user.id, "email": user.email, "faculty_id": user.faculty_id, "message": "Faculty created"}
    if temporary_password is not None:
        response_payload["temporary_password"] = temporary_password
        response_payload["temporary_password_generated"] = True
    return response_payload


@router.get("/faculty/{faculty_id}", status_code=status.HTTP_200_OK)
async def get_faculty(faculty_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(
        select(User, Department.name, Designation.name)
        .outerjoin(Department, User.department_id == Department.id)
        .outerjoin(Designation, User.designation_id == Designation.id)
        .where(User.id == faculty_id, User.role.in_(["faculty", "hod_admin"]))
    )
    row = result.first()
    if not row:
        raise NotFoundError("Faculty", faculty_id)
    user, dept_name, desig_name = row
    return {
        "id": user.id,
        "email": user.email,
        "official_email": user.official_email,
        "full_name": user.full_name,
        "role": user.role,
        "faculty_id": user.faculty_id,
        "department_id": user.department_id,
        "department_name": dept_name,
        "designation_id": user.designation_id,
        "designation_name": desig_name,
        "joining_date": user.joining_date.isoformat() if user.joining_date else None,
        "status": user.status,
        "is_active": user.is_active,
    }


@router.patch("/faculty/{faculty_id}", status_code=status.HTTP_200_OK)
async def update_faculty(faculty_id: str, request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    result = await db.execute(select(User).where(User.id == faculty_id, User.role.in_(["faculty", "hod_admin"])))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("Faculty", faculty_id)
    before = {"email": user.email, "full_name": user.full_name, "is_active": user.is_active, "department_id": user.department_id, "designation_id": user.designation_id, "role": user.role}
    for field in ("email", "official_email", "full_name", "faculty_id", "is_active", "department_id", "designation_id", "status"):
        if field in body:
            setattr(user, field, body[field])
    if "joining_date" in body:
        user.joining_date = _parse_datetime(body.get("joining_date"))
    # Sync role to designation if designation changed
    if "designation_id" in body:
        desig = (await db.execute(select(Designation).where(Designation.id == user.designation_id))).scalar_one_or_none() if user.designation_id else None
        if desig and (desig.title or "").strip().upper() == "HOD":
            user.role = "hod_admin"
        elif desig and (desig.title or "").strip().upper() == "FACULTY":
            user.role = "faculty"
    await db.commit()
    log_audit(actor=current_user.get("id"), action="FACULTY_UPDATED", target_type="user", target_id=user.id, status="success", before=before, after={"full_name": user.full_name, "department_id": user.department_id, "designation_id": user.designation_id, "is_active": user.is_active, "role": user.role})
    return {"id": user.id, "message": "Faculty updated", "before": before}


@router.post("/faculty/{faculty_id}/activate", status_code=status.HTTP_200_OK)
async def activate_faculty(faculty_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    await db.execute(update(User).where(User.id == faculty_id, User.role.in_(["faculty", "hod_admin"])).values(is_active=True, status="active"))
    await db.commit()
    log_audit(actor=current_user.get("id"), action="FACULTY_ACTIVATED", target_type="user", target_id=faculty_id, status="success")
    return {"id": faculty_id, "status": "active"}


@router.post("/faculty/{faculty_id}/deactivate", status_code=status.HTTP_200_OK)
async def deactivate_faculty(faculty_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    await db.execute(update(User).where(User.id == faculty_id, User.role.in_(["faculty", "hod_admin"])).values(is_active=False, status="inactive"))
    await db.commit()
    log_audit(actor=current_user.get("id"), action="FACULTY_DEACTIVATED", target_type="user", target_id=faculty_id, status="success")
    return {"id": faculty_id, "status": "inactive"}


@router.post("/faculty/{faculty_id}/reset-credentials", status_code=status.HTTP_200_OK)
async def reset_faculty_credentials(faculty_id: str, request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    new_password = body.get("password") or str(uuid.uuid4())
    from app.core.security import hash_password
    result = await db.execute(select(User).where(User.id == faculty_id, User.role.in_(["faculty", "hod_admin"])))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("Faculty", faculty_id)
    user.password_hash = hash_password(new_password)
    await db.commit()
    log_audit(actor=current_user.get("id"), action="FACULTY_CREDENTIAL_RESET", target_type="user", target_id=faculty_id, status="success", extra={"temporary_password_provided": bool(body.get("password"))})
    return {"id": faculty_id, "message": "Credentials reset", "temporary_password": new_password if body.get("password") else None}


@router.get("/departments", status_code=status.HTTP_200_OK)
async def list_departments(current_user: dict = Depends(get_current_user), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    total = await _serialize_count(db, select(func.count()).select_from(Department))
    rows = await db.execute(select(Department).order_by(Department.name).offset(offset).limit(limit))
    return {"departments": [_model_to_dict(r) for r in rows.scalars().all()], "total": total, "page": page, "per_page": per_page}


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    dept = Department(id=str(uuid.uuid4()), name=body["name"], code=body.get("code"), is_active=body.get("is_active", True))
    db.add(dept)
    await db.commit()
    return {"id": dept.id, "name": dept.name}


@router.patch("/departments/{dept_id}", status_code=status.HTTP_200_OK)
async def update_department(dept_id: str, request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    result = await db.execute(select(Department).where(Department.id == dept_id))
    dept = result.scalar_one_or_none()
    if not dept:
        raise NotFoundError("Department", dept_id)
    for field in ("name", "code", "is_active"):
        if field in body:
            setattr(dept, field, body[field])
    await db.commit()
    return {"id": dept.id, "name": dept.name}


@router.delete("/departments/{dept_id}", status_code=status.HTTP_200_OK)
async def delete_department(dept_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    await db.execute(delete(Department).where(Department.id == dept_id))
    await db.commit()
    return {"id": dept_id, "deleted": True}


@router.get("/designations", status_code=status.HTTP_200_OK)
async def list_designations(current_user: dict = Depends(get_current_user), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    total = await _serialize_count(db, select(func.count()).select_from(Designation))
    rows = await db.execute(select(Designation).order_by(Designation.title).offset(offset).limit(limit))
    return {"designations": [_model_to_dict(r) for r in rows.scalars().all()], "total": total, "page": page, "per_page": per_page}


@router.post("/designations", status_code=status.HTTP_201_CREATED)
async def create_designation(request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    desg = Designation(id=str(uuid.uuid4()), title=body["title"], level=body.get("level"), is_active=body.get("is_active", True))
    db.add(desg)
    await db.commit()
    return {"id": desg.id, "title": desg.title}


@router.patch("/designations/{desg_id}", status_code=status.HTTP_200_OK)
async def update_designation(desg_id: str, request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    result = await db.execute(select(Designation).where(Designation.id == desg_id))
    desg = result.scalar_one_or_none()
    if not desg:
        raise NotFoundError("Designation", desg_id)
    for field in ("title", "level", "is_active"):
        if field in body:
            setattr(desg, field, body[field])
    await db.commit()
    return {"id": desg.id, "title": desg.title}


@router.delete("/designations/{desg_id}", status_code=status.HTTP_200_OK)
async def delete_designation(desg_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    await db.execute(delete(Designation).where(Designation.id == desg_id))
    await db.commit()
    return {"id": desg_id, "deleted": True}


@router.get("/settings", status_code=status.HTTP_200_OK)
async def admin_settings(current_user: dict = Depends(get_current_user)):
    """Read-only view of the portal's operational configuration.

    Secrets (DB URL, JWT secret, OCR.Space API key) are never returned — only
    whether a capability is enabled and how it is configured.
    """
    from app.core.config import (
        app_settings,
        local_ocr_settings,
        ocr_space_settings,
        upload_settings,
        verification_settings,
    )
    from app.services.ocr_pipeline import _resolve_tesseract_cmd

    tesseract_path = _resolve_tesseract_cmd()
    ocrspace_configured = bool(ocr_space_settings.api_key)

    return {
        "editable": True,
        "editable_fields": ["max_upload_mb"],
        "application": {
            "name": app_settings.app_name if hasattr(app_settings, "app_name") else "Faculty Patent Portal",
            "environment": getattr(app_settings, "app_env", "development"),
            "debug": getattr(app_settings, "debug", False),
            "api_prefix": getattr(app_settings, "api_prefix", "/api"),
        },
        "ocr": {
            "engine": "tesseract" if tesseract_path else "none",
            "status": "ENABLED" if tesseract_path else "DISABLED",
            "tesseract_available": bool(tesseract_path),
            "tesseract_langs": local_ocr_settings.tesseract_langs,
            "embedded_text_extraction": "ENABLED",
            "external_fallback": {
                "provider": "OCR.Space",
                "status": "ENABLED" if (local_ocr_settings.ocrspace_fallback_enabled and ocrspace_configured) else "DISABLED",
                "required": False,
                "note": "Optional emergency fallback only; local OCR is authoritative.",
            },
        },
        "qr": {
            "status": "ENABLED",
            "engines": ["pyzbar/libzbar", "OpenCV QRCodeDetector"],
        },
        "verification": {
            "ip_india": {
                "status": "ENABLED" if getattr(verification_settings, "ipindia_enabled", False) else "MANUAL VERIFICATION",
                "note": "No reliable free InPASS automation; records fall back to manual verification.",
            },
            "default_country": getattr(verification_settings, "default_country", "IN"),
            "manual_fallback": "ENABLED",
        },
        "uploads": {
            "allowed_extensions": list(getattr(upload_settings, "allowed_extensions", [])),
            "max_upload_mb": __import__("app.core.runtime_settings", fromlist=["get_max_upload_mb"]).get_max_upload_mb(getattr(upload_settings, "max_upload_bytes", 20971520)),
            "max_upload_mb_min": __import__("app.core.runtime_settings", fromlist=["MIN_UPLOAD_MB"]).MIN_UPLOAD_MB,
            "max_upload_mb_max": __import__("app.core.runtime_settings", fromlist=["MAX_UPLOAD_MB"]).MAX_UPLOAD_MB,
            "max_pdf_pages": getattr(upload_settings, "max_pdf_pages", None),
            "storage_backend": getattr(upload_settings, "storage_backend", "local"),
        },
        "session": {
            "jwt_algorithm": getattr(app_settings, "jwt_algorithm", "HS256"),
            "access_token_minutes": getattr(app_settings, "jwt_access_token_minutes", 30),
            "cookie_secure": getattr(app_settings, "cookie_secure", False),
            "cookie_samesite": getattr(app_settings, "cookie_samesite", "lax"),
        },
    }


@router.patch("/settings", status_code=status.HTTP_200_OK)
async def admin_update_settings(request: Request, current_user: dict = Depends(get_current_user)):
    from app.core.runtime_settings import MAX_UPLOAD_MB, MIN_UPLOAD_MB, get_max_upload_mb, set_max_upload_mb
    from app.core.config import upload_settings as _us
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if "max_upload_mb" not in body:
        raise PortalError(message="max_upload_mb is required", error_code="VALIDATION_ERROR", status_code=422)
    try:
        mb = float(body["max_upload_mb"])
    except (TypeError, ValueError):
        raise PortalError(message="max_upload_mb must be a number", error_code="VALIDATION_ERROR", status_code=422)
    if not (MIN_UPLOAD_MB <= mb <= MAX_UPLOAD_MB):
        raise PortalError(message=f"max_upload_mb must be between {MIN_UPLOAD_MB} and {MAX_UPLOAD_MB}", error_code="VALIDATION_ERROR", status_code=422)
    before = get_max_upload_mb(getattr(_us, "max_upload_bytes", 20971520))
    saved = set_max_upload_mb(mb)
    log_audit(actor=current_user.get("id"), action="SETTINGS_UPDATED", target_type="settings", target_id="upload", status="success", before={"max_upload_mb": before}, after={"max_upload_mb": saved})
    return {"max_upload_mb": saved, "message": "Upload limit updated and enforced on new uploads"}


@router.get("/ip-records", status_code=status.HTTP_200_OK)
async def admin_list_ip_records(
    current_user: dict = Depends(get_current_user),
    search: str | None = Query(None, description="search title/numbers/applicant/faculty"),
    ip_type: str | None = Query(None),
    verification_status: str | None = Query(None),
    processing_status: str | None = Query(None),
    workflow_state: str | None = Query(None),
    department_id: str | None = Query(None),
    designation_id: str | None = Query(None),
    faculty_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    contributor_count: int | None = Query(None, ge=1, description="minimum number of contributors on the record"),
    institution: str | None = Query(None, description="record has >=1 contributor from this institution"),
    is_archived: bool | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
):
    offset, limit = _page_slice(page, per_page)
    _validate_enum_filter("ip_type", ip_type, IP_TYPE_CHOICES)
    _validate_enum_filter("verification_status", verification_status, VERIFICATION_STATUS_CHOICES)
    _validate_enum_filter("processing_status", processing_status, PROCESSING_STATUS_CHOICES)
    query = select(IpRecord)
    count_query = select(func.count()).select_from(IpRecord)
    if ip_type:
        query = query.where(IpRecord.ip_type == ip_type)
        count_query = count_query.where(IpRecord.ip_type == ip_type)
    if verification_status:
        query = query.where(IpRecord.verification_status == verification_status)
        count_query = count_query.where(IpRecord.verification_status == verification_status)
    if processing_status:
        query = query.where(IpRecord.processing_status == processing_status)
        count_query = count_query.where(IpRecord.processing_status == processing_status)
    if workflow_state:
        query = query.where(IpRecord.workflow_state == workflow_state)
        count_query = count_query.where(IpRecord.workflow_state == workflow_state)
    if department_id:
        query = query.where(IpRecord.department_id == department_id)
        count_query = count_query.where(IpRecord.department_id == department_id)
    if designation_id:
        query = query.where(IpRecord.designation_id == designation_id)
        count_query = count_query.where(IpRecord.designation_id == designation_id)
    if faculty_id:
        query = query.where(IpRecord.uploader_id == faculty_id)
        count_query = count_query.where(IpRecord.uploader_id == faculty_id)
    if is_archived is not None:
        query = query.where(IpRecord.is_archived.is_(is_archived))
        count_query = count_query.where(IpRecord.is_archived.is_(is_archived))
    if date_from:
        parsed = _parse_datetime(date_from)
        if parsed:
            query = query.where(IpRecord.created_at >= parsed)
            count_query = count_query.where(IpRecord.created_at >= parsed)
    if date_to:
        # Date-only input (YYYY-MM-DD) is treated as inclusive (whole day).
        parsed = _parse_datetime(date_to)
        if parsed:
            if "T" not in str(date_to):
                parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
            query = query.where(IpRecord.created_at <= parsed)
            count_query = count_query.where(IpRecord.created_at <= parsed)
    if contributor_count is not None:
        contrib_subq = (
            select(func.count())
            .select_from(IpContributor)
            .where(IpContributor.ip_record_id == IpRecord.id)
            .correlate(IpRecord)
            .scalar_subquery()
        )
        query = query.where(contrib_subq >= contributor_count)
        count_query = count_query.where(contrib_subq >= contributor_count)
    if institution:
        inst_exists = (
            select(IpContributor.id)
            .where(IpContributor.ip_record_id == IpRecord.id, IpContributor.institution.ilike(f"%{institution}%"))
            .correlate(IpRecord)
            .exists()
        )
        query = query.where(inst_exists)
        count_query = count_query.where(inst_exists)
    if search:
        like = f"%{search}%"
        faculty_match = (
            select(User.id)
            .where(User.id == IpRecord.uploader_id, or_(User.full_name.ilike(like), User.faculty_id.ilike(like), User.email.ilike(like)))
            .correlate(IpRecord)
            .exists()
        )
        search_cond = or_(
            IpRecord.title.ilike(like),
            IpRecord.patent_number.ilike(like),
            IpRecord.application_number.ilike(like),
            IpRecord.design_number.ilike(like),
            IpRecord.serial_number.ilike(like),
            IpRecord.applicant.ilike(like),
            IpRecord.patentee.ilike(like),
            IpRecord.contributor_name.ilike(like),
            faculty_match,
        )
        query = query.where(search_cond)
        count_query = count_query.where(search_cond)
    total = await _serialize_count(db, count_query)
    records = (await db.execute(query.order_by(IpRecord.created_at.desc()).offset(offset).limit(limit))).scalars().all()

    uploader_ids = {r.uploader_id for r in records if r.uploader_id}
    name_map = {}
    if uploader_ids:
        name_map = {
            u.id: (u.full_name, u.faculty_id)
            for u in (await db.execute(select(User).where(User.id.in_(uploader_ids)))).scalars().all()
        }
    dept_map = {d.id: d.name for d in (await db.execute(select(Department))).scalars().all()}

    out = []
    for r in records:
        row = _model_to_dict(r)
        nm = name_map.get(r.uploader_id)
        row["uploader_name"] = nm[0] if nm else None
        row["faculty_name"] = nm[0] if nm else None
        row["faculty_id"] = nm[1] if nm else None
        row["department_name"] = dept_map.get(r.department_id)
        out.append(row)
    return {"records": out, "total": total, "page": page, "per_page": per_page}


@router.get("/ip-records/{record_id}", status_code=status.HTTP_200_OK)
async def admin_get_ip_record(record_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(select(IpRecord).where(IpRecord.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise NotFoundError("IP record", record_id)
    row = _model_to_dict(record)
    if record.uploader_id:
        uploader = (await db.execute(select(User).where(User.id == record.uploader_id))).scalar_one_or_none()
        row["uploader_name"] = uploader.full_name if uploader else None
        row["faculty_name"] = uploader.full_name if uploader else None
        row["faculty_id"] = uploader.faculty_id if uploader else None
    if record.department_id:
        dept = (await db.execute(select(Department).where(Department.id == record.department_id))).scalar_one_or_none()
        row["department_name"] = dept.name if dept else None
    return row


@router.patch("/ip-records/{record_id}", status_code=status.HTTP_200_OK)
async def admin_update_ip_record(record_id: str, request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    result = await db.execute(select(IpRecord).where(IpRecord.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise NotFoundError("IP record", record_id)
    before = {"title": record.title, "verification_status": record.verification_status, "processing_status": record.processing_status, "department_id": record.department_id, "designation_id": record.designation_id, "is_archived": record.is_archived}
    for field in ("title", "verification_status", "processing_status", "department_id", "designation_id", "is_archived"):
        if field in body and body[field] is not None:
            setattr(record, field, body[field])
    await db.commit()
    log_audit(
        actor=current_user.get("id"),
        action="IP_RECORD_ARCHIVED" if record.is_archived else "IP_RECORD_UNARCHIVED",
        target_type="ip_record",
        target_id=record.id,
        status="success",
        before=before,
        after={"is_archived": record.is_archived},
    )
    return {"id": record.id, "message": "IP record updated", "is_archived": record.is_archived}


@router.post("/ip-records/{record_id}/grant", status_code=status.HTTP_200_OK)
async def admin_grant_patent(
    record_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Grant a verified patent. Only Super Admin can grant. Record must be VERIFIED."""
    from app.services.workflow import WorkflowState, can_transition

    result = await db.execute(select(IpRecord).where(IpRecord.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise NotFoundError("IP record", record_id)

    if record.verification_status != "VERIFIED":
        from app.core.exceptions import PortalError
        raise PortalError(
            message="Only verified records can be granted. Current status: " + (record.verification_status or "UNVERIFIED"),
            error_code="GRANT_NOT_ELIGIBLE",
            status_code=422,
        )

    current_state = record.workflow_state or "VERIFIED"
    if not can_transition(current_state, WorkflowState.GRANTED):
        from app.core.exceptions import PortalError
        raise PortalError(
            message="Cannot grant from current workflow state: " + current_state,
            error_code="GRANT_TRANSITION_INVALID",
            status_code=422,
        )

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    body = body if isinstance(body, dict) else {}

    before = {
        "verification_status": record.verification_status,
        "workflow_state": record.workflow_state,
    }

    record.workflow_state = WorkflowState.GRANTED.value
    record.evidence = {**(record.evidence or {}), "granted_at": datetime.utcnow().isoformat(), "granted_by": current_user.get("id")}
    await db.commit()

    log_audit(
        actor=current_user.get("id"),
        action="PATENT_GRANTED",
        target_type="ip_record",
        target_id=record.id,
        status="success",
        before=before,
        after={"workflow_state": record.workflow_state, "verification_status": record.verification_status},
    )

    return {
        "id": record.id,
        "workflow_state": record.workflow_state,
        "verification_status": record.verification_status,
        "message": "Patent granted successfully",
    }


@router.get("/duplicates", status_code=status.HTTP_200_OK)
async def admin_list_duplicates(current_user: dict = Depends(get_current_user), status: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    query = select(DuplicateCase)
    count_query = select(func.count()).select_from(DuplicateCase)
    if status:
        query = query.where(DuplicateCase.status == status)
        count_query = count_query.where(DuplicateCase.status == status)
    total = await _serialize_count(db, count_query)
    rows = await db.execute(query.order_by(DuplicateCase.detected_at.desc()).offset(offset).limit(limit))
    return {"duplicates": [_model_to_dict(r) for r in rows.scalars().all()], "total": total, "page": page, "per_page": per_page}


@router.post("/duplicates/{case_id}/resolve", status_code=status.HTTP_200_OK)
async def admin_resolve_duplicate(case_id: str, request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    result = await db.execute(select(DuplicateCase).where(DuplicateCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise NotFoundError("Duplicate case", case_id)
    case.status = "RESOLVED" if body.get("action") != "dismiss" else "DISMISSED"
    case.kept_record_id = body.get("kept_record_id")
    case.resolution_notes = body.get("notes")
    case.resolved_by = current_user.get("id")
    case.resolved_at = datetime.utcnow()
    await db.commit()
    return {"case_id": case_id, "action": body.get("action"), "kept_record_id": case.kept_record_id}


@router.get("/conflicts", status_code=status.HTTP_200_OK)
async def admin_list_conflicts(current_user: dict = Depends(get_current_user), conflict_type: str | None = Query(None), status: str | None = Query(None), priority: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    query = select(ConflictCase)
    count_query = select(func.count()).select_from(ConflictCase)
    if conflict_type:
        query = query.where(ConflictCase.conflict_type == conflict_type)
        count_query = count_query.where(ConflictCase.conflict_type == conflict_type)
    if status:
        query = query.where(ConflictCase.status == status)
        count_query = count_query.where(ConflictCase.status == status)
    total = await _serialize_count(db, count_query)
    rows = await db.execute(query.order_by(ConflictCase.created_at.desc()).offset(offset).limit(limit))
    return {"conflicts": [_model_to_dict(r) for r in rows.scalars().all()], "total": total, "page": page, "per_page": per_page}


@router.post("/conflicts/{conflict_id}/resolve", status_code=status.HTTP_200_OK)
async def admin_resolve_conflict(conflict_id: str, request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    result = await db.execute(select(ConflictCase).where(ConflictCase.id == conflict_id))
    case = result.scalar_one_or_none()
    if not case:
        raise NotFoundError("Conflict case", conflict_id)
    case.status = "RESOLVED"
    case.resolution_notes = body.get("notes")
    case.resolved_by = current_user.get("id")
    case.resolved_at = datetime.utcnow()
    await db.commit()
    return {"conflict_id": conflict_id, "action": body.get("action")}


@router.post("/conflicts/{conflict_id}/assign", status_code=status.HTTP_200_OK)
async def admin_assign_conflict(conflict_id: str, request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    result = await db.execute(select(ConflictCase).where(ConflictCase.id == conflict_id))
    case = result.scalar_one_or_none()
    if not case:
        raise NotFoundError("Conflict case", conflict_id)
    # Assignment is tracked in assigned_to; resolved_by is reserved for the
    # user who actually resolves the case (see admin_resolve_conflict).
    case.assigned_to = body.get("assigned_to")
    await db.commit()
    return {"conflict_id": conflict_id, "assigned_to": body.get("assigned_to")}


@router.get("/associations", status_code=status.HTTP_200_OK)
async def admin_list_associations(current_user: dict = Depends(get_current_user), status: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    query = select(AssociationRequest)
    count_query = select(func.count()).select_from(AssociationRequest)
    if status:
        query = query.where(AssociationRequest.status == status)
        count_query = count_query.where(AssociationRequest.status == status)
    total = await _serialize_count(db, count_query)
    rows = await db.execute(query.order_by(AssociationRequest.created_at.desc()).offset(offset).limit(limit))
    return {"associations": [_model_to_dict(r) for r in rows.scalars().all()], "total": total, "page": page, "per_page": per_page}


@router.get("/reports/pending-associations", status_code=status.HTTP_200_OK)
async def admin_pending_associations_report(
    current_user: dict = Depends(get_current_user),
    status: str | None = Query(None, description="association status; defaults to PENDING"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
):
    """Enriched pending-association report: faculty ↔ IP record pairs awaiting action.

    Dynamically generated from AssociationRequest rows (never hardcoded):
    each entry carries the relevant faculty/users, the relevant record with
    its identifiers, the association status, and the pending count.
    """
    wanted = status or "PENDING"
    offset, limit = _page_slice(page, per_page)
    base = select(AssociationRequest).where(AssociationRequest.status == wanted)
    total = await _serialize_count(db, select(func.count()).select_from(AssociationRequest).where(AssociationRequest.status == wanted))
    by_status_rows = (await db.execute(select(AssociationRequest.status, func.count()).group_by(AssociationRequest.status))).all()
    rows = (await db.execute(base.order_by(AssociationRequest.created_at.desc()).offset(offset).limit(limit))).scalars().all()

    user_ids = {r.requesting_faculty_id for r in rows if r.requesting_faculty_id} | {r.target_faculty_id for r in rows if r.target_faculty_id} | {r.requester_id for r in rows if r.requester_id} | {r.recipient_id for r in rows if r.recipient_id}
    umap = {}
    if user_ids:
        umap = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(list(user_ids))))).scalars().all()}
    rec_ids = [r.ip_record_id for r in rows if r.ip_record_id]
    recs = (await db.execute(select(IpRecord).where(IpRecord.id.in_(rec_ids)))).scalars().all() if rec_ids else []
    rmap = {r.id: r for r in recs}

    def _uname(uid: str | None):
        u = umap.get(uid) if uid else None
        return {"id": uid, "full_name": u.full_name if u else None, "email": u.email if u else None, "faculty_id": u.faculty_id if u else None}

    items = []
    for r in rows:
        rec = rmap.get(r.ip_record_id) if r.ip_record_id else None
        items.append({
            "id": r.id,
            "status": r.status,
            "requester": _uname(r.requesting_faculty_id or r.requester_id),
            "target": _uname(r.target_faculty_id or r.recipient_id),
            "record": {
                "id": r.ip_record_id,
                "title": rec.title if rec else None,
                "ip_type": rec.ip_type if rec else None,
                "patent_number": rec.patent_number if rec else None,
                "application_number": rec.application_number if rec else None,
                "design_number": rec.design_number if rec else None,
                "verification_status": rec.verification_status if rec else None,
                "processing_status": rec.processing_status if rec else None,
            } if r.ip_record_id else None,
            "master_ip_id": r.master_ip_id,
            "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {
        "associations": items,
        "total": total,
        "pending_count": total if wanted == "PENDING" else next((c for s, c in by_status_rows if s == "PENDING"), 0),
        "by_status": {s: c for s, c in by_status_rows},
        "page": page,
        "per_page": per_page,
    }


@router.get("/verifications", status_code=status.HTTP_200_OK)
async def admin_list_verifications(current_user: dict = Depends(get_current_user), status: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    query = select(VerificationAttempt)
    count_query = select(func.count()).select_from(VerificationAttempt)
    if status:
        query = query.where(VerificationAttempt.status == status)
        count_query = count_query.where(VerificationAttempt.status == status)
    total = await _serialize_count(db, count_query)
    rows = await db.execute(query.order_by(VerificationAttempt.created_at.desc()).offset(offset).limit(limit))
    return {"verifications": [_model_to_dict(r) for r in rows.scalars().all()], "total": total, "page": page, "per_page": per_page}


@router.get("/master-ip-records", status_code=status.HTTP_200_OK)
async def admin_list_master_records(current_user: dict = Depends(get_current_user), search: str | None = Query(None, description="search title/numbers"), ip_type: str | None = Query(None), workflow_state: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    offset, limit = _page_slice(page, per_page)
    query = select(MasterIpRecord)
    count_query = select(func.count()).select_from(MasterIpRecord)
    if ip_type:
        query = query.where(MasterIpRecord.ip_type == ip_type)
        count_query = count_query.where(MasterIpRecord.ip_type == ip_type)
    if workflow_state:
        query = query.where(MasterIpRecord.workflow_state == workflow_state)
        count_query = count_query.where(MasterIpRecord.workflow_state == workflow_state)
    if search:
        like = f"%{search}%"
        cond = or_(
            MasterIpRecord.title.ilike(like),
            MasterIpRecord.patent_number.ilike(like),
            MasterIpRecord.application_number.ilike(like),
            MasterIpRecord.design_number.ilike(like),
        )
        query = query.where(cond)
        count_query = count_query.where(cond)
    total = await _serialize_count(db, count_query)
    rows = (await db.execute(query.order_by(MasterIpRecord.created_at.desc()).offset(offset).limit(limit))).scalars().all()

    # Batch-fetch contributors and linked counts for all master records
    # instead of N×2 individual queries (N+1 optimization).
    master_ids = [m.id for m in rows]
    contribs_map: dict[str, list] = {}
    linked_map: dict[str, int] = {}
    if master_ids:
        all_contribs = (await db.execute(
            select(MasterIpContributor).where(MasterIpContributor.master_ip_id.in_(master_ids))
        )).scalars().all()
        for c in all_contribs:
            contribs_map.setdefault(c.master_ip_id, []).append(c)

        linked_rows = (await db.execute(
            select(IpRecord.master_ip_id, func.count().label("cnt"))
            .where(IpRecord.master_ip_id.in_(master_ids))
            .group_by(IpRecord.master_ip_id)
        )).all()
        linked_map = {r.master_ip_id: r.cnt for r in linked_rows}

    items = []
    for m in rows:
        contrib_rows = contribs_map.get(m.id, [])
        linked = linked_map.get(m.id, 0)
        items.append({
            "id": m.id,
            "ip_type": m.ip_type,
            "patent_number": m.patent_number,
            "application_number": m.application_number,
            "design_number": m.design_number,
            "title": m.title,
            "filing_date": m.filing_date.isoformat() if m.filing_date else None,
            "registration_date": m.registration_date.isoformat() if m.registration_date else None,
            "grant_date": m.grant_date.isoformat() if m.grant_date else None,
            "workflow_state": m.workflow_state,
            "official_verification_status": m.official_verification_status,
            "linked_records": linked,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "contributors": [
                {
                    "id": c.id,
                    "name": c.name,
                    "contributor_type": c.contributor_type,
                    "matched_faculty_id": c.matched_faculty_id,
                    "match_confidence": c.match_confidence,
                    "match_status": c.match_status,
                }
                for c in contrib_rows
            ],
        })

    return {"master_ip_records": items, "total": total, "page": page, "per_page": per_page}

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_department_scope, require_hod_admin
from app.core.database import get_async_session
from app.core.exceptions import NotFoundError, PortalError
from app.core.logging import log_audit
from app.models.base import (
    AssociationRequest,
    AuditLog,
    ConflictCase,
    Department,
    Designation,
    DuplicateCase,
    IpFile,
    IpRecord,
    Notification,
    User,
)

router = APIRouter(prefix="/api/v1/hod", tags=["hod"], dependencies=[Depends(require_hod_admin)])


def _ensure_department(user: dict) -> str:
    dept = user.get("department_id")
    if not dept:
        raise PortalError(message="HOD admin account is missing department scope", error_code="AUTHORIZATION_ERROR", status_code=403)
    return dept


async def _record_display_map(db: AsyncSession, record_ids: list[str]) -> dict[str, dict]:
    """User-facing display info for records (Bugs 4+5).

    Returns {record_id: {title, number, filename, display_name}} using only
    persisted data — never fabricated. display_name prefers the actual
    uploaded filename, then title, then identifier number (never the raw
    UUID as the primary user-facing identifier).
    """
    ids = sorted({i for i in record_ids if i})
    if not ids:
        return {}
    recs = (await db.execute(select(IpRecord).where(IpRecord.id.in_(ids)))).scalars().all()
    files = (
        await db.execute(
            select(IpFile)
            .where(IpFile.ip_record_id.in_(ids))
            .order_by(IpFile.created_at.desc())
        )
    ).scalars().all()
    first_file: dict[str, str] = {}
    for f in files:
        first_file.setdefault(f.ip_record_id, f.original_filename)
    out: dict[str, dict] = {}
    for r in recs:
        number = r.patent_number or r.design_number or r.application_number or r.serial_number
        out[r.id] = {
            "title": r.title,
            "number": number,
            "filename": first_file.get(r.id),
            "display_name": first_file.get(r.id) or r.title or number,
        }
    return out


@router.get("/dashboard", status_code=status.HTTP_200_OK)
async def dashboard(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    department_id = _ensure_department(current_user)
    record_ids_sub = select(IpRecord.id).where(IpRecord.department_id == department_id).subquery()

    # Group 1: User counts — single query with filter
    total_faculty = (await db.execute(
        select(func.count()).select_from(User).where(User.role == "faculty", User.department_id == department_id)
    )).scalar_one()

    # Group 2: IpRecord counts — single query with filter() for multiple conditions
    ip_row = (await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(IpRecord.verification_status == "VERIFIED").label("verified"),
            func.count().filter(IpRecord.processing_status.in_(["PENDING", "QUEUED", "PROCESSING", "AWAITING_REVIEW"])).label("pending"),
            func.count().filter(IpRecord.processing_status == "FAILED").label("rejected"),
        ).where(IpRecord.department_id == department_id)
    )).one()

    # Group 3: Cross-table counts using IpRecord subquery — each needs its own
    # table join so we keep them sequential (safe on same session).
    requires_approval = (await db.execute(
        select(func.count()).select_from(AssociationRequest).where(
            AssociationRequest.status.in_(["PENDING", "CLARIFICATION_REQUESTED"]),
            AssociationRequest.ip_record_id.in_(select(record_ids_sub.c.id)),
        )
    )).scalar_one()

    conflicts = (await db.execute(
        select(func.count()).select_from(ConflictCase).where(
            ConflictCase.ip_record_id.in_(select(record_ids_sub.c.id))
        )
    )).scalar_one()

    duplicates = (await db.execute(
        select(func.count()).select_from(DuplicateCase).where(or_(
            DuplicateCase.ip_record_id_1.in_(select(record_ids_sub.c.id)),
            DuplicateCase.ip_record_id_2.in_(select(record_ids_sub.c.id)),
        ))
    )).scalar_one()

    pending_associations = (await db.execute(
        select(func.count()).select_from(AssociationRequest).where(
            AssociationRequest.status == "PENDING",
            AssociationRequest.ip_record_id.in_(select(record_ids_sub.c.id)),
        )
    )).scalar_one()

    return {
        "department_id": department_id,
        "kpis": {
            "total_faculty": total_faculty,
            "total_documents": ip_row.total,
            "verified": ip_row.verified,
            "pending": ip_row.pending,
            "rejected": ip_row.rejected,
            "requires_approval": requires_approval,
            "conflicts": conflicts,
            "duplicates": duplicates,
            "pending_associations": pending_associations,
        },
    }


@router.get("/faculty", status_code=status.HTTP_200_OK)
async def faculty(current_user: dict = Depends(get_current_user), search: str | None = Query(None), db: AsyncSession = Depends(get_async_session)):
    department_id = _ensure_department(current_user)
    query = select(User).where(User.role == "faculty", User.department_id == department_id)
    if search:
        like = f"%{search}%"
        query = query.where(or_(User.full_name.ilike(like), User.email.ilike(like), User.faculty_id.ilike(like)))
    rows = (await db.execute(query.order_by(User.full_name.asc()))).scalars().all()

    desig_map = {
        d.id: (d.name or d.title)
        for d in (await db.execute(select(Designation))).scalars().all()
    }

    # Single grouped query for all counts instead of N+1 per-faculty queries
    user_ids = [u.id for u in rows]
    counts_map: dict[str, dict] = {}
    if user_ids:
        base = (
            select(
                IpRecord.uploader_id,
                func.count().label("total"),
                func.count().filter(IpRecord.verification_status == "VERIFIED").label("verified"),
                func.count().filter(IpRecord.processing_status.in_(["PENDING", "QUEUED", "PROCESSING", "AWAITING_REVIEW"])).label("pending"),
                func.count().filter(IpRecord.processing_status == "FAILED").label("rejected"),
                func.count().filter(IpRecord.ip_type == "PATENT").label("patents"),
            )
            .where(IpRecord.uploader_id.in_(user_ids))
            .group_by(IpRecord.uploader_id)
        )
        for row in (await db.execute(base)).all():
            counts_map[row.uploader_id] = {
                "documents": row.total,
                "verified": row.verified,
                "pending": row.pending,
                "rejected": row.rejected,
                "patents": row.patents,
            }

    empty_counts = {"documents": 0, "patents": 0, "verified": 0, "pending": 0, "rejected": 0}
    out = []
    for u in rows:
        out.append({
            "id": u.id,
            "faculty_id": u.faculty_id,
            "full_name": u.full_name,
            "email": u.email,
            "department_id": u.department_id,
            "designation_id": u.designation_id,
            "designation_name": desig_map.get(u.designation_id),
            "is_active": u.is_active,
            "counts": counts_map.get(u.id, empty_counts),
        })
    return {"faculty": out, "count": len(out), "department_id": department_id}


@router.get("/documents", status_code=status.HTTP_200_OK)
async def documents(
    current_user: dict = Depends(get_current_user),
    status_filter: str | None = Query(None, alias="status"),
    ip_type: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
):
    department_id = _ensure_department(current_user)
    query = select(IpRecord, User.full_name, User.faculty_id).join(User, User.id == IpRecord.uploader_id).where(IpRecord.department_id == department_id)
    count_query = select(func.count()).select_from(IpRecord).where(IpRecord.department_id == department_id)
    if status_filter:
        cond = or_(
            cast(IpRecord.processing_status, String) == status_filter,
            cast(IpRecord.verification_status, String) == status_filter,
            IpRecord.workflow_state == status_filter,
        )
        query = query.where(cond)
        count_query = count_query.where(cond)
    if ip_type:
        query = query.where(IpRecord.ip_type == ip_type)
        count_query = count_query.where(IpRecord.ip_type == ip_type)
    if search:
        like = f"%{search}%"
        cond = or_(IpRecord.title.ilike(like), IpRecord.patent_number.ilike(like), IpRecord.design_number.ilike(like), IpRecord.application_number.ilike(like))
        query = query.where(cond)
        count_query = count_query.where(cond)

    total = (await db.execute(count_query)).scalar_one()
    rows = (await db.execute(query.order_by(IpRecord.created_at.desc()).offset((page - 1) * per_page).limit(per_page))).all()
    rec_ids = [r[0].id for r in rows]
    # Bug 5: user-facing document name (persisted filename/title/number).
    display_map = await _record_display_map(db, rec_ids)
    dup_ids = set()
    conf_ids = set()
    if rec_ids:
        dup_ids = {
            rid
            for row in (await db.execute(select(DuplicateCase.ip_record_id_1, DuplicateCase.ip_record_id_2).where(or_(DuplicateCase.ip_record_id_1.in_(rec_ids), DuplicateCase.ip_record_id_2.in_(rec_ids))))).all()
            for rid in row
            if rid in rec_ids
        }
        conf_ids = {r for (r,) in (await db.execute(select(ConflictCase.ip_record_id).where(ConflictCase.ip_record_id.in_(rec_ids)))).all()}

    return {
        "documents": [
            {
                "id": r.id,
                "title": r.title,
                "document_name": (display_map.get(r.id) or {}).get("display_name"),
                "document_filename": (display_map.get(r.id) or {}).get("filename"),
                "ip_type": r.ip_type,
                "patent_number": r.patent_number,
                "design_number": r.design_number,
                "application_number": r.application_number,
                "grant_date": r.grant_date.isoformat() if r.grant_date else None,
                "uploader_id": r.uploader_id,
                "faculty_name": fname,
                "faculty_id": fid,
                "processing_status": r.processing_status,
                "verification_status": r.verification_status,
                "workflow_state": r.workflow_state,
                "has_duplicate": r.id in dup_ids,
                "has_conflict": r.id in conf_ids,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for (r, fname, fid) in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


@router.get("/duplicates", status_code=status.HTTP_200_OK)
async def duplicates(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    department_id = _ensure_department(current_user)
    dept_ids = select(IpRecord.id).where(IpRecord.department_id == department_id)
    query = (
        select(DuplicateCase)
        .where(or_(DuplicateCase.ip_record_id_1.in_(dept_ids), DuplicateCase.ip_record_id_2.in_(dept_ids)))
        .order_by(DuplicateCase.detected_at.desc())
    )
    rows = (await db.execute(query)).scalars().unique().all()
    # Bugs 4+5: resolve persisted document names for both sides of each case
    # so the UI never shows a raw UUID as the primary identifier.
    pair_ids = [d.ip_record_id_1 for d in rows] + [d.ip_record_id_2 for d in rows]
    display_map = await _record_display_map(db, pair_ids)
    return {
        "duplicates": [
            {
                "id": d.id,
                "status": d.status,
                "confidence": d.confidence,
                "detection_method": d.detection_method,
                "detected_by": d.detected_by,
                "ip_record_id_1": d.ip_record_id_1,
                "ip_record_id_2": d.ip_record_id_2,
                "record_1": display_map.get(d.ip_record_id_1),
                "record_2": display_map.get(d.ip_record_id_2),
                "kept_record_id": d.kept_record_id,
                "resolution_notes": d.resolution_notes,
                "detected_at": d.detected_at.isoformat() if d.detected_at else None,
                "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
            }
            for d in rows
        ],
        "count": len(rows),
        "department_id": department_id,
    }


@router.get("/conflicts", status_code=status.HTTP_200_OK)
async def conflicts(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    department_id = _ensure_department(current_user)
    rows = (await db.execute(select(ConflictCase).where(ConflictCase.ip_record_id.in_(select(IpRecord.id).where(IpRecord.department_id == department_id))).order_by(ConflictCase.created_at.desc()))).scalars().all()
    # Bug 5: persisted document name for the review table.
    display_map = await _record_display_map(db, [c.ip_record_id for c in rows])
    return {
        "conflicts": [
            {
                "id": c.id,
                "ip_record_id": c.ip_record_id,
                "record": display_map.get(c.ip_record_id),
                "conflict_type": c.conflict_type,
                "field_name": c.field_name,
                "severity": c.severity,
                "status": c.status,
                "description": c.description,
                "resolution_notes": c.resolution_notes,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
            }
            for c in rows
        ],
        "count": len(rows),
        "department_id": department_id,
    }


@router.get("/reports", status_code=status.HTTP_200_OK)
async def reports(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    department_id = _ensure_department(current_user)
    dept = IpRecord.department_id == department_id
    base = select(func.count()).select_from(IpRecord).where(dept)
    total_docs = (await db.execute(base)).scalar_one()
    verified = (await db.execute(base.where(IpRecord.verification_status == "VERIFIED"))).scalar_one()
    pending = (await db.execute(base.where(IpRecord.processing_status.in_(["PENDING", "QUEUED", "PROCESSING", "AWAITING_REVIEW"])))).scalar_one()
    rejected = (await db.execute(base.where(IpRecord.processing_status == "FAILED"))).scalar_one()
    total_faculty = (await db.execute(select(func.count()).select_from(User).where(User.role == "faculty", User.department_id == department_id))).scalar_one()

    by_type = {row[0]: row[1] for row in (await db.execute(select(IpRecord.ip_type, func.count()).where(dept).group_by(IpRecord.ip_type))).all()}
    by_verification = {row[0]: row[1] for row in (await db.execute(select(IpRecord.verification_status, func.count()).where(dept).group_by(IpRecord.verification_status))).all()}
    by_workflow = {row[0]: row[1] for row in (await db.execute(select(IpRecord.workflow_state, func.count()).where(dept).group_by(IpRecord.workflow_state))).all()}
    year_expr = func.extract("year", IpRecord.created_at)
    by_year = {str(int(row[0])): row[1] for row in (await db.execute(select(year_expr, func.count()).where(dept).group_by(year_expr))).all() if row[0] is not None}
    month_expr = func.date_trunc("month", IpRecord.created_at)
    trend = [
        {"date": str(row[0]), "value": row[1]}
        for row in (await db.execute(select(month_expr, func.count()).where(dept).group_by(month_expr).order_by(month_expr))).all()
    ]

    duplicates_open = (await db.execute(select(func.count()).select_from(DuplicateCase).where(or_(DuplicateCase.ip_record_id_1.in_(select(IpRecord.id).where(dept)), DuplicateCase.ip_record_id_2.in_(select(IpRecord.id).where(dept))), DuplicateCase.status == "OPEN"))).scalar_one()
    conflicts_open = (await db.execute(select(func.count()).select_from(ConflictCase).where(ConflictCase.ip_record_id.in_(select(IpRecord.id).where(dept)), ConflictCase.status == "OPEN"))).scalar_one()

    return {
        "department_id": department_id,
        "summary": {
            "total_documents": total_docs,
            "total_faculty": total_faculty,
            "verified": verified,
            "pending": pending,
            "rejected": rejected,
            "duplicates_open": duplicates_open,
            "conflicts_open": conflicts_open,
        },
        "by_type": by_type,
        "by_verification": by_verification,
        "by_workflow": by_workflow,
        "by_year": by_year,
        "upload_trend": trend,
    }


@router.get("/audit", status_code=status.HTTP_200_OK)
async def audit(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session), page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100)):
    department_id = _ensure_department(current_user)
    dept_record_ids = select(IpRecord.id).where(IpRecord.department_id == department_id)
    dept_faculty_ids = select(User.id).where(User.department_id == department_id)
    scope = or_(
        AuditLog.entity_id.in_(dept_record_ids),
        AuditLog.target_id.in_(dept_record_ids),
        AuditLog.actor_id.in_(dept_faculty_ids),
    )
    total = (await db.execute(select(func.count()).select_from(AuditLog).where(scope))).scalar_one()
    rows = (await db.execute(select(AuditLog).where(scope).order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page))).scalars().all()
    return {
        "audit_entries": [
            {
                "id": r.id,
                "action": r.action,
                "actor_id": r.actor_id,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "target_id": r.target_id,
                "previous_value": r.previous_value,
                "new_value": r.new_value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


@router.post("/reminders", status_code=status.HTTP_200_OK)
async def reminders(request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    department_id = _ensure_department(current_user)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    kind = body.get("kind", "pending_documents")
    count = (await db.execute(select(func.count()).select_from(IpRecord).where(IpRecord.department_id == department_id, IpRecord.processing_status.in_(["PENDING", "QUEUED", "PROCESSING", "AWAITING_REVIEW"])))).scalar_one()
    log_audit(actor=current_user.get("id"), action="HOD_REMINDER_CREATED", target_type="department", target_id=department_id, status="success", extra={"kind": kind, "count": count})
    return {"department_id": department_id, "kind": kind, "count": count, "status": "sent"}



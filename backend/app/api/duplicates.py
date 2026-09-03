from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_async_session
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.logging import log_audit
from app.models.base import DuplicateCase, IpRecord

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/duplicates", tags=["duplicates"])


@router.get("/", status_code=status.HTTP_200_OK)
async def list_duplicate_cases(current_user: dict = Depends(get_current_user), status: str | None = Query(None), db: AsyncSession = Depends(get_async_session)):
    """List duplicate cases, scoped by role.

    - ``super_admin``: institution-wide.
    - ``hod_admin``: only cases touching a record in the HOD's own department.
    - ``faculty`` (and anything else): forbidden — there is no per-faculty
      duplicate-case listing.
    """
    role = current_user.get("role", "")
    query = select(DuplicateCase)

    if role == "super_admin":
        pass
    elif role == "hod_admin":
        department_id = current_user.get("department_id")
        if not department_id:
            raise AuthorizationError("HOD admin account is missing a department assignment")
        dept_record_ids = select(IpRecord.id).where(IpRecord.department_id == department_id)
        query = query.where(
            or_(
                DuplicateCase.ip_record_id_1.in_(dept_record_ids),
                DuplicateCase.ip_record_id_2.in_(dept_record_ids),
            )
        )
    else:
        raise AuthorizationError("Not authorized to list duplicate cases")

    if status:
        query = query.where(DuplicateCase.status == status.upper())
    rows = await db.execute(query.order_by(DuplicateCase.detected_at.desc()))
    items = rows.scalars().all()
    return {
        "duplicate_cases": [
            {
                "id": item.id,
                "ip_record_id_1": item.ip_record_id_1,
                "ip_record_id_2": item.ip_record_id_2,
                "detection_method": item.detection_method,
                "confidence": item.confidence,
                "status": item.status,
                "kept_record_id": item.kept_record_id,
                "resolution_notes": item.resolution_notes,
                "detected_at": item.detected_at.isoformat() if item.detected_at else None,
                "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
            }
            for item in items
        ],
        "count": len(items),
    }


async def _assert_can_act_on_case(case: DuplicateCase, current_user: dict, db: AsyncSession) -> None:
    """Only a super admin, or an HOD whose department owns one of the two records
    in the case, may resolve/dismiss it. Faculty are never permitted."""
    role = current_user.get("role", "")
    if role == "super_admin":
        return
    if role == "hod_admin":
        department_id = current_user.get("department_id")
        if not department_id:
            raise AuthorizationError("HOD admin account is missing a department assignment")
        owned = (
            await db.execute(
                select(IpRecord.id).where(
                    IpRecord.id.in_([case.ip_record_id_1, case.ip_record_id_2]),
                    IpRecord.department_id == department_id,
                )
            )
        ).first()
        if not owned:
            raise AuthorizationError("Duplicate case is outside your department")
        return
    raise AuthorizationError("Not authorized to resolve duplicate cases")


@router.post("/{case_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve_duplicate_case(request: Request, case_id: str, keep_record_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    case = (await db.execute(select(DuplicateCase).where(DuplicateCase.id == case_id))).scalar_one_or_none()
    if not case:
        raise NotFoundError("Duplicate case", case_id)
    await _assert_can_act_on_case(case, current_user, db)
    action = str(body.get("action", "resolve")).lower()
    case.status = "DISMISSED" if action == "dismiss" else "RESOLVED"
    case.kept_record_id = keep_record_id if action != "dismiss" else None
    case.resolution_notes = body.get("notes")
    case.resolved_by = current_user.get("id")
    await db.commit()
    log_audit(actor=current_user.get("id"), action="DUPLICATE_RESOLVED", target_type="duplicate_case", target_id=case_id, status=case.status.lower(), after={"kept_record_id": case.kept_record_id, "notes": case.resolution_notes})
    return {"case_id": case_id, "status": case.status, "kept_record_id": case.kept_record_id}

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_async_session
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.logging import log_audit
from app.models.base import ConflictCase, IpRecord

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/conflicts", tags=["conflicts"])


def _dept_record_ids(department_id: str):
    return select(IpRecord.id).where(IpRecord.department_id == department_id)


@router.get("/", status_code=status.HTTP_200_OK)
async def list_conflicts(current_user: dict = Depends(get_current_user), conflict_status: str | None = Query(None), conflict_type: str | None = Query(None), db: AsyncSession = Depends(get_async_session)):
    """Conflicts scoped by role: super_admin sees all; hod_admin sees only cases
    on a record in their department; faculty are not permitted a global listing."""
    role = current_user.get("role", "")
    query = select(ConflictCase)

    if role == "super_admin":
        pass
    elif role == "hod_admin":
        department_id = current_user.get("department_id")
        if not department_id:
            raise AuthorizationError("HOD admin account is missing a department assignment")
        query = query.where(ConflictCase.ip_record_id.in_(_dept_record_ids(department_id)))
    else:
        raise AuthorizationError("Not authorized to list conflict cases")

    if conflict_status:
        query = query.where(ConflictCase.status == conflict_status.upper())
    if conflict_type:
        query = query.where(ConflictCase.conflict_type == conflict_type)
    rows = await db.execute(query.order_by(ConflictCase.created_at.desc()))
    items = rows.scalars().all()
    return {
        "conflicts": [
            {
                "id": item.id,
                "ip_record_id": item.ip_record_id,
                "conflict_type": item.conflict_type,
                "field_name": item.field_name,
                "detected_value": item.detected_value,
                "expected_value": item.expected_value,
                "severity": item.severity,
                "description": item.description,
                "status": item.status,
                "resolution_notes": item.resolution_notes,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
            }
            for item in items
        ],
        "count": len(items),
    }


@router.post("/{conflict_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve_conflict(request: Request, conflict_id: str, resolution: str = Query("resolved"), current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    conflict = (await db.execute(select(ConflictCase).where(ConflictCase.id == conflict_id))).scalar_one_or_none()
    if not conflict:
        raise NotFoundError("Conflict case", conflict_id)

    role = current_user.get("role", "")
    if role == "super_admin":
        pass
    elif role == "hod_admin":
        department_id = current_user.get("department_id")
        if not department_id:
            raise AuthorizationError("HOD admin account is missing a department assignment")
        owned = (
            await db.execute(
                select(IpRecord.id).where(IpRecord.id == conflict.ip_record_id, IpRecord.department_id == department_id)
            )
        ).first()
        if not owned:
            raise AuthorizationError("Conflict case is outside your department")
    else:
        raise AuthorizationError("Not authorized to resolve conflict cases")

    action = str(body.get("action", "resolve")).lower()
    conflict.status = "DISMISSED" if action == "dismiss" else "RESOLVED"
    conflict.resolution_notes = body.get("notes") or resolution
    conflict.resolved_by = current_user.get("id")
    await db.commit()
    log_audit(actor=current_user.get("id"), action="CONFLICT_RESOLVED", target_type="conflict_case", target_id=conflict_id, status=conflict.status.lower(), after={"resolution": conflict.resolution_notes})
    return {"conflict_id": conflict_id, "status": conflict.status, "resolution": conflict.resolution_notes}

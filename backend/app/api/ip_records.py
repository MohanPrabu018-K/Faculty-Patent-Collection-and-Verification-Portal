from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_async_session
from app.core.exceptions import NotFoundError, PortalError
from app.core.logging import log_audit
from app.models.base import IpRecord

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/ip-records", tags=["ip-records"])


def _record_to_dict(record: IpRecord) -> dict:
    return {
        "id": record.id,
        "ip_type": record.ip_type,
        "patent_number": record.patent_number,
        "design_number": record.design_number,
        "application_number": record.application_number,
        "serial_number": record.serial_number,
        "title": record.title,
        "applicant": record.applicant,
        "patentee": record.patentee,
        "verification_status": record.verification_status,
        "processing_status": record.processing_status,
        "workflow_state": record.workflow_state,
        "uploader_id": record.uploader_id,
        "department_id": record.department_id,
        "designation_id": record.designation_id,
        "master_ip_id": record.master_ip_id,
        "filing_date": record.filing_date.isoformat() if record.filing_date else None,
        "grant_date": record.grant_date.isoformat() if record.grant_date else None,
        "published_date": record.published_date.isoformat() if record.published_date else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


@router.get("/", status_code=status.HTTP_200_OK)
async def list_ip_records(
    current_user: dict = Depends(get_current_user),
    ip_type: str | None = Query(None),
    verification_status: str | None = Query(None),
    processing_status: str | None = Query(None),
    department_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
):
    """List IP records with filters.

    Faculty see their own records; super admin sees all with filters.
    """
    user_role = current_user.get("role", "")
    user_id = current_user.get("id")

    query = select(IpRecord)
    count_query = select(func.count()).select_from(IpRecord)
    conditions = []

    if user_role != "super_admin":
        conditions.append(IpRecord.uploader_id == user_id)
    if ip_type:
        conditions.append(IpRecord.ip_type == ip_type)
    if verification_status:
        conditions.append(IpRecord.verification_status == verification_status)
    if processing_status:
        conditions.append(IpRecord.processing_status == processing_status)
    if department_id:
        conditions.append(IpRecord.department_id == department_id)

    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)

    total = (await db.execute(count_query)).scalar_one()
    offset = (page - 1) * per_page
    rows = (await db.execute(query.order_by(IpRecord.created_at.desc()).offset(offset).limit(per_page))).scalars().all()

    return {
        "records": [_record_to_dict(r) for r in rows],
        "total": total,
        "count": len(rows),
        "page": page,
        "per_page": per_page,
        "filters_applied": {
            "ip_type": ip_type,
            "verification_status": verification_status,
            "processing_status": processing_status,
            "department_id": department_id,
        },
    }


@router.get("/{record_id}", status_code=status.HTTP_200_OK)
async def get_ip_record(
    record_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a specific IP record."""
    user_role = current_user.get("role", "")
    user_id = current_user.get("id")

    record = (await db.execute(select(IpRecord).where(IpRecord.id == record_id))).scalar_one_or_none()
    if not record:
        raise NotFoundError("IP record", record_id)
    if user_role != "super_admin" and record.uploader_id != user_id:
        raise PortalError(message="Not authorized", error_code="AUTHORIZATION_ERROR", status_code=403)

    return _record_to_dict(record)


@router.patch("/{record_id}", status_code=status.HTTP_200_OK)
async def update_ip_record(
    record_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Update an IP record (admin or owner)."""
    user_role = current_user.get("role", "")
    user_id = current_user.get("id")

    record = (await db.execute(select(IpRecord).where(IpRecord.id == record_id))).scalar_one_or_none()
    if not record:
        raise NotFoundError("IP record", record_id)
    if user_role != "super_admin" and record.uploader_id != user_id:
        raise PortalError(message="Not authorized", error_code="AUTHORIZATION_ERROR", status_code=403)

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}

    updatable = (
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
        "contributor_country",
    )
    changed = []
    for field in updatable:
        if field in body and body[field] is not None:
            setattr(record, field, body[field])
            changed.append(field)

    await db.commit()

    log_audit(
        actor=user_id,
        action="IP_RECORD_UPDATED",
        target_type="ip_record",
        target_id=record_id,
        status="updated",
        after={"fields": changed},
    )

    return _record_to_dict(record)

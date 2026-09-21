from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import upload_settings
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


def _resolve_requested_file(files: list, file_id: str | None) -> IpFile | None:
    for f in files:
        if not file_id or f.id == file_id:
            return f
    return None


@router.get("/{record_id}/file", status_code=status.HTTP_200_OK)
async def download_ip_record_file(
    record_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    file_id: str | None = Query(None, description="specific stored file; defaults to the first file on the record"),
    db: AsyncSession = Depends(get_async_session),
):
    """Download the raw stored file for an IP record (AA1, blueprint §14).

    Authorization (IDOR-safe):
    - super_admin: any record
    - hod_admin: only records from the HOD's own department
    - faculty: only records uploaded by the requesting faculty

    The response filename is the original sanitized name; content is served
    from the private storage root the uploader's key identifies.
    """
    user_role = current_user.get("role", "")
    user_id = current_user.get("id")

    record = (await db.execute(select(IpRecord).where(IpRecord.id == record_id))).scalar_one_or_none()
    if not record:
        raise NotFoundError("IP record", record_id)

    from app.models.base import IpFile

    if user_role == "super_admin":
        pass
    elif user_role == "hod_admin":
        hod_dept = current_user.get("department_id")
        if hod_dept and record.department_id and str(hod_dept) == str(record.department_id):
            pass
        else:
            raise PortalError(message="Not authorized", error_code="AUTHORIZATION_ERROR", status_code=403)
    elif record.uploader_id == user_id:
        pass
    else:
        raise PortalError(message="Not authorized", error_code="AUTHORIZATION_ERROR", status_code=403)

    files_result = await db.execute(
        select(IpFile).where(IpFile.ip_record_id == record_id).order_by(IpFile.created_at)
    )
    files = files_result.scalars().all()
    if not files:
        raise NotFoundError("IP record file", record_id)

    selected = _resolve_requested_file(files, file_id)
    if not selected:
        raise NotFoundError("IP record file", file_id or record_id)

    storage_root = Path(upload_settings.local_storage_root)
    file_path = (storage_root / selected.storage_key).resolve()
    if not str(file_path).startswith(str(storage_root.resolve())):
        raise PortalError(message="Invalid storage path", error_code="AUTHORIZATION_ERROR", status_code=403)
    if not file_path.is_file():
        raise NotFoundError("Stored file", selected.storage_key)

    log_audit(
        actor=user_id,
        action="IP_RECORD_FILE_DOWNLOADED",
        target_type="ip_record",
        target_id=record_id,
        status="success",
        after={"filename": selected.original_filename, "file_size_bytes": selected.file_size_bytes},
    )
    return FileResponse(
        path=str(file_path),
        media_type=selected.mime_type or "application/octet-stream",
        filename=selected.original_filename,
    )


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

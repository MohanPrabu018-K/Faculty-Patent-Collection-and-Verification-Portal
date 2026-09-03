from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_rate_limit, get_current_user
from app.core.config import rate_limit_settings, upload_settings
from app.core.database import get_async_session
from app.core.exceptions import PortalError, RateLimitError
from app.core.logging import log_audit
from app.core.security import validate_filename
from app.models.base import Department, IpFile, IpRecord, ProcessingJob, User
from app.workers.orchestrator_task import run_document_pipeline

import structlog

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])

# Minimum non-empty file size (1 byte). Anything smaller is rejected.
_MIN_UPLOAD_BYTES = 1


@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def upload_certificate(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Upload a patent/design certificate file."""
    client_ip = request.client.host if request.client else "unknown"
    try:
        await check_rate_limit(
            key=f"upload:{client_ip}",
            limit=rate_limit_settings.upload_per_hour,
            window_seconds=3600,
        )
    except RateLimitError as exc:
        raise PortalError(
            message="Upload rate limit exceeded",
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
        ) from exc

    original_filename = file.filename or "unknown"
    is_valid, error_msg = validate_filename(original_filename, upload_settings.allowed_extensions)
    if not is_valid:
        raise PortalError(message=f"Invalid filename: {error_msg}", error_code="UPLOAD_ERROR", status_code=400)

    file_extension = Path(original_filename).suffix.lower()
    if file_extension not in upload_settings.allowed_extensions:
        raise PortalError(message=f"Unsupported file extension: {file_extension}", error_code="UPLOAD_ERROR", status_code=400)

    content = await file.read()
    if len(content) < _MIN_UPLOAD_BYTES:
        raise PortalError(message="File is empty", error_code="UPLOAD_ERROR", status_code=400)
    if len(content) > upload_settings.max_upload_bytes:
        raise PortalError(
            message=f"File too large: {len(content)} bytes (max: {upload_settings.max_upload_bytes})",
            error_code="UPLOAD_ERROR",
            status_code=400,
        )

    if not _validate_file_type(content, file_extension):
        raise PortalError(message="File type does not match extension", error_code="UPLOAD_ERROR", status_code=400)

    if not _validate_document_dimensions(content, file_extension):
        raise PortalError(
            message=f"Document exceeds limits (max {upload_settings.max_pdf_pages} pages / {upload_settings.max_image_dimension}px)",
            error_code="UPLOAD_ERROR",
            status_code=400,
        )

    faculty_id = current_user.get("faculty_id") or current_user.get("id")
    user_id = current_user.get("id")

    # Department is derived from the authenticated uploader's own account, read
    # fresh from the DB. A request-supplied department_id is never trusted for
    # ownership/authorization. Super Admins with no department upload globally
    # (department_id stays NULL).
    uploader = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    uploader_department_id = uploader.department_id if uploader else None
    uploader_designation_id = uploader.designation_id if uploader else None
    uploader_department_name = None
    if uploader_department_id:
        _dept = (
            await db.execute(select(Department).where(Department.id == uploader_department_id))
        ).scalar_one_or_none()
        uploader_department_name = _dept.name if _dept else None

    storage_key = f"{faculty_id}/{uuid.uuid4()}{file_extension}"
    storage_root = Path(upload_settings.local_storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)
    file_path = storage_root / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error("file_save_failed", error=str(e), error_type=type(e).__name__, file_path=str(file_path))
        raise PortalError(message=f"Failed to save file: {e}", error_code="UPLOAD_ERROR", status_code=500)

    ip_record = IpRecord(
        id=str(uuid.uuid4()),
        ip_type="UNKNOWN_OTHER",
        uploader_id=user_id,
        department_id=uploader_department_id,
        designation_id=uploader_designation_id,
        historical_department_id=uploader_department_id,
        historical_department_name=uploader_department_name,
        processing_status="QUEUED",
        verification_status="UNVERIFIED",
        evidence={},
    )

    db.add(ip_record)
    await db.flush()

    # Persist the SHA-256 file fingerprint for duplicate detection.
    from app.services.duplicate_detection import calculate_file_fingerprint
    fingerprint = calculate_file_fingerprint(content)

    ip_file = IpFile(
        id=str(uuid.uuid4()),
        ip_record_id=ip_record.id,
        storage_key=storage_key,
        original_filename=original_filename,
        file_extension=file_extension,
        file_size_bytes=len(content),
        mime_type=file.content_type,
        fingerprint=fingerprint,
        uploaded_by=user_id,
        upload_status="COMPLETED",
    )
    db.add(ip_file)

    processing_job = ProcessingJob(
        id=str(uuid.uuid4()),
        ip_record_id=ip_record.id,
        job_type="orchestrator",
        status="QUEUED",
        max_retries=3,
    )
    db.add(processing_job)

    await db.commit()
    await db.refresh(ip_record)

    # Schedule the deterministic 11-agent pipeline as a background task.
    # The pipeline runs on the FastAPI process (no Celery/Redis required).
    logger.info(
        "background_task_scheduled",
        ip_record_id=ip_record.id,
        file_path=str(file_path),
        exists=file_path.exists(),
    )
    if background_tasks is not None:
        background_tasks.add_task(run_document_pipeline, str(file_path), ip_record.id)
    else:
        # Test/fixture path: run synchronously so callers get a terminal status.
        run_document_pipeline(str(file_path), ip_record.id)
    logger.info(
        "document_processing_queued",
        ip_record_id=ip_record.id,
        faculty_id=faculty_id,
        filename=original_filename,
    )

    log_audit(
        actor=user_id,
        action="UPLOAD",
        target_type="ip_record",
        target_id=ip_record.id,
        status="uploaded",
        before={},
        after={"filename": original_filename, "file_size": len(content)},
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "pending",
            "message": "Certificate upload received - background processing started",
            "ip_record_id": ip_record.id,
            "filename": original_filename,
            "file_size": len(content),
        },
        background=background_tasks,
    )
@router.get("/{ip_record_id}/status", status_code=status.HTTP_200_OK)
async def get_upload_status(
    ip_record_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get the processing status of an uploaded certificate."""
    user_id = current_user.get("id")
    user_role = current_user.get("role", "faculty")

    query = select(IpRecord).where(IpRecord.id == ip_record_id)
    if user_role == "faculty":
        query = query.where(IpRecord.uploader_id == user_id)
    elif user_role == "hod_admin":
        dept = current_user.get("department_id")
        if not dept:
            raise HTTPException(status_code=403, detail="HOD account is missing a department")
        query = query.where(IpRecord.department_id == dept)

    result = await db.execute(query)
    ip_record = result.scalar_one_or_none()

    if not ip_record:
        raise HTTPException(status_code=404, detail="IP record not found")

    jobs_result = await db.execute(select(ProcessingJob).where(ProcessingJob.ip_record_id == ip_record_id))
    jobs = jobs_result.scalars().all()

    file_result = await db.execute(select(IpFile).where(IpFile.ip_record_id == ip_record_id))
    files = file_result.scalars().all()

    return {
        "ip_record_id": ip_record.id,
        "ip_type": ip_record.ip_type,
        "processing_status": ip_record.processing_status,
        "verification_status": ip_record.verification_status,
        "patent_number": ip_record.patent_number,
        "design_number": ip_record.design_number,
        "title": ip_record.title,
        "applicant": ip_record.applicant,
        "jobs": [
            {
                "job_type": job.job_type,
                "status": job.status,
                "retry_count": job.retry_count,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }
            for job in jobs
        ],
        "files": [
            {
                "id": f.id,
                "original_filename": f.original_filename,
                "file_size_bytes": f.file_size_bytes,
                "upload_status": f.upload_status,
            }
            for f in files
        ],
    }


def _validate_file_type(content: bytes, extension: str) -> bool:
    """Validate file type by checking magic bytes."""
    if not content:
        return False

    magic_bytes = {
        ".pdf": [b"%PDF"],
        ".png": [bytes([0x89]) + b"PNG" + b"\r\n\x1a\n"],
        ".jpg": [b"\xff\xd8\xff"],
        ".jpeg": [b"\xff\xd8\xff"],
    }

    expected = magic_bytes.get(extension.lower(), [])
    if not expected:
        return False

    return any(content.startswith(magic) for magic in expected)


def _validate_document_dimensions(content: bytes, extension: str) -> bool:
    """Validate PDF page count and image dimensions against configured limits.

    Returns True when the document is within limits or the dimension cannot be
    cheaply determined (fail-open so legitimate files are not rejected due to a
    missing optional parser).
    """
    ext = extension.lower()

    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=content, filetype="pdf")
            try:
                return doc.page_count <= upload_settings.max_pdf_pages
            finally:
                doc.close()
        except Exception:
            # Unable to inspect page count; defer to pipeline for validation.
            return True

    if ext in (".png", ".jpg", ".jpeg"):
        try:
            import cv2
            import numpy as np

            arr = np.frombuffer(content, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
            if img is None:
                return True
            height, width = img.shape[:2]
            return width <= upload_settings.max_image_dimension and height <= upload_settings.max_image_dimension
        except Exception:
            return True

    return True







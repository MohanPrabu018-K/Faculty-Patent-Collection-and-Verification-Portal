from __future__ import annotations

import io
import uuid

import structlog
from app.api.deps import get_current_user
from app.services.search_analytics import ExportFormat, create_export_job as create_export_job_service, get_export_service
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def create_export_job(
    request: Request,
    current_user: dict = Depends(get_current_user),
    format: str = Query("csv", pattern="^(csv|excel|json|pdf|docx)$"),
    filters: dict | None = None,
):
    """Create an export job using the real export service."""
    export_format = ExportFormat(format)
    user_id = current_user.get("id")
    job = await create_export_job_service(export_format, filters or {}, user_id)
    return {
        "job_id": job.id,
        "status": job.status,
        "format": job.format.value,
        "created_at": job.created_at.isoformat(),
    }


@router.get("/{job_id}/download", status_code=status.HTTP_200_OK)
async def download_export(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Download a completed export job result."""
    service = get_export_service()
    job = await service.get_job_status(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "EXPORT_NOT_FOUND", "message": "Export job not found"})
    file_data = await service.get_file(job_id)
    if not file_data:
        return JSONResponse(status_code=404, content={"error": "FILE_NOT_FOUND", "message": "Export file not found"})
    filename = f"export_{job_id}.{job.get('format', 'csv')}"
    media_types = {"csv": "text/csv", "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "json": "application/json", "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    return StreamingResponse(io.BytesIO(file_data), media_type=media_types.get(job.get('format', 'csv'), "application/octet-stream"), headers={"Content-Disposition": f'attachment; filename="{filename}"'})


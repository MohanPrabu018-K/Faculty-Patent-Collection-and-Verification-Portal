from __future__ import annotations

import io

import structlog
from app.api.deps import get_current_user
from app.core.exceptions import AuthorizationError
from app.services.search_analytics import ExportFormat, SearchFilters, SearchSortField, create_export_job, get_analytics_overview, get_analytics_service, get_export_service, get_search_service, search_ip_records
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.get("/", status_code=status.HTTP_200_OK)
async def search_ip_records_endpoint(current_user: dict = Depends(get_current_user), query: str | None = Query(None), ip_type: str | None = Query(None), patent_number: str | None = Query(None), design_number: str | None = Query(None), application_number: str | None = Query(None), title: str | None = Query(None), faculty_name: str | None = Query(None), faculty_id: str | None = Query(None), institution: str | None = Query(None), department_id: str | None = Query(None), designation_id: str | None = Query(None), date_from: str | None = Query(None), date_to: str | None = Query(None), verification_status: str | None = Query(None), processing_status: str | None = Query(None), uploader_id: str | None = Query(None), has_associations: bool | None = Query(None), is_collaborative: bool | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), sort_by: str = Query("relevance"), sort_order: str = Query("desc")):
    role = current_user.get("role", "faculty")
    # Server-side scoping that a client cannot override:
    #  - faculty  -> only their own uploads
    #  - hod_admin -> only their own department
    #  - super_admin -> institution-wide
    scoped_faculty_id = current_user.get("id") if role == "faculty" else faculty_id
    scoped_department_id = department_id
    if role == "hod_admin":
        scoped_department_id = current_user.get("department_id")
        if not scoped_department_id:
            raise AuthorizationError("HOD admin account is missing a department assignment")
    filters = SearchFilters(query=query, ip_type=ip_type, patent_number=patent_number, design_number=design_number, application_number=application_number, title=title, faculty_name=faculty_name, faculty_id=scoped_faculty_id, institution=institution, department_id=scoped_department_id, designation_id=designation_id, date_from=date_from, date_to=date_to, verification_status=verification_status, processing_status=processing_status, uploader_id=uploader_id, has_associations=has_associations, is_collaborative=is_collaborative)
    sort_by_enum = SearchSortField(sort_by) if sort_by in [e.value for e in SearchSortField] else SearchSortField.RELEVANCE
    result = await search_ip_records(filters=filters, page=page, per_page=per_page, sort_by=sort_by_enum, sort_order=sort_order, user_role=role, user_id=current_user.get("id"))
    return {"results": [r.__dict__ for r in result.results], "total": result.total, "page": result.page, "per_page": result.per_page, "total_pages": result.total_pages, "query_time_ms": result.query_time_ms, "facets": result.facets}


@router.get("/suggestions", status_code=status.HTTP_200_OK)
async def get_search_suggestions(q: str = Query(..., min_length=2), limit: int = Query(10, ge=1, le=50), current_user: dict = Depends(get_current_user)):
    service = get_search_service()
    return {"suggestions": await service.get_suggestions(q, limit)}


analytics_router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@analytics_router.get("/overview", status_code=status.HTTP_200_OK)
async def analytics_overview(current_user: dict = Depends(get_current_user), date_from: str | None = Query(None), date_to: str | None = Query(None)):
    overview = await get_analytics_overview(date_from, date_to)
    return overview.__dict__


@analytics_router.get("/by-faculty", status_code=status.HTTP_200_OK)
async def analytics_by_faculty(current_user: dict = Depends(get_current_user), faculty_id: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    service = get_analytics_service()
    results, total = await service.get_by_faculty(faculty_id, page, per_page)
    return {"faculty": [r.__dict__ for r in results], "total": total, "page": page, "per_page": per_page}


@analytics_router.get("/by-department", status_code=status.HTTP_200_OK)
async def analytics_by_department(current_user: dict = Depends(get_current_user), department_id: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    service = get_analytics_service()
    results, total = await service.get_by_department(department_id, page, per_page)
    return {"departments": [r.__dict__ for r in results], "total": total, "page": page, "per_page": per_page}


@analytics_router.get("/trends", status_code=status.HTTP_200_OK)
async def analytics_trends(current_user: dict = Depends(get_current_user), metric: str = Query("uploads", pattern="^(uploads|verifications|publications|associations)$"), granularity: str = Query("month", pattern="^(day|week|month|year)$"), date_from: str | None = Query(None), date_to: str | None = Query(None)):
    service = get_analytics_service()
    trends = await service.get_trends(metric, granularity, date_from, date_to)
    return {"trends": [t.__dict__ for t in trends]}


exports_router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


def _scoped_export_filters(current_user: dict, filters: dict | None) -> dict:
    """Force a role-appropriate export scope; a client cannot widen it."""
    role = current_user.get("role", "faculty")
    f = dict(filters or {})
    if role == "super_admin":
        return f
    if role == "hod_admin":
        dept = current_user.get("department_id")
        if not dept:
            raise AuthorizationError("HOD admin account is missing a department assignment")
        f["department_id"] = dept
        f.pop("faculty_id", None)
        return f
    f["faculty_id"] = current_user.get("id")
    f.pop("department_id", None)
    return f


def _job_owned(job: dict, current_user: dict) -> bool:
    return current_user.get("role") == "super_admin" or job.get("created_by") == current_user.get("id")


@exports_router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def create_export(request: Request, current_user: dict = Depends(get_current_user), format: str = Query("csv", pattern="^(csv|excel|json|pdf|docx|txt)$")):
    try:
        body = await request.json()
    except Exception:
        body = {}
    filters = body.get("filters", {}) if isinstance(body, dict) else {}
    selected_fields = body.get("selected_fields") if isinstance(body, dict) else None
    if selected_fields:
        filters["selected_fields"] = selected_fields
    export_format = ExportFormat(format)
    user_id = current_user.get("id")
    scoped = _scoped_export_filters(current_user, filters)
    job = await create_export_job(export_format, scoped, user_id)
    return {"job_id": job.id, "format": job.format.value, "status": job.status, "created_at": job.created_at.isoformat()}


@exports_router.get("/{job_id}", status_code=status.HTTP_200_OK)
async def get_export_status(job_id: str, current_user: dict = Depends(get_current_user)):
    service = get_export_service()
    job = await service.get_job_status(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "EXPORT_NOT_FOUND", "message": "Export job not found"})
    if not _job_owned(job, current_user):
        raise AuthorizationError("Not authorized to view this export job")
    return {k: v for k, v in job.items() if k != "file_data"}


@exports_router.get("/{job_id}/download", status_code=status.HTTP_200_OK)
async def download_export(job_id: str, current_user: dict = Depends(get_current_user)):
    service = get_export_service()
    job = await service.get_job_status(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "EXPORT_NOT_FOUND", "message": "Export job not found"})
    if not _job_owned(job, current_user):
        raise AuthorizationError("Not authorized to download this export")
    file_data = await service.get_file(job_id)
    if not file_data:
        return JSONResponse(status_code=404, content={"error": "FILE_NOT_FOUND", "message": "Export file not found"})
    filename = f"export_{job_id}.{job.get('format', 'csv')}"
    media_types = {"csv": "text/csv", "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "json": "application/json", "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "txt": "text/plain"}
    return StreamingResponse(io.BytesIO(file_data), media_type=media_types.get(job.get('format', 'csv'), "application/octet-stream"), headers={"Content-Disposition": f'attachment; filename="{filename}"'})

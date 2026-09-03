from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.core.database import get_async_session_context
from app.models.base import Department, IpContributor, IpRecord, User, VerificationAttempt


class SearchSortField(Enum):
    RELEVANCE = "relevance"
    DATE_DESC = "date_desc"
    DATE_ASC = "date_asc"
    TITLE = "title"
    FACULTY = "faculty"
    VERIFICATION_STATUS = "verification_status"


@dataclass
class SearchFilters:
    query: str | None = None
    ip_type: str | None = None
    patent_number: str | None = None
    design_number: str | None = None
    application_number: str | None = None
    title: str | None = None
    faculty_name: str | None = None
    faculty_id: str | None = None
    institution: str | None = None
    department_id: str | None = None
    designation_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    verification_status: str | None = None
    processing_status: str | None = None
    uploader_id: str | None = None
    has_associations: bool | None = None
    is_collaborative: bool | None = None


@dataclass
class SearchResult:
    id: str
    ip_type: str
    patent_number: str | None = None
    design_number: str | None = None
    application_number: str | None = None
    title: str | None = None
    applicant: str | None = None
    inventors: list[str] = field(default_factory=list)
    filing_date: str | None = None
    grant_date: str | None = None
    verification_status: str = ""
    processing_status: str = ""
    faculty_name: str | None = None
    faculty_id: str | None = None
    department: str | None = None
    institution: str | None = None
    contributor_count: int = 0
    is_collaborative: bool = False
    created_at: str | None = None
    score: float = 1.0


@dataclass
class SearchResponse:
    results: list[SearchResult]
    total: int
    page: int
    per_page: int
    total_pages: int
    query_time_ms: float
    facets: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class TimeSeriesPoint:
    date: str
    value: int


@dataclass
class AnalyticsOverview:
    total_faculty: int
    active_faculty: int
    total_ip_records: int
    verified_records: int
    pending_verification: int
    pending_processing: int
    by_ip_type: dict[str, int]
    by_verification_status: dict[str, int]
    by_processing_status: dict[str, int]
    by_department: dict[str, int]
    by_year: dict[str, int]
    collaborative_records: int
    external_contributions: int
    upload_trend: list[TimeSeriesPoint]
    verification_trend: list[TimeSeriesPoint]


@dataclass
class FacultyAnalytics:
    faculty_id: str
    faculty_name: str
    total_records: int
    verified_records: int
    pending_records: int
    by_ip_type: dict[str, int]
    by_year: dict[str, int]
    collaborative_count: int
    external_collaborations: int


@dataclass
class DepartmentAnalytics:
    department_id: str
    department_name: str
    total_faculty: int
    total_records: int
    verified_records: int
    by_ip_type: dict[str, int]
    by_year: dict[str, int]


class ExportFormat(Enum):
    CSV = "csv"
    EXCEL = "excel"
    JSON = "json"
    PDF = "pdf"


@dataclass
class ExportJob:
    id: str
    format: ExportFormat
    filters: dict[str, Any]
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    file_path: str | None = None
    error: str | None = None
    record_count: int = 0


class SearchService:
    async def search(self, filters: SearchFilters, page: int = 1, per_page: int = 20, sort_by: SearchSortField = SearchSortField.RELEVANCE, sort_order: str = "desc", user_role: str = "faculty", user_id: str | None = None) -> SearchResponse:
        start = time.time()
        async with get_async_session_context() as session:
            # join(User) drives the faculty_name/faculty_id filters; selectinload
            # eagerly fetches the relationships read while building SearchResult
            # (async lazy-loading outside a greenlet raises greenlet_spawn errors).
            query = (
                select(IpRecord)
                .join(User, User.id == IpRecord.uploader_id)
                .options(selectinload(IpRecord.uploader), selectinload(IpRecord.department))
            )
            count_query = select(func.count()).select_from(IpRecord).join(User, User.id == IpRecord.uploader_id)
            clauses = []
            if filters.query:
                like = f"%{filters.query.strip()}%"
                clauses.append(
                    or_(
                        IpRecord.title.ilike(like),
                        IpRecord.applicant.ilike(like),
                        IpRecord.patentee.ilike(like),
                        IpRecord.contributor_name.ilike(like),
                        IpRecord.patent_number.ilike(like),
                        IpRecord.design_number.ilike(like),
                        IpRecord.application_number.ilike(like),
                        IpRecord.serial_number.ilike(like),
                        User.full_name.ilike(like),
                    )
                )
            if user_role == "faculty" and user_id:
                clauses.append(IpRecord.uploader_id == user_id)
            elif filters.faculty_id:
                clauses.append(User.faculty_id == filters.faculty_id)
            if filters.uploader_id:
                clauses.append(IpRecord.uploader_id == filters.uploader_id)
            if filters.ip_type:
                clauses.append(IpRecord.ip_type == filters.ip_type)
            if filters.patent_number:
                clauses.append(IpRecord.patent_number.ilike(f"%{filters.patent_number}%"))
            if filters.design_number:
                clauses.append(IpRecord.design_number.ilike(f"%{filters.design_number}%"))
            if filters.application_number:
                clauses.append(IpRecord.application_number.ilike(f"%{filters.application_number}%"))
            if filters.title:
                clauses.append(IpRecord.title.ilike(f"%{filters.title}%"))
            if filters.faculty_name:
                clauses.append(User.full_name.ilike(f"%{filters.faculty_name}%"))
            if filters.department_id:
                clauses.append(IpRecord.department_id == filters.department_id)
            if filters.designation_id:
                clauses.append(IpRecord.designation_id == filters.designation_id)
            if filters.verification_status:
                clauses.append(IpRecord.verification_status == filters.verification_status)
            if filters.processing_status:
                clauses.append(IpRecord.processing_status == filters.processing_status)
            if filters.date_from:
                clauses.append(IpRecord.created_at >= datetime.fromisoformat(filters.date_from))
            if filters.date_to:
                clauses.append(IpRecord.created_at <= datetime.fromisoformat(filters.date_to))
            if clauses:
                query = query.where(and_(*clauses))
                count_query = count_query.where(and_(*clauses))
            if sort_by == SearchSortField.DATE_ASC:
                query = query.order_by(IpRecord.created_at.asc())
            elif sort_by == SearchSortField.TITLE:
                query = query.order_by(IpRecord.title.asc())
            else:
                query = query.order_by(IpRecord.created_at.desc())
            total = (await session.execute(count_query)).scalar_one()
            rows = (await session.execute(query.offset((page - 1) * per_page).limit(per_page))).scalars().all()

            # One grouped query for contributor counts instead of N per-row queries.
            page_ids = [r.id for r in rows]
            counts: dict[str, int] = {}
            if page_ids:
                counts = {
                    rid: cnt
                    for rid, cnt in (
                        await session.execute(
                            select(IpContributor.ip_record_id, func.count())
                            .where(IpContributor.ip_record_id.in_(page_ids))
                            .group_by(IpContributor.ip_record_id)
                        )
                    ).all()
                }

            results = []
            for record in rows:
                contributor_count = counts.get(record.id, 0)
                results.append(SearchResult(id=record.id, ip_type=record.ip_type, patent_number=record.patent_number, design_number=record.design_number, application_number=record.application_number, title=record.title, applicant=record.applicant, filing_date=record.filing_date.isoformat() if record.filing_date else None, grant_date=record.grant_date.isoformat() if record.grant_date else None, verification_status=record.verification_status, processing_status=record.processing_status, faculty_name=record.uploader.full_name if record.uploader else None, faculty_id=record.uploader.faculty_id if record.uploader else None, department=record.department.name if record.department else None, institution=None, contributor_count=contributor_count, is_collaborative=contributor_count > 1, created_at=record.created_at.isoformat() if record.created_at else None, score=1.0))
            return SearchResponse(results=results, total=total, page=page, per_page=per_page, total_pages=(total + per_page - 1) // per_page, query_time_ms=round((time.time() - start) * 1000, 2), facets={})

    async def get_suggestions(self, query: str, limit: int = 10) -> list[str]:
        async with get_async_session_context() as session:
            rows = await session.execute(select(IpRecord.title).where(IpRecord.title.ilike(f"%{query}%")).order_by(IpRecord.created_at.desc()).limit(limit))
            return [row[0] for row in rows.all() if row[0]]


class AnalyticsService:
    async def get_overview(self, date_from: str | None = None, date_to: str | None = None) -> AnalyticsOverview:
        async with get_async_session_context() as session:
            total_faculty = (await session.execute(select(func.count()).select_from(User).where(User.role == "faculty"))).scalar_one()
            active_faculty = (await session.execute(select(func.count()).select_from(User).where(User.role == "faculty", User.is_active.is_(True)))).scalar_one()
            total_ip_records = (await session.execute(select(func.count()).select_from(IpRecord))).scalar_one()
            verified_records = (await session.execute(select(func.count()).select_from(IpRecord).where(IpRecord.verification_status == "VERIFIED"))).scalar_one()
            pending_verification = (await session.execute(select(func.count()).select_from(IpRecord).where(IpRecord.verification_status.in_(["UNVERIFIED", "VERIFICATION_REQUIRED"])))).scalar_one()
            pending_processing = (await session.execute(select(func.count()).select_from(IpRecord).where(IpRecord.processing_status.in_(["PENDING", "QUEUED", "PROCESSING"])))).scalar_one()
            by_ip_type = {row[0]: row[1] for row in (await session.execute(select(IpRecord.ip_type, func.count()).group_by(IpRecord.ip_type))).all()}
            by_verification_status = {row[0]: row[1] for row in (await session.execute(select(IpRecord.verification_status, func.count()).group_by(IpRecord.verification_status))).all()}
            by_processing_status = {row[0]: row[1] for row in (await session.execute(select(IpRecord.processing_status, func.count()).group_by(IpRecord.processing_status))).all()}
            by_department = {row[0] or "Unknown": row[1] for row in (await session.execute(select(Department.name, func.count()).select_from(IpRecord).join(Department, Department.id == IpRecord.department_id, isouter=True).group_by(Department.name))).all()}
            by_year = {str(row[0]): row[1] for row in (await session.execute(select(func.extract("year", IpRecord.created_at), func.count()).group_by(func.extract("year", IpRecord.created_at)))).all()}
            collaborative_records = (await session.execute(select(func.count()).select_from(IpRecord).join(IpContributor, IpContributor.ip_record_id == IpRecord.id).group_by(IpRecord.id).having(func.count(IpContributor.id) > 1))).all()
            external_contributions = (await session.execute(select(func.count()).select_from(IpContributor).where(IpContributor.is_external.is_(True)))).scalar_one()
            # Reuse one expression object for SELECT/GROUP BY/ORDER BY: Postgres
            # rejects a parameterised date_trunc() unless the bind params are
            # provably identical, which only happens when SQLAlchemy renders the
            # same placeholder for the same object.
            upload_bucket = func.date_trunc("month", IpRecord.created_at)
            upload_trend = [TimeSeriesPoint(date=str(row[0]), value=row[1]) for row in (await session.execute(select(upload_bucket, func.count()).group_by(upload_bucket).order_by(upload_bucket))).all()]
            verif_bucket = func.date_trunc("month", VerificationAttempt.created_at)
            verification_trend = [TimeSeriesPoint(date=str(row[0]), value=row[1]) for row in (await session.execute(select(verif_bucket, func.count()).group_by(verif_bucket).order_by(verif_bucket))).all()]
            return AnalyticsOverview(total_faculty=total_faculty, active_faculty=active_faculty, total_ip_records=total_ip_records, verified_records=verified_records, pending_verification=pending_verification, pending_processing=pending_processing, by_ip_type=by_ip_type, by_verification_status=by_verification_status, by_processing_status=by_processing_status, by_department=by_department, by_year=by_year, collaborative_records=len(collaborative_records), external_contributions=external_contributions, upload_trend=upload_trend, verification_trend=verification_trend)

    async def get_by_faculty(self, faculty_id: str | None = None, page: int = 1, per_page: int = 20) -> tuple[list[FacultyAnalytics], int]:
        async with get_async_session_context() as session:
            query = select(User).where(User.role == "faculty")
            if faculty_id:
                query = query.where(User.faculty_id == faculty_id)
            users = (await session.execute(query.offset((page - 1) * per_page).limit(per_page))).scalars().all()
            total = (await session.execute(select(func.count()).select_from(User).where(User.role == "faculty"))).scalar_one()
            results = []
            for user in users:
                record_count = (await session.execute(select(func.count()).select_from(IpRecord).where(IpRecord.uploader_id == user.id))).scalar_one()
                verified = (await session.execute(select(func.count()).select_from(IpRecord).where(IpRecord.uploader_id == user.id, IpRecord.verification_status == "VERIFIED"))).scalar_one()
                pending = (await session.execute(select(func.count()).select_from(IpRecord).where(IpRecord.uploader_id == user.id, IpRecord.processing_status.in_(["PENDING", "QUEUED", "PROCESSING"])))).scalar_one()
                results.append(FacultyAnalytics(faculty_id=user.faculty_id or user.id, faculty_name=user.full_name, total_records=record_count, verified_records=verified, pending_records=pending, by_ip_type={}, by_year={}, collaborative_count=0, external_collaborations=0))
            return results, total

    async def get_by_department(self, department_id: str | None = None, page: int = 1, per_page: int = 20) -> tuple[list[DepartmentAnalytics], int]:
        async with get_async_session_context() as session:
            query = select(Department)
            if department_id:
                query = query.where(Department.id == department_id)
            departments = (await session.execute(query.offset((page - 1) * per_page).limit(per_page))).scalars().all()
            total = (await session.execute(select(func.count()).select_from(Department))).scalar_one()
            results = []
            for dept in departments:
                total_records = (await session.execute(select(func.count()).select_from(IpRecord).where(IpRecord.department_id == dept.id))).scalar_one()
                verified_records = (await session.execute(select(func.count()).select_from(IpRecord).where(IpRecord.department_id == dept.id, IpRecord.verification_status == "VERIFIED"))).scalar_one()
                faculty_total = (await session.execute(select(func.count()).select_from(User).join(IpRecord, IpRecord.uploader_id == User.id).where(IpRecord.department_id == dept.id))).scalar_one()
                results.append(DepartmentAnalytics(department_id=dept.id, department_name=dept.name, total_faculty=faculty_total, total_records=total_records, verified_records=verified_records, by_ip_type={}, by_year={}))
            return results, total

    async def get_trends(self, metric: str, granularity: str = "month", date_from: str | None = None, date_to: str | None = None) -> list[TimeSeriesPoint]:
        async with get_async_session_context() as session:
            bucket = func.date_trunc(granularity, IpRecord.created_at)
            rows = await session.execute(select(bucket, func.count()).group_by(bucket).order_by(bucket))
            return [TimeSeriesPoint(date=str(row[0]), value=row[1]) for row in rows.all()]


class ExportService:
    def __init__(self):
        self._jobs: dict[str, dict] = {}

    async def create_export(self, format: ExportFormat, filters: dict[str, Any], user_id: str) -> ExportJob:
        job_id = f"export-{format.value}-{int(time.time())}"
        async with get_async_session_context() as session:
            query = select(IpRecord)
            if filters.get("faculty_id"):
                query = query.where(IpRecord.uploader_id == filters["faculty_id"])
            if filters.get("department_id"):
                query = query.where(IpRecord.department_id == filters["department_id"])
            if filters.get("ip_type"):
                query = query.where(IpRecord.ip_type == filters["ip_type"])
            if filters.get("verification_status"):
                query = query.where(IpRecord.verification_status == filters["verification_status"])
            records = (await session.execute(query.order_by(IpRecord.created_at.desc()))).scalars().all()
            fieldnames = ["id", "ip_type", "patent_number", "design_number", "application_number", "title", "verification_status", "processing_status", "created_at"]
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow({"id": record.id, "ip_type": record.ip_type, "patent_number": record.patent_number or "", "design_number": record.design_number or "", "application_number": record.application_number or "", "title": record.title or "", "verification_status": record.verification_status, "processing_status": record.processing_status, "created_at": record.created_at.isoformat() if record.created_at else ""})
            self._jobs[job_id] = {"id": job_id, "format": format.value, "filters": filters, "status": "completed", "created_at": datetime.now(UTC), "created_by": user_id, "record_count": len(records), "file_data": output.getvalue().encode("utf-8"), "file_path": None, "error": None}
            return ExportJob(id=job_id, format=format, filters=filters, status="completed", created_at=self._jobs[job_id]["created_at"], completed_at=datetime.now(UTC), record_count=len(records))

    async def get_job_status(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    async def get_file(self, job_id: str) -> bytes | None:
        job = self._jobs.get(job_id)
        return job.get("file_data") if job else None


_search_service: SearchService | None = None
_analytics_service: AnalyticsService | None = None
_export_service: ExportService | None = None


def get_search_service() -> SearchService:
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service


def get_analytics_service() -> AnalyticsService:
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = AnalyticsService()
    return _analytics_service


def get_export_service() -> ExportService:
    global _export_service
    if _export_service is None:
        _export_service = ExportService()
    return _export_service


async def search_ip_records(filters: SearchFilters, page: int = 1, per_page: int = 20, sort_by: SearchSortField = SearchSortField.RELEVANCE, sort_order: str = "desc", user_role: str = "faculty", user_id: str | None = None) -> SearchResponse:
    return await get_search_service().search(filters, page, per_page, sort_by, sort_order, user_role, user_id)


async def get_analytics_overview(date_from: str | None = None, date_to: str | None = None) -> AnalyticsOverview:
    return await get_analytics_service().get_overview(date_from, date_to)


async def create_export_job(format: ExportFormat, filters: dict[str, Any], user_id: str) -> ExportJob:
    return await get_export_service().create_export(format, filters, user_id)


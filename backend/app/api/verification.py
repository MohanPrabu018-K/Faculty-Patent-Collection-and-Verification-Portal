from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_async_session
from app.core.exceptions import NotFoundError
from app.core.logging import log_audit
from app.verification.adapters import VerificationService, get_verification_registry, verify_patent_or_design
from app.models.base import VerificationAttempt

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/verification", tags=["verification"])


@router.get("/sources", status_code=status.HTTP_200_OK)
async def list_verification_sources(current_user: dict = Depends(get_current_user), country: str | None = Query(None), ip_type: str | None = Query(None)):
    registry = get_verification_registry()
    sources = []
    for adapter in registry._adapters.values():
        if (not ip_type or ip_type in adapter.source.supported_ip_types) and (not country or not adapter.source.supported_countries or "ALL" in adapter.source.supported_countries or country in adapter.source.supported_countries):
            sources.append({"name": adapter.get_source_name(), "display_name": adapter.source.display_name, "url": adapter.source.url, "supported_countries": adapter.source.supported_countries, "supported_ip_types": adapter.source.supported_ip_types, "requires_api_key": adapter.source.requires_api_key, "rate_limit_rps": adapter.source.rate_limit_rps})
    return {"sources": sources, "count": len(sources)}


@router.post("/verify", status_code=status.HTTP_200_OK)
async def verify_ip_record(request: Request, current_user: dict = Depends(get_current_user), ip_type: str = Query(...), identifier: str = Query(...), title: str | None = Query(None), applicant: str | None = Query(None), inventor: str | None = Query(None), filing_date: str | None = Query(None), country: str | None = Query(None), source: str | None = Query(None), db: AsyncSession = Depends(get_async_session)):
    result = await verify_patent_or_design(ip_type=ip_type, identifier=identifier, title=title, applicant=applicant, inventor=inventor, filing_date=filing_date, country=country, source=source)
    log_audit(actor=current_user.get("id"), action="VERIFICATION_ATTEMPT", target_type="ip_record", target_id=identifier, status="completed" if result.success else "failed", extra={"source": result.source, "status": result.status, "confidence": result.confidence})
    return {"identifier": identifier, "ip_type": ip_type, "status": result.status, "source": result.source, "confidence": result.confidence, "matched_data": result.matched_data, "raw_response": result.raw_response, "error": result.error, "verification_time_ms": result.verification_time_ms}


@router.post("/initiate/{record_id}", status_code=status.HTTP_200_OK)
async def initiate_verification(request: Request, record_id: str, current_user: dict = Depends(get_current_user), source: str | None = Query(None), db: AsyncSession = Depends(get_async_session)):
    body = await request.json()
    service = VerificationService()
    result = await service.initiate_verification(ip_record_id=record_id, ip_type=body.get("ip_type", "PATENT"), identifier=body.get("identifier", ""), title=body.get("title"), applicant=body.get("applicant"), inventor=body.get("inventor"), filing_date=body.get("filing_date"), country=body.get("country"), requested_by=current_user.get("id"))
    return result


@router.get("/attempts", status_code=status.HTTP_200_OK)
async def list_verification_attempts(current_user: dict = Depends(get_current_user), record_id: str | None = Query(None), source: str | None = Query(None), status: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_async_session)):
    query = select(VerificationAttempt)
    if record_id:
        query = query.where(VerificationAttempt.ip_record_id == record_id)
    if source:
        query = query.where(VerificationAttempt.source == source)
    if status:
        query = query.where(VerificationAttempt.status == status)
    rows = await db.execute(query.order_by(VerificationAttempt.created_at.desc()).offset((page - 1) * per_page).limit(per_page))
    items = rows.mappings().all()
    return {"attempts": [dict(r) for r in items], "count": len(items), "page": page, "per_page": per_page}


@router.get("/attempts/{attempt_id}", status_code=status.HTTP_200_OK)
async def get_verification_attempt(attempt_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    attempt = (await db.execute(select(VerificationAttempt).where(VerificationAttempt.id == attempt_id))).scalar_one_or_none()
    if not attempt:
        raise NotFoundError("Verification attempt", attempt_id)
    return {"attempt_id": attempt.id, "status": attempt.status, "source": attempt.source, "created_at": attempt.created_at.isoformat() if attempt.created_at else None}


@router.post("/attempts/{attempt_id}/retry", status_code=status.HTTP_200_OK)
async def retry_verification(attempt_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    attempt = (await db.execute(select(VerificationAttempt).where(VerificationAttempt.id == attempt_id))).scalar_one_or_none()
    if not attempt:
        raise NotFoundError("Verification attempt", attempt_id)
    attempt.attempt_number += 1
    attempt.status = "UNVERIFIED"
    await db.commit()
    return {"attempt_id": attempt_id, "status": "retry_initiated"}

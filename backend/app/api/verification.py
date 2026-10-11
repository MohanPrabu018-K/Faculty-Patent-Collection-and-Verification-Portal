from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_async_session
from app.core.exceptions import AuthorizationError, NotFoundError, PortalError
from app.core.logging import log_audit
from app.verification.adapters import VerificationService, get_verification_registry, verify_patent_or_design
from app.models.base import (
    AssociationRequest,
    IpContributor,
    IpRecord,
    User,
    VerificationAttempt,
)

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
    attempts = rows.scalars().all()
    return {"attempts": [_attempt_to_dict(a) for a in attempts], "count": len(attempts), "page": page, "per_page": per_page}


def _attempt_to_dict(a: VerificationAttempt) -> dict:
    """Flatten one VerificationAttempt into JSON-serializable columns.

    ``select(Model)`` rows expose the instance under the model key, so the
    previous ``dict(row)`` produced nested ``{"VerificationAttempt": ...}``
    payloads that were not JSON-serializable. This returns the columns
    directly (same convention as admin ``_model_to_dict``).
    """
    from sqlalchemy import inspect as sa_inspect

    out: dict = {}
    for attr in sa_inspect(a).mapper.column_attrs:
        value = getattr(a, attr.key)
        out[attr.key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


def _enum_safe_verification_status(status: str | None) -> str:
    """Coerce an adapter status into the DB enum vocabulary (local copy of the
    orchestrator helper to avoid importing the worker module from the API)."""
    if status in ("VERIFIED", "MISMATCH", "UNVERIFIED"):
        return status
    return "VERIFICATION_REQUIRED"


@router.get("/attempts/{attempt_id}", status_code=status.HTTP_200_OK)
async def get_verification_attempt(attempt_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    attempt = (await db.execute(select(VerificationAttempt).where(VerificationAttempt.id == attempt_id))).scalar_one_or_none()
    if not attempt:
        raise NotFoundError("Verification attempt", attempt_id)
    return {"attempt_id": attempt.id, "status": attempt.status, "source": attempt.source, "created_at": attempt.created_at.isoformat() if attempt.created_at else None}


@router.post("/attempts/{attempt_id}/retry", status_code=status.HTTP_200_OK)
async def retry_verification(attempt_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    """Re-run automated official verification for the attempt's record.

    The previous implementation only bumped ``attempt_number`` and reset the
    old row to UNVERIFIED without contacting any verification source. This
    performs a real adapter lookup using the record's stored identifiers,
    persists a new attempt row, and refreshes the record's automated
    verification state. Institutional (HOD) history is never modified.
    """
    attempt = (await db.execute(select(VerificationAttempt).where(VerificationAttempt.id == attempt_id))).scalar_one_or_none()
    if not attempt:
        raise NotFoundError("Verification attempt", attempt_id)
    record = (await db.execute(select(IpRecord).where(IpRecord.id == attempt.ip_record_id))).scalar_one_or_none()
    if not record:
        raise NotFoundError("IP record", attempt.ip_record_id)
    identifier = record.patent_number or record.application_number or record.design_number or record.serial_number or ""
    result = await verify_patent_or_design(
        ip_type=record.ip_type or "PATENT",
        identifier=identifier,
        title=record.title,
        applicant=record.applicant,
    )
    new_no = (await db.execute(select(func.count()).select_from(VerificationAttempt).where(VerificationAttempt.ip_record_id == record.id))).scalar_one() + 1
    new_attempt = VerificationAttempt(
        id=str(uuid.uuid4()),
        ip_record_id=record.id,
        source=result.source,
        attempt_number=new_no,
        status=_enum_safe_verification_status(result.status),
        result=f"Retry of {attempt_id}: {result.status} (confidence {result.confidence})",
        evidence={"retried_from": attempt_id, "status": result.status, "confidence": result.confidence, "matched_data": result.matched_data, "error": result.error},
    )
    db.add(new_attempt)
    record.official_verification_status = _enum_safe_verification_status(result.status)
    await db.commit()
    log_audit(actor=current_user.get("id"), action="VERIFICATION_RETRIED", target_type="ip_record", target_id=record.id, status="success", extra={"from_attempt": attempt_id, "to_attempt": new_attempt.id, "status": result.status})
    return {"attempt_id": new_attempt.id, "retried_from": attempt_id, "status": result.status, "record_id": record.id}


# Source label for historical institutional (HOD manual) verification attempts.
# Retained so previously recorded decisions stay readable through the GET route.
INSTITUTIONAL_SOURCE = "institutional_hod"


async def _pending_internal_approvals(db: AsyncSession, record: IpRecord) -> list[str]:
    """Internal faculty whose acceptance is still outstanding for a record.

    Bug 3: HOD manual verification must not complete before required internal
    faculty acceptance. An approver is outstanding when they are an internal
    (non-external, user-linked, active) participant other than the uploader
    without an ACCEPTED/APPROVED association on this record (or its master),
    or when a PENDING/CLARIFICATION_REQUESTED request involving an active
    internal user is still open. Returns user ids ( [] means HOD may verify).
    """
    from sqlalchemy import or_

    outstanding: list[str] = []
    seen: set[str] = set()

    def _note(uid: str | None) -> None:
        if uid and uid not in seen:
            seen.add(uid)
            outstanding.append(uid)

    internal_rows = (
        await db.execute(
            select(IpContributor.user_id).where(
                IpContributor.ip_record_id == record.id,
                IpContributor.is_external.is_(False),
                IpContributor.user_id.is_not(None),
                IpContributor.user_id != record.uploader_id,
            )
        )
    ).scalars().all()
    internal_ids = [uid for uid in set(internal_rows) if uid]

    scope = AssociationRequest.ip_record_id == record.id
    if record.master_ip_id:
        scope = or_(scope, AssociationRequest.master_ip_id == record.master_ip_id)

    async def _has_accepted(uid: str) -> bool:
        pair = or_(
            or_(AssociationRequest.requesting_faculty_id == record.uploader_id, AssociationRequest.requester_id == record.uploader_id)
            & or_(AssociationRequest.target_faculty_id == uid, AssociationRequest.recipient_id == uid),
            or_(AssociationRequest.requesting_faculty_id == uid, AssociationRequest.requester_id == uid)
            & or_(AssociationRequest.target_faculty_id == record.uploader_id, AssociationRequest.recipient_id == record.uploader_id),
        )
        hit = (
            await db.execute(
                select(AssociationRequest).where(
                    pair, scope, AssociationRequest.status.in_(("ACCEPTED", "APPROVED"))
                ).limit(1)
            )
        ).scalar_one_or_none()
        return hit is not None

    users_by_id: dict[str, User] = {}
    if internal_ids:
        for u in (
            await db.execute(select(User).where(User.id.in_(internal_ids)))
        ).scalars().all():
            users_by_id[u.id] = u
    for uid in internal_ids:
        u = users_by_id.get(uid)
        if u is not None and not u.is_active:
            # Deactivated faculty can no longer accept (Bug 8 blocks new
            # requests); they must not hold HOD verification hostage.
            continue
        if not await _has_accepted(uid):
            _note(uid)

    # Item 4: the uploader approves by uploading ONLY while no request names
    # them. Once a request is addressed to the uploader (named contributor),
    # their explicit acceptance is required like everyone else's.
    uploader_open = (
        await db.execute(
            select(AssociationRequest).where(
                scope,
                AssociationRequest.status.in_(("PENDING", "CLARIFICATION_REQUESTED")),
                or_(
                    AssociationRequest.target_faculty_id == record.uploader_id,
                    AssociationRequest.recipient_id == record.uploader_id,
                ),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if uploader_open is not None and record.uploader_id:
        _note(record.uploader_id)

    # Requests that name an internal participant but have no contributor row
    # yet (e.g. identified purely via the request flow) still gate.
    open_rows = (
        await db.execute(
            select(AssociationRequest).where(
                scope,
                AssociationRequest.status.in_(("PENDING", "CLARIFICATION_REQUESTED")),
            )
        )
    ).scalars().all()
    party_ids: set[str] = set()
    for req in open_rows:
        for pid in (
            req.requesting_faculty_id, req.requester_id,
            req.target_faculty_id, req.recipient_id,
        ):
            if pid:
                party_ids.add(pid)
    party_ids.discard(record.uploader_id)
    if party_ids:
        for u in (
            await db.execute(select(User).where(User.id.in_(sorted(party_ids))))
        ).scalars().all():
            if u.is_active and u.id not in seen and not await _has_accepted(u.id):
                _note(u.id)

    return outstanding


def _institutional_to_dict(a: VerificationAttempt) -> dict:
    ev = a.evidence or {}
    return {
        "id": a.id,
        "ip_record_id": a.ip_record_id,
        "decision": ev.get("decision"),
        "verification_type": ev.get("verification_type", "INSTITUTIONAL_MANUAL_OFFICIAL_CHECK"),
        "status": a.status,
        "hod_user_id": ev.get("hod_user_id"),
        "hod_faculty_id": ev.get("hod_faculty_id"),
        "department_id": ev.get("department_id"),
        "remarks": ev.get("remarks"),
        "evidence_ref": ev.get("evidence_ref"),
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/institutional/{record_id}", status_code=status.HTTP_200_OK)
async def list_institutional_verifications(record_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    role = current_user.get("role", "")
    record = (await db.execute(select(IpRecord).where(IpRecord.id == record_id))).scalar_one_or_none()
    if not record:
        raise NotFoundError("IP record", record_id)
    if role == "faculty" and record.uploader_id != current_user.get("id"):
        raise AuthorizationError("Not authorized to view this record")
    if role == "hod_admin":
        hod_dept = current_user.get("department_id")
        if not hod_dept or (record.department_id and str(hod_dept) != str(record.department_id)):
            raise AuthorizationError("HOD can only view institutional verification for own department")
    rows = (await db.execute(select(VerificationAttempt).where(VerificationAttempt.ip_record_id == record_id, VerificationAttempt.source == INSTITUTIONAL_SOURCE).order_by(VerificationAttempt.created_at.desc()))).scalars().all()
    latest = _institutional_to_dict(rows[0]) if rows else None
    # Three-way distinction: the automated official state (preserved, never
    # overwritten by human review), the institutional HOD decision, and the
    # final decision (verification_status + workflow_state + evidence).
    official = record.official_verification_status or record.verification_status
    evidence = record.evidence or {}
    final = evidence.get("final_verification") if isinstance(evidence, dict) else None
    # Bug 3: expose outstanding internal approvals so the HOD UI can disable
    # "Confirm Verified" before required acceptance (backend still enforces).
    pending_approvals = await _pending_internal_approvals(db, record)
    # Staged workflow: expose the HOD association state so the UI can show
    # which HOD owns verification (or that HOD acceptance is still pending).
    from app.api.associations import _live_hod_request as _live_hod

    _hod_open = await _live_hod(db, record.id, record.master_ip_id)
    _hod_done = await _live_hod(db, record.id, record.master_ip_id, accepted_only=True)
    _hod_req = _hod_open or _hod_done
    _hod_uid = None
    _hod_name = None
    if _hod_req is not None:
        _hod_uid = _hod_req.responder_id or _hod_req.target_faculty_id or _hod_req.recipient_id
        _hod_user = (
            (await db.execute(select(User).where(User.id == _hod_uid))).scalar_one_or_none()
            if _hod_uid
            else None
        )
        _hod_name = _hod_user.full_name if _hod_user else None
    return {
        "record_id": record_id,
        "official_verification_status": official,
        "verification_status": record.verification_status,
        "workflow_state": record.workflow_state,
        "final_verification": final,
        "institutional": latest,
        "history": [_institutional_to_dict(r) for r in rows],
        "pending_approvals": pending_approvals,
        "hod_association": {
            "status": _hod_req.status if _hod_req else None,
            "hod_user_id": _hod_uid,
            "hod_name": _hod_name,
        },
    }


@router.post("/institutional/{record_id}", status_code=status.HTTP_405_METHOD_NOT_ALLOWED, include_in_schema=False)
async def submit_institutional_verification(record_id: str, current_user: dict = Depends(get_current_user)) -> None:
    """Manual institutional patent decisions are disabled.

    Grant / verify / accept / reject by a HOD or Super Admin were removed from
    the product. The route is kept as an explicit 405 (rather than deleted) so
    a direct API call can never silently succeed and clients get a clear
    signal. Institutional verification is now produced only by the automated
    pipeline; historical decisions remain readable via the GET route above.
    """
    raise PortalError(
        message=(
            "Manual institutional verification is disabled. Patent verification "
            "status is produced by the automated processing pipeline only."
        ),
        error_code="MANUAL_DECISION_DISABLED",
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    )

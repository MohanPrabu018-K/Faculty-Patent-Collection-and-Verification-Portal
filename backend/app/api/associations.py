from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user
from app.core.database import get_async_session
from app.core.exceptions import NotFoundError, PortalError
from app.core.logging import log_audit
from app.models.base import AssociationRequest, Department, IpContributor, IpRecord, User
from app.services.notifications import (
    NotificationPriority,
    NotificationType,
    get_notification_service,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/associations", tags=["associations"])

# Canonical workflow actions → DB enum status mapping.
_ACTION_STATUS_MAP = {
    "approved": "APPROVED",
    "accepted": "ACCEPTED",
    "rejected": "REJECTED",
    "not_me": "NOT_ME",
    "clarification_requested": "CLARIFICATION_REQUESTED",
}


def _assoc_row_to_dict(item: AssociationRequest, requester: User | None, recipient: User | None, record: IpRecord | None) -> dict:
    """Serialize an association request for the API, preserving the
    frontend-friendly field names."""
    return {
        "id": item.id,
        "record_id": record.id if record else item.ip_record_id,
        "record_title": record.title if record else None,
        "master_ip_id": item.master_ip_id,
        "contributor_id": item.contributor_id,
        "requester_id": item.requesting_faculty_id or item.requester_id,
        "requester_name": requester.full_name if requester else None,
        "requester_email": requester.email if requester else None,
        "recipient_id": item.target_faculty_id or item.recipient_id,
        "recipient_name": recipient.full_name if recipient else None,
        "recipient_email": recipient.email if recipient else None,
        "reason": item.reason,
        "message": item.message,
        "status": item.status,
        "response_reason": item.response_reason,
        "clarification_message": item.clarification_message,
        "responded_at": item.responded_at.isoformat() if item.responded_at else None,
        "reminder_sent_at": item.reminder_sent_at.isoformat() if item.reminder_sent_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


async def _association_stage(db: AsyncSession, request_obj: AssociationRequest) -> str:
    """Workflow stage of a request, derived live from the recipient's role.

    'HOD' when the recipient (target) is an active hod_admin, otherwise
    'FACULTY'. No schema column is needed: role is the source of truth, so
    promotion/demotion can never desynchronize a stored stage value.
    """
    target_id = request_obj.target_faculty_id or request_obj.recipient_id
    if not target_id:
        return "FACULTY"
    target = (await db.execute(select(User).where(User.id == target_id))).scalar_one_or_none()
    if target is not None and target.role == "hod_admin":
        return "HOD"
    return "FACULTY"


async def _live_hod_request(
    db: AsyncSession, record_id: str | None, master_ip_id: str | None, accepted_only: bool = False
) -> AssociationRequest | None:
    """The live HOD-stage request for a record, if any.

    HOD-stage = recipient is an hod_admin. With accepted_only, only an
    ACCEPTED/APPROVED one qualifies (the bound-HOD lookup).
    """
    if not record_id and not master_ip_id:
        return None
    scope = AssociationRequest.ip_record_id == record_id if record_id else False
    if master_ip_id:
        scope = or_(scope, AssociationRequest.master_ip_id == master_ip_id) if record_id else (AssociationRequest.master_ip_id == master_ip_id)
    statuses = ("ACCEPTED", "APPROVED") if accepted_only else ("PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW")
    rows = (
        await db.execute(select(AssociationRequest).where(scope, AssociationRequest.status.in_(statuses)))
    ).scalars().all()
    if not rows:
        return None
    target_ids = {r.target_faculty_id or r.recipient_id for r in rows} - {None}
    if not target_ids:
        return None
    hods = {
        u.id
        for u in (
            await db.execute(select(User).where(User.id.in_(sorted(target_ids)), User.role == "hod_admin"))
        ).scalars().all()
    }
    for req in rows:
        if (req.target_faculty_id or req.recipient_id) in hods:
            return req
    return None


def _is_live_pair_conflict(exc: BaseException) -> bool:
    """True when a failed INSERT hit the live-pair backstop index
    (``uq_assoc_live_pair_per_record``). Any other integrity error is a
    genuine bug and must propagate instead of becoming a 409."""
    return "uq_assoc_live_pair_per_record" in str(getattr(exc, "orig", exc))


async def _has_live_pair_request(
    db: AsyncSession, record: IpRecord, requester_id: str, target_id: str
) -> bool:
    """Any live (non-terminal) request between a pair on a record/master."""
    scope = AssociationRequest.ip_record_id == record.id
    if record.master_ip_id:
        scope = or_(scope, AssociationRequest.master_ip_id == record.master_ip_id)
    pair = or_(
        or_(AssociationRequest.requesting_faculty_id == requester_id, AssociationRequest.requester_id == requester_id)
        & or_(AssociationRequest.target_faculty_id == target_id, AssociationRequest.recipient_id == target_id),
        or_(AssociationRequest.requesting_faculty_id == target_id, AssociationRequest.requester_id == target_id)
        & or_(AssociationRequest.target_faculty_id == requester_id, AssociationRequest.recipient_id == requester_id),
    )
    hit = (
        await db.execute(
            select(AssociationRequest).where(
                pair,
                scope,
                AssociationRequest.status.in_(("PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW", "ACCEPTED", "APPROVED")),
            ).limit(1)
        )
    ).scalar_one_or_none()
    return hit is not None


async def _live_reviewer_request(db: AsyncSession, record: IpRecord, user_id: str):
    """Any live (non-terminal) request already addressed to a reviewer.

    Recipient-based idempotency for the exact business flow: exactly one live
    request per reviewer per record, regardless of who requested it.
    """
    scope = AssociationRequest.ip_record_id == record.id
    if record.master_ip_id:
        scope = or_(scope, AssociationRequest.master_ip_id == record.master_ip_id)
    return (
        await db.execute(
            select(AssociationRequest).where(
                scope,
                AssociationRequest.status.in_((
                    "PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW",
                    "ACCEPTED", "APPROVED",
                )),
                or_(
                    AssociationRequest.target_faculty_id == user_id,
                    AssociationRequest.recipient_id == user_id,
                ),
            ).limit(1)
        )
    ).scalar_one_or_none()


async def _other_internal_reviewers(db: AsyncSession, record: IpRecord) -> list[User]:
    """OTHER internal faculty who must approve a record (exact business rule).

    Excludes, always: the uploader (automatically accepted — NEVER receives a
    self-association request), external contributors, inactive users, and HOD
    accounts (HODs review via the per-department HOD-review stage, never as
    faculty approvers). Only user-linked INTERNAL_FACULTY contributors qualify.
    """
    from app.models.base import IpContributor as _IpContributor

    contribs = (
        await db.execute(
            select(_IpContributor).where(
                _IpContributor.ip_record_id == record.id,
                _IpContributor.is_external.is_(False),
                _IpContributor.user_id.is_not(None),
                _IpContributor.user_id != record.uploader_id,
            )
        )
    ).scalars().all()
    if not contribs:
        return []
    users = {
        u.id: u
        for u in (
            await db.execute(
                select(User).where(User.id.in_({c.user_id for c in contribs if c.user_id}))
            )
        ).scalars().all()
    }
    out = []
    for contrib in contribs:
        user = users.get(contrib.user_id or "")
        if user is None or not user.is_active:
            continue
        if user.role == "hod_admin":
            continue
        if user.id == record.uploader_id:
            continue
        if any(u.id == user.id for u in out):
            continue
        out.append(user)
    return out


async def _dispatch_faculty_review_requests(
    db: AsyncSession, record: IpRecord, requester_id: str
) -> dict:
    """Create faculty-stage requests to OTHER internal faculty (exact rule).

    Exactly one live request per reviewer (idempotent: existing live rows are
    reused, never duplicated). The uploader is NEVER included. Every NEWLY
    created recipient is notified. Returns {"created": [...newly created...],
    "covered": [...all reviewers with a live request...]}.
    """
    reviewers = await _other_internal_reviewers(db, record)
    created: list[str] = []
    covered: list[str] = []
    for user in reviewers:
        if await _has_live_pair_request(db, record, requester_id, user.id):
            if user.id not in covered:
                covered.append(user.id)
            continue
        if await _live_reviewer_request(db, record, user.id) is not None:
            if user.id not in covered:
                covered.append(user.id)
            continue
        # A9 backstop: the insert runs in a SAVEPOINT with an immediate
        # flush, so a concurrent duplicate for this reviewer rolls back only
        # this row (reported as already-covered) instead of failing the
        # whole batch at commit time. The notification is sent only after
        # the row survives, so a rolled-back request never notifies.
        try:
            async with db.begin_nested():
                db.add(
                    AssociationRequest(
                        id=str(uuid.uuid4()),
                        ip_record_id=record.id,
                        master_ip_id=record.master_ip_id,
                        requesting_faculty_id=requester_id,
                        target_faculty_id=user.id,
                        requester_id=requester_id,
                        recipient_id=user.id,
                        reason="Faculty association: named in the patent; explicit acceptance required",
                        status="PENDING",
                    )
                )
                await db.flush()
        except IntegrityError as exc:
            if not _is_live_pair_conflict(exc):
                raise
            if user.id not in covered:
                covered.append(user.id)
            continue
        await _notify(
            user.id,
            NotificationType.ASSOCIATION_REQUEST,
            "New association request",
            "You are named in a patent record. Please review and respond.",
            related_entity_id=record.id,
            priority=NotificationPriority.HIGH,
            action_url="/faculty/associations",
            action_label="Review request",
            metadata={"record_id": record.id},
        )
        created.append(user.id)
        covered.append(user.id)
    return {"created": created, "covered": covered}


async def _represented_department_ids(db: AsyncSession, record: IpRecord) -> list[str]:
    """Unique departments represented by internal faculty on a record.

    Union of the uploader's department and every user-linked internal
    contributor's department (active or not — representation is a fact about
    who is named, not about who can still act). External contributors NEVER
    create departments. Sorted for determinism.
    """
    from app.models.base import IpContributor as _IpContributor

    user_ids: set[str] = set()
    if record.uploader_id:
        user_ids.add(record.uploader_id)
    rows = (
        await db.execute(
            select(_IpContributor.user_id).where(
                _IpContributor.ip_record_id == record.id,
                _IpContributor.is_external.is_(False),
                _IpContributor.user_id.is_not(None),
            )
        )
    ).scalars().all()
    user_ids.update(uid for uid in rows if uid)
    if not user_ids:
        return []
    depts = {
        u.department_id
        for u in (
            await db.execute(select(User).where(User.id.in_(sorted(user_ids))))
        ).scalars().all()
        if u.department_id
    }
    if record.department_id:
        depts.add(record.department_id)
    return sorted(depts)


async def _complete_faculty_stage(db: AsyncSession, record: IpRecord, actor_id: str | None) -> dict:
    """Complete the faculty association stage (simplified business rule).

    Called only when every required OTHER-internal-faculty acceptance is
    recorded (or when no faculty stage is needed). Runs the automated
    pre-grant checks (identifier present, processing complete, uploader
    valid, no open duplicate/conflict). When all pass, advances
    FACULTY_ASSOCIATION_COMPLETE, marks verification VERIFIED, audits, and
    notifies the uploader that the patent is ready for Super Admin grant.
    Otherwise moves to NEEDS_REVIEW with the blocking reasons recorded
    honestly in evidence. No HOD request is created anywhere: HODs are
    read-only reviewers with department visibility. Returns a summary.
    """
    from app.services.workflow import advance_through

    from app.api.verification import _pending_internal_approvals

    state = record.workflow_state or ""
    pending = await _pending_internal_approvals(db, record)
    if pending:
        return {"completed": False, "pending": pending}
    missing: list[str] = []
    identifier = record.patent_number or record.application_number or record.design_number or record.serial_number
    if not identifier:
        missing.append("official/reference identifier available")
    if (record.processing_status or "") not in ("COMPLETED", "COMPLETED_WITH_ERRORS", "AWAITING_REVIEW"):
        missing.append("document processing completed")
    uploader = (
        (await db.execute(select(User).where(User.id == record.uploader_id))).scalar_one_or_none()
        if record.uploader_id else None
    )
    if uploader is None or not uploader.is_active:
        missing.append("uploader valid and active")
    if await _open_duplicate_or_conflict(db, record):
        missing.append("no open duplicate/conflict")
    if missing:
        record.workflow_state = advance_through(state, "NEEDS_REVIEW")
        evidence = dict(record.evidence or {})
        evidence["faculty_completion"] = {"blocked": missing}
        record.evidence = evidence
        log_audit(
            actor=actor_id or record.uploader_id or "system",
            action="FACULTY_ASSOCIATION_COMPLETE",
            target_type="ip_record",
            target_id=record.id,
            status="needs_review",
            after={"missing": missing},
        )
        return {"completed": False, "missing": missing}
    record.workflow_state = advance_through(state, "FACULTY_ASSOCIATION_COMPLETE")
    record.verification_status = "VERIFIED"
    log_audit(
        actor=actor_id or record.uploader_id or "system",
        action="FACULTY_ASSOCIATION_COMPLETE",
        target_type="ip_record",
        target_id=record.id,
        status="success",
    )
    if record.uploader_id:
        await _notify(
            record.uploader_id,
            NotificationType.VERIFICATION_COMPLETED,
            "Patent ready for Super Admin grant",
            f"'{record.title or record.patent_number or record.design_number or record.id}' passed all faculty and automated checks and is ready for Super Admin grant.",
            related_entity_id=record.id,
            priority=NotificationPriority.HIGH,
            action_url="/faculty/records",
            action_label="View record",
            metadata={"record_id": record.id},
        )
    return {"completed": True}


async def _open_duplicate_or_conflict(db: AsyncSession, record: IpRecord) -> bool:
    """True when an open duplicate or open high/medium conflict blocks grant.

    Mirrors the FinalVerificationAgent conditions in
    verification._reevaluate_final_after_institutional (same OPEN semantics).
    """
    from sqlalchemy import or_ as _or

    from app.models.base import ConflictCase as _Conflict
    from app.models.base import DuplicateCase as _Dup

    dup = (
        await db.execute(
            select(_Dup).where(
                _Dup.status == "OPEN",
                _or(_Dup.ip_record_id_1 == record.id, _Dup.ip_record_id_2 == record.id),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if dup is not None:
        return True
    conf = (
        await db.execute(
            select(_Conflict).where(
                _Conflict.ip_record_id == record.id,
                _Conflict.status == "OPEN",
                _Conflict.severity.in_(("high", "HIGH", "medium", "MEDIUM")),
            ).limit(1)
        )
    ).scalar_one_or_none()
    return conf is not None


async def _notify(
    user_id: str,
    notification_type: NotificationType,
    title: str,
    message: str,
    *,
    related_entity_type: str = "association_request",
    related_entity_id: str | None = None,
    priority: NotificationPriority = NotificationPriority.MEDIUM,
    action_url: str | None = None,
    action_label: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Best-effort persistent notification. Never fails the primary operation."""
    try:
        await get_notification_service().create_notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            action_url=action_url,
            action_label=action_label,
            metadata=metadata or {},
        )
    except Exception:  # pragma: no cover - notification failure is non-fatal
        logger.warning("notification_create_failed", user_id=user_id, type=notification_type.value)


async def _resolve_associated_record(db: AsyncSession, record_id: str) -> IpRecord | None:
    """Resolve an IpRecord (and prefer its master linkage) for an association."""
    if not record_id:
        return None
    return (
        await db.execute(select(IpRecord).where(IpRecord.id == record_id))
    ).scalar_one_or_none()


@router.get("/", status_code=status.HTTP_200_OK)
async def list_associations(current_user: dict = Depends(get_current_user), status_filter: str | None = Query(None, alias="status"), db: AsyncSession = Depends(get_async_session)):
    user_id = current_user.get("id")
    requester_alias = aliased(User)
    recipient_alias = aliased(User)
    query = (
        select(AssociationRequest, requester_alias, recipient_alias, IpRecord)
        .outerjoin(requester_alias, requester_alias.id == AssociationRequest.requesting_faculty_id)
        .outerjoin(recipient_alias, recipient_alias.id == AssociationRequest.target_faculty_id)
        .outerjoin(IpRecord, IpRecord.id == AssociationRequest.ip_record_id)
        .where(
            or_(
                AssociationRequest.requesting_faculty_id == user_id,
                AssociationRequest.target_faculty_id == user_id,
                AssociationRequest.requester_id == user_id,
                AssociationRequest.recipient_id == user_id,
            )
        )
    )
    if status_filter:
        query = query.where(AssociationRequest.status == status_filter.upper())
    rows = await db.execute(query.order_by(AssociationRequest.created_at.desc()))
    items = []
    for item, requester, recipient, record in rows.all():
        items.append(_assoc_row_to_dict(item, requester, recipient, record))
    return {"associations": items, "count": len(items)}


@router.get("/pending", status_code=status.HTTP_200_OK)
async def pending_associations(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    user_id = current_user.get("id")
    requester_alias = aliased(User)
    query = (
        select(AssociationRequest, requester_alias, IpRecord)
        .outerjoin(requester_alias, requester_alias.id == AssociationRequest.requesting_faculty_id)
        .outerjoin(IpRecord, IpRecord.id == AssociationRequest.ip_record_id)
        .where(
            or_(
                AssociationRequest.target_faculty_id == user_id,
                AssociationRequest.recipient_id == user_id,
            ),
            AssociationRequest.status == "PENDING",
        )
        .order_by(AssociationRequest.created_at.desc())
    )
    rows = await db.execute(query)
    items = []
    for item, requester, record in rows.all():
        items.append(_assoc_row_to_dict(item, requester, None, record))
    return {"requests": items, "count": len(items)}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def send_association_request(request: Request, recipient_faculty_id: str, reason: str = "", current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    record_id = body.get("record_id") or body.get("master_ip_id")
    if not record_id:
        raise PortalError(message="record_id is required", error_code="VALIDATION_ERROR", status_code=422)

    requester_id = current_user.get("id")
    recipient = (await db.execute(select(User).where(User.faculty_id == recipient_faculty_id))).scalar_one_or_none()
    if not recipient:
        raise NotFoundError("Faculty", recipient_faculty_id)
    # BUG 5: deactivated accounts cannot initiate new workflow actions.
    requester = (await db.execute(select(User).where(User.id == requester_id))).scalar_one_or_none()
    if requester is None or not requester.is_active:
        raise PortalError(message="Deactivated accounts cannot send association requests", error_code="AUTHORIZATION_ERROR", status_code=403)
    if recipient.id == requester_id:
        raise PortalError(message="Self-association is not allowed", error_code="VALIDATION_ERROR", status_code=400)
    # Bug 8: deactivated faculty must never receive association requests.
    # Backend enforcement (frontend also hides the action, but the API is the
    # gate). No request row and no notification are created for inactive users.
    if not recipient.is_active:
        raise PortalError(message="Association requests cannot be sent to deactivated faculty", error_code="VALIDATION_ERROR", status_code=422)

    record = await _resolve_associated_record(db, record_id)

    # Authoritative rule (B/D): only the record's uploader (or a super admin)
    # may initiate association requests, and requests may address OTHER
    # internal faculty only. HOD accounts are NEVER association recipients -
    # HODs are read-only (no HOD approval requests, no HOD accept/reject).
    if record is None:
        raise NotFoundError("IP record", record_id)
    if requester_id != record.uploader_id and current_user.get("role") != "super_admin":
        raise PortalError(
            message="Only the uploader may send association requests",
            error_code="AUTHORIZATION_ERROR",
            status_code=403,
        )
    if recipient.role == "hod_admin":
        raise PortalError(
            message="HOD accounts cannot receive association requests",
            error_code="VALIDATION_ERROR",
            status_code=422,
        )

    resolved_record_id = record.id if record else record_id
    # Staged workflow: faculty-stage requests stay blocked while the HOD
    # association for the record is still pending. Requests addressed to an
    # HOD are HOD-stage and are never blocked by this rule.
    if recipient.role != "hod_admin":
        pending_hod = await _live_hod_request(
            db, resolved_record_id, record.master_ip_id if record else None
        )
        if pending_hod is not None:
            raise PortalError(
                message="HOD association acceptance is required before faculty association requests",
                error_code="HOD_ASSOCIATION_PENDING",
                status_code=409,
            )
    duplicate = (
        await db.execute(
            select(AssociationRequest).where(
                AssociationRequest.ip_record_id == resolved_record_id,
                or_(
                    AssociationRequest.requesting_faculty_id == requester_id,
                    AssociationRequest.requester_id == requester_id,
                ),
                or_(
                    AssociationRequest.target_faculty_id == recipient.id,
                    AssociationRequest.recipient_id == recipient.id,
                ),
                AssociationRequest.status.in_(
                    ["PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW", "ACCEPTED", "APPROVED"]
                ),
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise PortalError(
            message=f"Association request already {duplicate.status} for this record and faculty",
            error_code="VALIDATION_ERROR",
            status_code=409,
        )

    association = AssociationRequest(
        id=str(uuid.uuid4()),
        ip_record_id=record.id if record else record_id,
        master_ip_id=record.master_ip_id if record else None,
        requesting_faculty_id=requester_id,
        target_faculty_id=recipient.id,
        requester_id=requester_id,
        recipient_id=recipient.id,
        reason=reason,
        message=body.get("message", ""),
        status="PENDING",
    )
    db.add(association)
    # A9 backstop: a concurrent identical request may have committed between
    # the app-level duplicate check and this commit. The partial unique
    # index rejects it; translate that into the same deterministic 409 the
    # app-level check returns (never a 500). Any other integrity error is a
    # genuine bug and propagates.
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if not _is_live_pair_conflict(exc):
            raise
        raise PortalError(
            message="Association request already exists for this record and faculty (concurrent request)",
            error_code="VALIDATION_ERROR",
            status_code=409,
        ) from exc

    log_audit(
        actor=requester_id,
        action="ASSOCIATION_REQUEST_CREATED",
        target_type="association_request",
        target_id=association.id,
        status="pending",
        after={"record_id": record_id, "recipient_faculty_id": recipient_faculty_id},
    )

    await _notify(
        recipient.id,
        NotificationType.ASSOCIATION_REQUEST,
        "New association request",
        f"{current_user.get('full_name', 'A faculty member')} requested to associate you with a patent/design record.",
        related_entity_id=association.id,
        priority=NotificationPriority.HIGH,
        action_url="/faculty/associations",
        action_label="Review request",
        metadata={"request_id": association.id, "record_id": record_id},
    )

    return _assoc_row_to_dict(association, None, recipient, record)


@router.post("/send-all", status_code=status.HTTP_200_OK)
async def send_all_association_requests(request: Request, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    """Uploader's explicit [Send Association Request] action (exact rule).

    Sends requests ONLY to OTHER internal faculty contributors — never to
    the uploader (automatically accepted), never to externals, never to
    inactive users or HOD accounts. Idempotent: reviewers already covered by
    a live request are reported, never duplicated. When no other internal
    faculty exist, the faculty stage completes immediately and HOD routing
    proceeds.
    """
    from app.services.workflow import advance_through

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    record_id = body.get("record_id") or body.get("master_ip_id")
    if not record_id:
        raise PortalError(message="record_id is required", error_code="VALIDATION_ERROR", status_code=422)
    requester_id = current_user.get("id")
    requester = (await db.execute(select(User).where(User.id == requester_id))).scalar_one_or_none()
    if requester is None or not requester.is_active:
        raise PortalError(message="Deactivated accounts cannot send association requests", error_code="AUTHORIZATION_ERROR", status_code=403)
    record = await _resolve_associated_record(db, record_id)
    if record is None:
        raise NotFoundError("IP record", record_id)
    if requester_id != record.uploader_id and current_user.get("role") != "super_admin":
        raise PortalError(message="Only the uploader may send association requests", error_code="AUTHORIZATION_ERROR", status_code=403)
    # Legacy in-flight records in the old association-pending family normalize
    # into the simplified flow on next Send (audited, no history deleted).
    if (record.workflow_state or "") not in (
        "FACULTY_ASSOCIATION_PENDING", "FACULTY_APPROVAL_PENDING",
        "HOD_ASSOCIATION_PENDING", "HOD_ASSOCIATION_ACCEPTED",
    ):
        raise PortalError(
            message="Association requests can only be sent while faculty association is pending",
            error_code="VALIDATION_ERROR",
            status_code=409,
            details={"workflow_state": record.workflow_state},
        )
    reviewers = await _other_internal_reviewers(db, record)
    if (record.workflow_state or "") != "FACULTY_ASSOCIATION_PENDING":
        # Normalize legacy in-flight states into the simplified flow.
        from app.services.workflow import advance_through

        record.workflow_state = advance_through(record.workflow_state, "FACULTY_ASSOCIATION_PENDING")
    if not reviewers:
        completion = await _complete_faculty_stage(db, record, requester_id)
        await db.commit()
        return {
            "record_id": record.id,
            "uploader": {"id": record.uploader_id, "status": "AUTO_ACCEPTED"},
            "created": [],
            "already_pending": [],
            "workflow_state": record.workflow_state,
            "faculty_completion": completion,
        }
    already = []
    for user in reviewers:
        live = (
            await db.execute(
                select(AssociationRequest).where(
                    AssociationRequest.ip_record_id == record.id,
                    AssociationRequest.status.in_(("PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW", "ACCEPTED", "APPROVED")),
                    or_(
                        AssociationRequest.target_faculty_id == user.id,
                        AssociationRequest.recipient_id == user.id,
                    ),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if live is not None and user.id not in already:
            already.append(user.id)
    created = (await _dispatch_faculty_review_requests(db, record, requester_id))["created"]
    log_audit(
        actor=requester_id,
        action="ASSOCIATION_REQUEST_SENT",
        target_type="ip_record",
        target_id=record.id,
        status="success",
        after={"created": created, "already_pending": already,
               "uploader": {"id": record.uploader_id, "status": "AUTO_ACCEPTED"}},
    )
    await db.commit()
    return {
        "record_id": record.id,
        "uploader": {"id": record.uploader_id, "status": "AUTO_ACCEPTED"},
        "created": created,
        "already_pending": already,
        "workflow_state": record.workflow_state,
    }


@router.post("/{request_id}/respond", status_code=status.HTTP_200_OK)
async def respond_association_request(request: Request, request_id: str, action: str = Query(..., pattern="^(approved|accepted|rejected|not_me|clarification_requested)$"), current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    request_obj = (await db.execute(select(AssociationRequest).where(AssociationRequest.id == request_id))).scalar_one_or_none()
    if not request_obj:
        raise NotFoundError("Association request", request_id)

    responder_id = current_user.get("id")
    target_id = request_obj.target_faculty_id or request_obj.recipient_id
    if target_id != responder_id:
        raise PortalError(message="Only the recipient may respond", error_code="AUTHORIZATION_ERROR", status_code=403)

    # BUG 5: deactivated accounts cannot perform verification actions,
    # including accepting/rejecting association requests.
    responder = (await db.execute(select(User).where(User.id == responder_id))).scalar_one_or_none()
    if responder is None or not responder.is_active:
        raise PortalError(message="Deactivated accounts cannot respond to association requests", error_code="AUTHORIZATION_ERROR", status_code=403)
    # HODs are strictly read-only: they never accept/reject association
    # requests (rule D). This mirrors the frontend, which already hides the
    # decision action for HOD accounts.
    if responder.role == "hod_admin":
        raise PortalError(message="HOD accounts cannot respond to association requests", error_code="AUTHORIZATION_ERROR", status_code=403)

    if request_obj.status not in ("PENDING", "CLARIFICATION_REQUESTED"):
        raise PortalError(message=f"Request already {request_obj.status}", error_code="VALIDATION_ERROR", status_code=409)

    old_status = request_obj.status
    new_status = _ACTION_STATUS_MAP[action]
    request_obj.status = new_status
    request_obj.responder_id = responder_id
    request_obj.responded_at = datetime.now(UTC).replace(tzinfo=None)
    request_obj.responded_at_timestamp = datetime.now(UTC).replace(tzinfo=None)

    if action == "clarification_requested":
        request_obj.clarification_message = body.get("reason") or body.get("message")
        request_obj.response_reason = body.get("reason")
    else:
        request_obj.response_reason = body.get("reason")

    # An accepted association links the recipient as an internal contributor
    # in the SAME transaction (dashboards are uploader-OR-contributor scoped).
    # HOD reviewers are NEVER linked as faculty contributors: their decision
    # flows through the HOD-review stage, and linking them would corrupt the
    # faculty-approval counts.
    if action in ("accepted", "approved") and request_obj.ip_record_id and responder.role != "hod_admin":
        existing_link = (
            await db.execute(
                select(IpContributor).where(
                    IpContributor.ip_record_id == request_obj.ip_record_id,
                    IpContributor.user_id == responder_id,
                )
            )
        ).scalar_one_or_none()
        if existing_link is None:
            db.add(
                IpContributor(
                    id=str(uuid.uuid4()),
                    ip_record_id=request_obj.ip_record_id,
                    user_id=responder_id,
                    name=responder.full_name or responder.email,
                    contributor_type="INTERNAL_FACULTY",
                    match_status="ACCEPTED",
                    source="ASSOCIATION_ACCEPT",
                    is_external=False,
                )
            )

    # Simplified business workflow drive. HOD recipients have NO approval
    # action: their accept/reject only changes the request row (audited
    # below) and never touches record state. Faculty acceptances drive the
    # record toward faculty-stage completion. Everything below stays in the
    # same transaction as the status change; master-only requests keep the
    # legacy status-only behavior.
    if action in ("accepted", "approved"):
        stage = await _association_stage(db, request_obj)
        record = None
        if request_obj.ip_record_id:
            record = (
                await db.execute(select(IpRecord).where(IpRecord.id == request_obj.ip_record_id))
            ).scalar_one_or_none()
        if record is not None and stage != "HOD" and (record.workflow_state or "") in (
            "FACULTY_ASSOCIATION_PENDING",
            "FACULTY_APPROVAL_PENDING",
            "FACULTY_APPROVED",
            "HOD_VERIFICATION_PENDING",
            "HOD_ASSOCIATION_ACCEPTED",
        ):
            from app.api.verification import _pending_internal_approvals

            if not await _pending_internal_approvals(db, record):
                await _complete_faculty_stage(db, record, responder_id)

    if action == "rejected":
        stage = await _association_stage(db, request_obj)
        record = None
        if request_obj.ip_record_id:
            record = (
                await db.execute(select(IpRecord).where(IpRecord.id == request_obj.ip_record_id))
            ).scalar_one_or_none()
        if record is not None and stage != "HOD" and (record.workflow_state or "") not in ("REJECTED", "GRANTED", "VERIFIED"):
            from app.services.workflow import advance_through

            record.workflow_state = advance_through(record.workflow_state, "NEEDS_REVIEW")

    if action == "not_me":
        record = None
        if request_obj.ip_record_id:
            record = (
                await db.execute(select(IpRecord).where(IpRecord.id == request_obj.ip_record_id))
            ).scalar_one_or_none()
        if record is not None and (record.workflow_state or "") not in ("REJECTED", "GRANTED", "VERIFIED"):
            from app.services.workflow import advance_through

            # Identity dispute: never guess — route to review.
            record.workflow_state = advance_through(record.workflow_state, "NEEDS_REVIEW")

    await db.commit()

    log_audit(
        actor=responder_id,
        action=f"ASSOCIATION_REQUEST_{action.upper()}",
        target_type="association_request",
        target_id=request_id,
        status=new_status.lower(),
        before={"status": old_status},
        after={"status": new_status, "reason": request_obj.response_reason},
    )

    requester_id = request_obj.requesting_faculty_id or request_obj.requester_id
    if requester_id and requester_id != responder_id:
        if action in ("approved", "accepted"):
            await _notify(
                requester_id,
                NotificationType.ASSOCIATION_APPROVED,
                "Association request approved",
                f"{current_user.get('full_name', 'A faculty member')} approved your association request.",
                related_entity_id=request_id,
                priority=NotificationPriority.MEDIUM,
                action_url="/faculty/associations",
                action_label="View",
                metadata={"request_id": request_id},
            )
        elif action == "rejected":
            await _notify(
                requester_id,
                NotificationType.ASSOCIATION_REJECTED,
                "Association request declined",
                f"{current_user.get('full_name', 'A faculty member')} declined your association request.",
                related_entity_id=request_id,
                metadata={"request_id": request_id},
            )
        elif action == "not_me":
            await _notify(
                requester_id,
                NotificationType.ASSOCIATION_NOT_ME,
                "Association marked as 'Not me'",
                f"{current_user.get('full_name', 'A faculty member')} indicated this record is not theirs.",
                related_entity_id=request_id,
                priority=NotificationPriority.HIGH,
                action_url="/faculty/associations",
                action_label="Review",
                metadata={"request_id": request_id},
            )
        elif action == "clarification_requested":
            await _notify(
                requester_id,
                NotificationType.ASSOCIATION_CLARIFICATION,
                "Clarification requested",
                f"{current_user.get('full_name', 'A faculty member')} requested more information.",
                related_entity_id=request_id,
                metadata={"request_id": request_id, "message": request_obj.clarification_message},
            )

    return {"request_id": request_id, "status": new_status, "message": "Association request updated"}


@router.post("/{request_id}/clarify", status_code=status.HTTP_200_OK)
async def respond_to_clarification(request: Request, request_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    """Requester responds to a clarification request, returning it to PENDING."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    request_obj = (await db.execute(select(AssociationRequest).where(AssociationRequest.id == request_id))).scalar_one_or_none()
    if not request_obj:
        raise NotFoundError("Association request", request_id)

    requester_id = current_user.get("id")
    if (request_obj.requesting_faculty_id or request_obj.requester_id) != requester_id:
        raise PortalError(message="Only the requester may respond to clarification", error_code="AUTHORIZATION_ERROR", status_code=403)

    if request_obj.status != "CLARIFICATION_REQUESTED":
        raise PortalError(message="No clarification requested", error_code="VALIDATION_ERROR", status_code=409)

    request_obj.message = body.get("message") or request_obj.message
    request_obj.status = "PENDING"
    await db.commit()

    log_audit(
        actor=requester_id,
        action="ASSOCIATION_CLARIFICATION_PROVIDED",
        target_type="association_request",
        target_id=request_id,
        status="pending",
        after={"message": request_obj.message},
    )

    target_id = request_obj.target_faculty_id or request_obj.recipient_id
    if target_id:
        await _notify(
            target_id,
            NotificationType.ASSOCIATION_CLARIFICATION,
            "Clarification provided",
            f"{current_user.get('full_name', 'A faculty member')} responded to your clarification request.",
            related_entity_id=request_id,
            priority=NotificationPriority.HIGH,
            action_url=f"/associations?request={request_id}",
            action_label="Review",
            metadata={"request_id": request_id},
        )

    return {"request_id": request_id, "status": "PENDING", "message": "Clarification recorded"}


@router.post("/{request_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_association_request(request_id: str, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_async_session)):
    """Requester cancels a pending request."""
    request_obj = (await db.execute(select(AssociationRequest).where(AssociationRequest.id == request_id))).scalar_one_or_none()
    if not request_obj:
        raise NotFoundError("Association request", request_id)

    requester_id = current_user.get("id")
    if (request_obj.requesting_faculty_id or request_obj.requester_id) != requester_id:
        raise PortalError(message="Only the requester may cancel", error_code="AUTHORIZATION_ERROR", status_code=403)

    if request_obj.status != "PENDING":
        raise PortalError(message="Only pending requests can be cancelled", error_code="VALIDATION_ERROR", status_code=409)

    request_obj.status = "CANCELLED"
    await db.commit()

    log_audit(
        actor=requester_id,
        action="ASSOCIATION_REQUEST_CANCELLED",
        target_type="association_request",
        target_id=request_id,
        status="cancelled",
    )

    return {"request_id": request_id, "status": "CANCELLED", "message": "Association request cancelled"}

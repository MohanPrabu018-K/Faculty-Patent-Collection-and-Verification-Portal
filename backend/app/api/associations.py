from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user
from app.core.database import get_async_session
from app.core.exceptions import NotFoundError, PortalError
from app.core.logging import log_audit
from app.models.base import AssociationRequest, IpContributor, IpRecord, User
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


async def _dispatch_faculty_requests(
    db: AsyncSession, hod_request: AssociationRequest, record: IpRecord, hod_user_id: str
) -> list[str]:
    """Create faculty-stage requests after an HOD acceptance (items 2/4).

    One request per internal contributor (non-external, user-linked, active),
    INCLUDING the uploader when their identity is linked to a contributor row
    — item 4: the uploader is asked because they are named, never merely for
    uploading. Self-requests (requester == recipient == uploader) are created
    only by this system path; the manual endpoints keep rejecting them.
    Returns the recipient user ids that now have a live request.
    """
    from app.models.base import IpContributor as _IpContributor

    contribs = (
        await db.execute(
            select(_IpContributor).where(
                _IpContributor.ip_record_id == record.id,
                _IpContributor.is_external.is_(False),
                _IpContributor.user_id.is_not(None),
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
    requester_id = record.uploader_id or hod_user_id
    created: list[str] = []
    for contrib in contribs:
        uid = contrib.user_id
        if not uid or uid == hod_user_id:
            continue
        user = users.get(uid)
        if user is None or not user.is_active:
            continue
        if await _has_live_pair_request(db, record, requester_id, uid):
            if uid not in created:
                created.append(uid)
            continue
        db.add(
            AssociationRequest(
                id=str(uuid.uuid4()),
                ip_record_id=record.id,
                master_ip_id=record.master_ip_id,
                requesting_faculty_id=requester_id,
                target_faculty_id=uid,
                requester_id=requester_id,
                recipient_id=uid,
                reason="Faculty association: named in the patent; acceptance required before HOD verification",
                status="PENDING",
            )
        )
        if uid != requester_id:
            await _notify(
                uid,
                NotificationType.ASSOCIATION_REQUEST,
                "New association request",
                "You are named in a patent record. Please review and respond.",
                related_entity_id=record.id,
                priority=NotificationPriority.HIGH,
                action_url="/faculty/associations",
                action_label="Review request",
                metadata={"record_id": record.id},
            )
        created.append(uid)
    return created


async def _notify_hod_ready(db: AsyncSession, record: IpRecord, hod_user_id: str | None) -> None:
    """Tell the bound HOD the record is ready for manual verification."""
    if not hod_user_id:
        return
    hod = (await db.execute(select(User).where(User.id == hod_user_id))).scalar_one_or_none()
    if hod is None or not hod.is_active:
        return
    await _notify(
        hod_user_id,
        NotificationType.HOD_VERIFICATION_READY,
        "Patent ready for manual verification",
        f"'{record.title or record.patent_number or record.design_number or record.id}' has all required association approvals and is ready for your manual verification.",
        related_entity_id=record.id,
        priority=NotificationPriority.HIGH,
        action_url="/hod/documents",
        action_label="Review documents",
        metadata={"record_id": record.id},
    )


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
    if recipient.id == requester_id:
        raise PortalError(message="Self-association is not allowed", error_code="VALIDATION_ERROR", status_code=400)
    # Bug 8: deactivated faculty must never receive association requests.
    # Backend enforcement (frontend also hides the action, but the API is the
    # gate). No request row and no notification are created for inactive users.
    if not recipient.is_active:
        raise PortalError(message="Association requests cannot be sent to deactivated faculty", error_code="VALIDATION_ERROR", status_code=422)

    record = await _resolve_associated_record(db, record_id)

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
    await db.commit()

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

    # Bug 1: an accepted/approved association must link the recipient to the
    # record as an internal contributor in the SAME transaction as the status
    # change. Dashboard/profile/records queries are uploader-OR-contributor
    # scoped, so the accepted patent appears for Faculty B immediately and
    # survives refresh and new sessions (backend is source of truth).
    if action in ("accepted", "approved") and request_obj.ip_record_id:
        existing_link = (
            await db.execute(
                select(IpContributor).where(
                    IpContributor.ip_record_id == request_obj.ip_record_id,
                    IpContributor.user_id == responder_id,
                )
            )
        ).scalar_one_or_none()
        if existing_link is None:
            responder = (
                await db.execute(select(User).where(User.id == responder_id))
            ).scalar_one_or_none()
            if responder is not None and responder.is_active:
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

    # Staged workflow (items 2/4/9/10): drive record workflow, fan out
    # faculty requests on HOD acceptance, and notify the bound HOD when the
    # record becomes ready for manual verification. Everything below stays in
    # the same transaction as the status change; master-only requests keep
    # the legacy status-only behavior.
    if action in ("accepted", "approved"):
        stage = await _association_stage(db, request_obj)
        record = None
        if request_obj.ip_record_id:
            record = (
                await db.execute(select(IpRecord).where(IpRecord.id == request_obj.ip_record_id))
            ).scalar_one_or_none()
        if record is not None:
            from app.services.workflow import advance_through

            if stage == "HOD":
                record.workflow_state = advance_through(record.workflow_state, "HOD_ASSOCIATION_ACCEPTED")
                faculty_uids = await _dispatch_faculty_requests(db, request_obj, record, responder_id)
                if faculty_uids:
                    record.workflow_state = advance_through(record.workflow_state, "FACULTY_APPROVAL_PENDING")
                else:
                    # No internal faculty to approve: the record is ready for
                    # the bound HOD immediately.
                    record.workflow_state = advance_through(record.workflow_state, "HOD_VERIFICATION_PENDING")
                    await _notify_hod_ready(db, record, responder_id)
            else:
                bound = await _live_hod_request(db, record.id, record.master_ip_id, accepted_only=True)
                if bound is not None:
                    from app.api.verification import _pending_internal_approvals

                    if not await _pending_internal_approvals(db, record):
                        record.workflow_state = advance_through(record.workflow_state, "HOD_VERIFICATION_PENDING")
                        bound_hod = bound.responder_id or bound.target_faculty_id or bound.recipient_id
                        await _notify_hod_ready(db, record, bound_hod)

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

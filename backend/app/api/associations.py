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
from app.models.base import AssociationRequest, IpRecord, User
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

    record = await _resolve_associated_record(db, record_id)

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
        action_url=f"/associations?request={association.id}",
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
                action_url=f"/associations?request={request_id}",
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
                action_url="/associations",
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

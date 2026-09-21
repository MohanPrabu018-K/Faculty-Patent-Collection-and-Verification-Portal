from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import structlog
from app.core.database import get_session
from app.core.logging import log_audit
from app.models.base import AssociationRequest, User
from app.services.notifications import get_notification_service, NotificationType, NotificationPriority

logger = structlog.get_logger()

# Association reminder/expiry configuration
DEFAULT_ASSOCIATION_EXPIRY_DAYS = 14
REMINDER_BEFORE_EXPIRY_DAYS = 3


# --- Data Classes ---

class AssociationStatus(Enum):
    """Status of an association request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CLARIFICATION_REQUESTED = "clarification_requested"
    CANCELLED = "cancelled"


class AssociationRole(Enum):
    """Role in association."""
    REQUESTER = "requester"
    RECIPIENT = "recipient"
    CO_OWNER = "co_owner"
    CONTRIBUTOR = "contributor"


@dataclass
class AssociationRequest:
    """An association request between faculty members."""
    id: str
    record_id: str  # IP record this association is for
    requester_id: str
    requester_name: str
    requester_email: str
    recipient_id: str
    recipient_name: str
    recipient_email: str
    
    # Request details
    role: AssociationRole = AssociationRole.CO_OWNER
    reason: str = ""
    message: str = ""
    
    # Status
    status: AssociationStatus = AssociationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    # Response
    response_reason: str | None = None
    response_message: str | None = None
    responded_at: datetime | None = None
    responded_by: str | None = None
    
    # Clarification
    clarification_requested_at: datetime | None = None
    clarification_response: str | None = None
    clarification_responded_at: datetime | None = None
    
    # History
    history: list[dict[str, Any]] = field(default_factory=list)


# --- Association Service ---

class AssociationService:
    """Service for managing association requests."""
    
    def __init__(self):
        self.logger = logger.bind(service="association")
        self._requests: dict[str, AssociationRequest] = {}  # In-memory for testing
    
    async def create_association_request(
        self,
        record_id: str,
        requester_id: str,
        requester_name: str,
        requester_email: str,
        recipient_id: str,
        recipient_name: str,
        recipient_email: str,
        role: str = "co_owner",
        reason: str = "",
        message: str = "",
    ) -> dict[str, Any]:
        """Create a new association request."""
        request = AssociationRequest(
            id=f"assoc-{requester_id}-{recipient_id}-{int(time.time())}",
            record_id=record_id,
            requester_id=requester_id,
            requester_name=requester_name,
            requester_email=requester_email,
            recipient_id=recipient_id,
            recipient_name=recipient_name,
            recipient_email=recipient_email,
            role=AssociationRole(role) if role in [r.value for r in AssociationRole] else AssociationRole.CO_OWNER,
            reason=reason,
            message=message,
            status=AssociationStatus.PENDING,
        )
        
        self._requests[request.id] = request
        
        # Add to history
        self._add_history(request, "created", requester_id, "Association request created")
        
        # Log audit
        log_audit(
            actor=requester_id,
            action="ASSOCIATION_REQUEST_CREATED",
            target_type="association_request",
            target_id=request.id,
            status="pending",
            extra={
                "record_id": record_id,
                "requester_id": requester_id,
                "recipient_id": recipient_id,
                "role": role,
            },
        )
        
        # In production, send notification to recipient
        await self._notify_recipient(request)
        
        return self._request_to_dict(request)
    
    async def respond_to_request(
        self,
        request_id: str,
        responder_id: str,
        action: str,  # approve, reject, request_clarification
        reason: str = "",
        message: str = "",
    ) -> dict[str, Any]:
        """Respond to an association request."""
        request = self._requests.get(request_id)
        if not request:
            raise ValueError(f"Association request {request_id} not found")
        
        if request.status != AssociationStatus.PENDING:
            raise ValueError(f"Request already {request.status.value}")
        
        if responder_id != request.recipient_id:
            raise ValueError("Only recipient can respond to association request")
        
        old_status = request.status
        
        if action == "approve":
            request.status = AssociationStatus.APPROVED
            request.response_reason = reason
            request.response_message = message
            request.responded_at = datetime.now(UTC)
            request.responded_by = responder_id
            self._add_history(request, "approved", responder_id, reason or "Approved")
            
        elif action == "reject":
            request.status = AssociationStatus.REJECTED
            request.response_reason = reason
            request.response_message = message
            request.responded_at = datetime.now(UTC)
            request.responded_by = responder_id
            self._add_history(request, "rejected", responder_id, reason or "Rejected")
            
        elif action == "request_clarification":
            request.status = AssociationStatus.CLARIFICATION_REQUESTED
            request.clarification_requested_at = datetime.now(UTC)
            request.clarification_response = reason
            self._add_history(request, "clarification_requested", responder_id, reason)
            
        else:
            raise ValueError(f"Invalid action: {action}")
        
        request.updated_at = datetime.now(UTC)
        
        # Log audit
        log_audit(
            actor=responder_id,
            action=f"ASSOCIATION_REQUEST_{action.upper()}",
            target_type="association_request",
            target_id=request_id,
            status=request.status.value,
            before={"status": old_status.value},
            after={"status": request.status.value, "reason": reason},
            extra={
                "record_id": request.record_id,
                "requester_id": request.requester_id,
                "recipient_id": responder_id,
            },
        )
        
        # Notify requester
        await self._notify_requester(request, action)
        
        return self._request_to_dict(request)
    
    async def request_clarification_response(
        self,
        request_id: str,
        requester_id: str,
        clarification: str,
    ) -> dict[str, Any]:
        """Requester responds to clarification request."""
        request = self._requests.get(request_id)
        if not request:
            raise ValueError(f"Association request {request_id} not found")
        
        if request.status != AssociationStatus.CLARIFICATION_REQUESTED:
            raise ValueError("No clarification requested")
        
        if requester_id != request.requester_id:
            raise ValueError("Only requester can respond to clarification")
        
        request.clarification_response = clarification
        request.clarification_responded_at = datetime.now(UTC)
        request.updated_at = datetime.now(UTC)
        
        # After clarification, status goes back to pending
        old_status = request.status
        request.status = AssociationStatus.PENDING
        
        self._add_history(request, "clarification_provided", requester_id, clarification)
        
        log_audit(
            actor=requester_id,
            action="ASSOCIATION_CLARIFICATION_PROVIDED",
            target_type="association_request",
            target_id=request.id,
            status="pending",
            before={"status": "clarification_requested"},
            after={"status": "pending", "clarification": True},
            extra={"clarification": clarification[:100]},
        )
        
        # Notify recipient
        await self._notify_recipient(request, "clarification_response")
        
        return self._request_to_dict(request)
    
    async def cancel_request(self, request_id: str, user_id: str) -> dict[str, Any]:
        """Cancel an association request (by requester)."""
        request = self._requests.get(request_id)
        if not request:
            raise ValueError(f"Association request {request_id} not found")
        
        if request.requester_id != user_id:
            raise ValueError("Only requester can cancel")
        
        if request.status != AssociationStatus.PENDING:
            raise ValueError("Can only cancel pending requests")
        
        old_status = request.status
        request.status = AssociationStatus.CANCELLED
        request.updated_at = datetime.now(UTC)
        self._add_history(request, "cancelled", user_id, "Cancelled by requester")
        
        log_audit(
            actor=user_id,
            action="ASSOCIATION_REQUEST_CANCELLED",
            target_type="association_request",
            target_id=request.id,
            status="cancelled",
            before={"status": old_status.value},
            after={"status": "cancelled"},
        )
        
        # Notify recipient
        await self._notify_recipient(request, "cancelled")
        
        return self._request_to_dict(request)
    
    def get_request(self, request_id: str) -> dict[str, Any] | None:
        """Get a single association request."""
        request = self._requests.get(request_id)
        if request:
            return self._request_to_dict(request)
        return None
    
    def list_requests(
        self,
        user_id: str,
        role: str = "all",  # requester, recipient, all
        status: str | None = None,
        record_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List association requests for a user."""
        results = []
        
        for request in self._requests.values():
            # Filter by user role
            if role == "requester" and request.requester_id != user_id:
                continue
            if role == "recipient" and request.recipient_id != user_id:
                continue
            if role == "all" and request.requester_id != user_id and request.recipient_id != user_id:
                continue
            
            # Filter by status
            if status and request.status.value != status:
                continue
            
            # Filter by record
            if record_id and request.record_id != record_id:
                continue
            
            results.append(self._request_to_dict(request))
        
        # Sort by created_at descending
        results.sort(key=lambda r: r["created_at"], reverse=True)
        return results
    
    def get_requests_for_record(self, record_id: str) -> list[dict[str, Any]]:
        """Get all association requests for a specific IP record."""
        return [
            self._request_to_dict(r) for r in self._requests.values()
            if r.record_id == record_id
        ]
    
    def _add_history(self, request: AssociationRequest, action: str, actor_id: str, details: str):
        """Add entry to request history."""
        request.history.append({
            "action": action,
            "actor_id": actor_id,
            "details": details,
            "timestamp": datetime.now(UTC).isoformat(),
        })
    
    def _request_to_dict(self, request: AssociationRequest) -> dict[str, Any]:
        """Convert request to dictionary."""
        return {
            "id": request.id,
            "record_id": request.record_id,
            "requester": {
                "id": request.requester_id,
                "name": request.requester_name,
                "email": request.requester_email,
            },
            "recipient": {
                "id": request.recipient_id,
                "name": request.recipient_name,
                "email": request.recipient_email,
            },
            "role": request.role.value,
            "reason": request.reason,
            "message": request.message,
            "status": request.status.value,
            "created_at": request.created_at.isoformat(),
            "updated_at": request.updated_at.isoformat(),
            "response_reason": request.response_reason,
            "response_message": request.response_message,
            "responded_at": request.responded_at.isoformat() if request.responded_at else None,
            "responded_by": request.responded_by,
            "clarification_requested_at": request.clarification_requested_at.isoformat() if request.clarification_requested_at else None,
            "clarification_response": request.clarification_response,
            "clarification_responded_at": request.clarification_responded_at.isoformat() if request.clarification_responded_at else None,
            "history": request.history,
        }
    
    async def _notify_recipient(self, request: AssociationRequest, event: str = "created"):
        """Send notification to recipient."""
        try:
            service = get_notification_service()
            # Use target_faculty_id for SQLAlchemy model, recipient_id for dataclass
            recipient_id = getattr(request, 'target_faculty_id', None) or getattr(request, 'recipient_id', None)
            if not recipient_id:
                return
            
            if event == "created":
                await service.create_notification(
                    user_id=recipient_id,
                    notification_type=NotificationType.ASSOCIATION_REQUEST,
                    title="Association Request Received",
                    message=f"You have received a new association request for an IP record. Please review and respond.",
                    priority=NotificationPriority.HIGH,
                    related_entity_type="association_request",
                    related_entity_id=request.id,
                    action_url=f"/faculty/associations",
                    action_label="Review Request",
                )
            elif event == "cancelled":
                await service.create_notification(
                    user_id=recipient_id,
                    notification_type=NotificationType.ASSOCIATION_REQUEST,
                    title="Association Request Cancelled",
                    message=f"The association request has been cancelled by the requester.",
                    priority=NotificationPriority.MEDIUM,
                    related_entity_type="association_request",
                    related_entity_id=request.id,
                )
            elif event == "clarification_response":
                await service.create_notification(
                    user_id=recipient_id,
                    notification_type=NotificationType.ASSOCIATION_CLARIFICATION,
                    title="Clarification Provided",
                    message=f"The requester has provided clarification on the association request.",
                    priority=NotificationPriority.HIGH,
                    related_entity_type="association_request",
                    related_entity_id=request.id,
                    action_url=f"/faculty/associations",
                    action_label="Review Request",
                )
            elif event == "expired":
                await service.create_notification(
                    user_id=recipient_id,
                    notification_type=NotificationType.ASSOCIATION_REQUEST,
                    title="Association Request Expired",
                    message=f"You did not respond to an association request for IP record {request.record_id} before it expired.",
                    priority=NotificationPriority.MEDIUM,
                    related_entity_type="association_request",
                    related_entity_id=request.id,
                    action_url=f"/faculty/associations",
                    action_label="View Details",
                    metadata={"expired": True, "missed_by_recipient": True},
                )
        except Exception as e:
            recipient_id = getattr(request, 'target_faculty_id', None) or getattr(request, 'recipient_id', None)
            self.logger.warning("notification_failed", recipient=recipient_id, request_id=request.id, error=str(e))
    
    async def _notify_requester(self, request: AssociationRequest, event: str = "responded"):
        """Send notification to requester."""
        try:
            service = get_notification_service()
            
            if event == "approve":
                await service.create_notification(
                    user_id=request.requester_id,
                    notification_type=NotificationType.ASSOCIATION_APPROVED,
                    title="Association Request Approved",
                    message=f"Your association request has been approved.",
                    priority=NotificationPriority.HIGH,
                    related_entity_type="association_request",
                    related_entity_id=request.id,
                    action_url=f"/faculty/associations",
                    action_label="View Details",
                )
            elif event == "reject":
                await service.create_notification(
                    user_id=request.requester_id,
                    notification_type=NotificationType.ASSOCIATION_REJECTED,
                    title="Association Request Rejected",
                    message=f"Your association request was rejected.",
                    priority=NotificationPriority.HIGH,
                    related_entity_type="association_request",
                    related_entity_id=request.id,
                )
            elif event == "clarification":
                await service.create_notification(
                    user_id=request.requester_id,
                    notification_type=NotificationType.ASSOCIATION_CLARIFICATION,
                    title="Clarification Requested",
                    message=f"The recipient has requested clarification on your association request.",
                    priority=NotificationPriority.HIGH,
                    related_entity_type="association_request",
                    related_entity_id=request.id,
                    action_url=f"/faculty/associations",
                    action_label="Provide Clarification",
                )
            elif event == "not_me":
                await service.create_notification(
                    user_id=request.requester_id,
                    notification_type=NotificationType.ASSOCIATION_NOT_ME,
                    title="Association Marked 'Not Me'",
                    message=f"The recipient indicated this association is not for them.",
                    priority=NotificationPriority.MEDIUM,
                    related_entity_type="association_request",
                    related_entity_id=request.id,
                )
            elif event == "expired":
                await service.create_notification(
                    user_id=request.requester_id,
                    notification_type=NotificationType.ASSOCIATION_REQUEST,
                    title="Association Request Expired",
                    message=f"Your association request has expired without a response.",
                    priority=NotificationPriority.MEDIUM,
                    related_entity_type="association_request",
                    related_entity_id=request.id,
                    action_url=f"/faculty/associations",
                    action_label="View Details",
                    metadata={"expired": True},
                )
        except Exception as e:
            self.logger.warning("notification_failed", requester=request.requester_id, request_id=request.id, error=str(e))

    async def check_and_send_reminders(self) -> int:
        """Check for pending association requests that need reminders.

        Sends reminders for requests that are approaching expiry.
        Returns the number of reminders sent.
        """
        from app.core.database import get_session
        from sqlalchemy import select
        from app.models.base import AssociationRequest

        session = get_session()
        try:
            # Find pending requests that haven't had a reminder sent
            # and are within the reminder window
            reminder_cutoff = datetime.now(UTC) + timedelta(days=REMINDER_BEFORE_EXPIRY_DAYS)

            pending_requests = session.execute(
                select(AssociationRequest).where(
                    AssociationRequest.status == "PENDING",
                    AssociationRequest.expires_at.isnot(None),
                    AssociationRequest.expires_at <= reminder_cutoff,
                    AssociationRequest.reminder_sent_at.is_(None),
                )
            ).scalars().all()

            reminders_sent = 0
            for request in pending_requests:
                try:
                    await self._send_reminder(request)
                    request.reminder_sent_at = datetime.now(UTC)
                    session.add(request)
                    reminders_sent += 1
                except Exception as e:
                    self.logger.warning("reminder_failed", 
                                      request_id=request.id, 
                                      error=str(e))

            if reminders_sent > 0:
                session.commit()
                self.logger.info("reminders_sent", count=reminders_sent)

            return reminders_sent
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def check_and_expire_requests(self) -> int:
        """Check for and expire overdue association requests.

        Returns the number of requests expired.
        """
        from app.core.database import get_session
        from sqlalchemy import select
        from app.models.base import AssociationRequest

        session = get_session()
        try:
            # Find pending requests that have passed their expiry date
            now = datetime.now(UTC)

            expired_requests = session.execute(
                select(AssociationRequest).where(
                    AssociationRequest.status == "PENDING",
                    AssociationRequest.expires_at.isnot(None),
                    AssociationRequest.expires_at < now,
                )
            ).scalars().all()

            expired_count = 0
            for request in expired_requests:
                try:
                    old_status = request.status
                    request.status = "EXPIRED"
                    request.updated_at = datetime.now(UTC)

                    # Log audit
                    from app.core.logging import log_audit
                    log_audit(
                        actor="system",
                        action="ASSOCIATION_REQUEST_EXPIRED",
                        target_type="association_request",
                        target_id=request.id,
                        status="expired",
                        before={"status": old_status},
                        after={"status": "EXPIRED"},
                        extra={
                            "record_id": request.record_id,
                            "requester_id": request.requester_id,
                            "recipient_id": request.target_faculty_id,
                        },
                    )

                    # Notify requester
                    await self._notify_requester_expired(request)

                    # Notify recipient (they missed the deadline)
                    await self._notify_recipient_expired(request)

                    session.add(request)
                    expired_count += 1
                except Exception as e:
                    self.logger.warning("expiry_failed",
                                      request_id=request.id,
                                      error=str(e))

            if expired_count > 0:
                session.commit()
                self.logger.info("requests_expired", count=expired_count)

            return expired_count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def _send_reminder(self, request: "AssociationRequest"):
        """Send a reminder notification for an expiring association request."""
        service = get_notification_service()
        # Use target_faculty_id for SQLAlchemy model, recipient_id for dataclass
        recipient_id = getattr(request, 'target_faculty_id', None) or getattr(request, 'recipient_id', None)
        if not recipient_id:
            return
        await service.create_notification(
            user_id=recipient_id,
            notification_type=NotificationType.ASSOCIATION_REQUEST,
            title="Association Request Reminder",
            message=f"Your association request for IP record {request.record_id} will expire in {REMINDER_BEFORE_EXPIRY_DAYS} days. Please review and respond.",
            priority=NotificationPriority.HIGH,
            related_entity_type="association_request",
            related_entity_id=request.id,
            action_url=f"/faculty/associations",
            action_label="Review Request",
            metadata={"reminder": True, "expires_at": request.expires_at.isoformat() if request.expires_at else None},
        )

    async def _notify_requester_expired(self, request: "AssociationRequest"):
        """Notify requester that their request expired."""
        try:
            service = get_notification_service()
            await service.create_notification(
                user_id=request.requester_id,
                notification_type=NotificationType.ASSOCIATION_REQUEST,
                title="Association Request Expired",
                message=f"Your association request for IP record {request.record_id} has expired without a response.",
                priority=NotificationPriority.MEDIUM,
                related_entity_type="association_request",
                related_entity_id=request.id,
                action_url=f"/faculty/associations",
                action_label="View Details",
                metadata={"expired": True},
            )
        except Exception as e:
            self.logger.warning("notification_failed", requester=request.requester_id, request_id=request.id, error=str(e))

    async def _notify_recipient_expired(self, request: "AssociationRequest"):
        """Notify recipient that they missed an association request."""
        try:
            service = get_notification_service()
            # Use target_faculty_id for SQLAlchemy model, recipient_id for dataclass
            recipient_id = getattr(request, 'target_faculty_id', None) or getattr(request, 'recipient_id', None)
            if not recipient_id:
                return
            await service.create_notification(
                user_id=recipient_id,
                notification_type=NotificationType.ASSOCIATION_REQUEST,
                title="Association Request Expired",
                message=f"You did not respond to an association request for IP record {request.record_id} before it expired.",
                priority=NotificationPriority.MEDIUM,
                related_entity_type="association_request",
                related_entity_id=request.id,
                action_url=f"/faculty/associations",
                action_label="View Details",
                metadata={"expired": True, "missed_by_recipient": True},
            )
        except Exception as e:
            recipient_id = getattr(request, 'target_faculty_id', None) or getattr(request, 'recipient_id', None)
            self.logger.warning("notification_failed", recipient=recipient_id, request_id=request.id, error=str(e))


# --- Global Service ---

_association_service: AssociationService | None = None


def get_association_service() -> AssociationService:
    """Get or create the global association service."""
    global _association_service
    if _association_service is None:
        _association_service = AssociationService()
    return _association_service


async def create_association_request(
    record_id: str,
    requester_id: str,
    requester_name: str,
    requester_email: str,
    recipient_id: str,
    recipient_name: str,
    recipient_email: str,
    role: str = "co_owner",
    reason: str = "",
    message: str = "",
) -> dict[str, Any]:
    """High-level function to create association request."""
    service = get_association_service()
    return await service.create_association_request(
        record_id, requester_id, requester_name, requester_email,
        recipient_id, recipient_name, recipient_email,
        role, "", ""
    )


async def respond_to_association_request(
    request_id: str,
    responder_id: str,
    action: str,
    reason: str = "",
    message: str = "",
) -> dict[str, Any]:
    """Respond to an association request."""
    service = get_association_service()
    return await service.respond_to_request(request_id, responder_id, action, reason, "", "")
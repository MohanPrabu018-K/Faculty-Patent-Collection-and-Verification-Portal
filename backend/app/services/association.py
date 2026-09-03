from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog
from app.core.logging import log_audit

logger = structlog.get_logger()


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
        """Send notification to recipient (placeholder)."""
        self.logger.info("notification_sent", 
                        notification_event=event, 
                        recipient=request.recipient_id,
                        request_id=request.id)
        # In production, integrate with notification service
    
    async def _notify_requester(self, request: AssociationRequest, event: str = "responded"):
        """Send notification to requester (placeholder)."""
        self.logger.info("notification_sent",
                        notification_event=event,
                        requester=request.requester_id,
                        request_id=request.id)


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
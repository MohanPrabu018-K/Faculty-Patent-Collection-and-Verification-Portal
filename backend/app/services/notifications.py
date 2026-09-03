from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import structlog
from app.core.logging import log_security_event

logger = structlog.get_logger()


# --- Enums ---

class NotificationType(Enum):
    """Types of notifications."""
    UPLOAD_COMPLETED = "upload_completed"
    VERIFICATION_COMPLETED = "verification_completed"
    ASSOCIATION_REQUEST = "association_request"
    ASSOCIATION_APPROVED = "association_approved"
    ASSOCIATION_REJECTED = "association_rejected"
    ASSOCIATION_CLARIFICATION = "association_clarification"
    ASSOCIATION_NOT_ME = "association_not_me"
    CONFLICT_DETECTED = "conflict_detected"
    CONFLICT_RESOLVED = "conflict_resolved"
    ADMIN_ACTION_REQUIRED = "admin_action_required"
    PROCESSING_FAILURE = "processing_failure"
    CORRECTION_REQUIRED = "correction_required"
    PROFILE_UPDATED = "profile_updated"
    CREDENTIALS_RESET = "credentials_reset"


class NotificationPriority(Enum):
    """Notification priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class SecurityEventType(Enum):
    """Types of security events."""
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    ACCOUNT_LOCKED = "account_locked"
    PASSWORD_CHANGED = "password_changed"
    CREDENTIALS_RESET = "credentials_reset"
    PERMISSION_CHANGED = "permission_changed"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    BRUTE_FORCE_ATTEMPT = "brute_force_attempt"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    DATA_EXPORT = "data_export"
    ADMIN_ACTION = "admin_action"


# --- Data Classes (public API, kept enum-rich for endpoint compatibility) ---

@dataclass
class Notification:
    """In-app notification."""
    id: str
    user_id: str
    type: NotificationType
    priority: NotificationPriority
    title: str
    message: str
    related_entity_type: str | None = None
    related_entity_id: str | None = None
    action_url: str | None = None
    action_label: str | None = None
    is_read: bool = False
    read_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityEvent:
    """Security event log."""
    id: str
    event_type: SecurityEventType
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    description: str = ""
    severity: str = "medium"  # low, medium, high, critical
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _coerce_notification_type(value: str) -> NotificationType:
    try:
        return NotificationType(value)
    except ValueError:
        return NotificationType.ADMIN_ACTION_REQUIRED


def _coerce_priority(value: str) -> NotificationPriority:
    try:
        return NotificationPriority(value)
    except ValueError:
        return NotificationPriority.MEDIUM


def _coerce_event_type(value: str) -> SecurityEventType:
    try:
        return SecurityEventType(value)
    except ValueError:
        return SecurityEventType.SUSPICIOUS_ACTIVITY


def _model_to_notification(row) -> Notification:
    """Map a SQLAlchemy Notification row to the public dataclass."""
    return Notification(
        id=row.id,
        user_id=row.user_id,
        type=_coerce_notification_type(row.type),
        priority=_coerce_priority(row.priority or "MEDIUM"),
        title=row.title,
        message=row.message,
        related_entity_type=row.related_entity_type,
        related_entity_id=row.related_entity_id,
        action_url=row.action_url,
        action_label=row.action_label,
        is_read=bool(row.is_read),
        read_at=row.read_at,
        created_at=row.created_at,
        expires_at=row.expires_at,
        metadata=row.meta or {},
    )


# --- Notification Service ---

class NotificationService:
    """Persistent in-app notification service backed by PostgreSQL."""

    def __init__(self):
        self.logger = logger.bind(service="notification")

    async def create_notification(
        self,
        user_id: str,
        notification_type: NotificationType,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        related_entity_type: str | None = None,
        related_entity_id: str | None = None,
        action_url: str | None = None,
        action_label: str | None = None,
        expires_in_hours: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Notification:
        """Create and persist a new notification."""
        from app.core.database import get_async_session_context
        from app.models.base import Notification as NotificationModel

        notification_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).replace(tzinfo=None)
        expires_at = (
            (datetime.now(UTC) + timedelta(hours=expires_in_hours)).replace(tzinfo=None)
            if expires_in_hours
            else None
        )

        row = NotificationModel(
            id=notification_id,
            user_id=user_id,
            type=notification_type.value,
            title=title,
            message=message,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            priority=priority.value,
            action_url=action_url,
            action_label=action_label,
            is_read=False,
            created_at=created_at,
            expires_at=expires_at,
            meta=metadata or {},
        )

        async with get_async_session_context() as session:
            session.add(row)
            await session.commit()

        self.logger.info(
            "notification_created",
            user_id=user_id,
            type=notification_type.value,
            priority=priority.value,
        )

        return Notification(
            id=notification_id,
            user_id=user_id,
            type=notification_type,
            priority=priority,
            title=title,
            message=message,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            action_url=action_url,
            action_label=action_label,
            is_read=False,
            created_at=created_at,
            expires_at=expires_at,
            metadata=metadata or {},
        )

    async def get_user_notifications(
        self,
        user_id: str,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Notification], int]:
        """Get persisted notifications for a user."""
        from sqlalchemy import func, select
        from app.core.database import get_async_session_context
        from app.models.base import Notification as NotificationModel

        async with get_async_session_context() as session:
            count_query = select(func.count()).select_from(NotificationModel).where(
                NotificationModel.user_id == user_id
            )
            query = select(NotificationModel).where(NotificationModel.user_id == user_id)
            if unread_only:
                count_query = count_query.where(NotificationModel.is_read.is_(False))
                query = query.where(NotificationModel.is_read.is_(False))

            total = (await session.execute(count_query)).scalar_one()
            rows = (
                await session.execute(
                    query.order_by(NotificationModel.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).scalars().all()

            return [_model_to_notification(r) for r in rows], total

    async def mark_as_read(
        self,
        user_id: str,
        notification_id: str,
    ) -> Notification | None:
        """Mark a notification as read."""
        from sqlalchemy import select
        from app.core.database import get_async_session_context
        from app.models.base import Notification as NotificationModel

        async with get_async_session_context() as session:
            row = (
                await session.execute(
                    select(NotificationModel).where(
                        NotificationModel.id == notification_id,
                        NotificationModel.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if not row:
                return None

            row.is_read = True
            row.read_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            return _model_to_notification(row)

    async def mark_all_read(self, user_id: str) -> int:
        """Mark all unread notifications as read for a user."""
        from sqlalchemy import select, update
        from app.core.database import get_async_session_context
        from app.models.base import Notification as NotificationModel

        now = datetime.now(UTC).replace(tzinfo=None)
        async with get_async_session_context() as session:
            result = await session.execute(
                update(NotificationModel)
                .where(
                    NotificationModel.user_id == user_id,
                    NotificationModel.is_read.is_(False),
                )
                .values(is_read=True, read_at=now)
            )
            await session.commit()
            return result.rowcount or 0

    async def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications."""
        from sqlalchemy import func, select
        from app.core.database import get_async_session_context
        from app.models.base import Notification as NotificationModel

        async with get_async_session_context() as session:
            return (
                await session.execute(
                    select(func.count())
                    .select_from(NotificationModel)
                    .where(
                        NotificationModel.user_id == user_id,
                        NotificationModel.is_read.is_(False),
                    )
                )
            ).scalar_one()

    async def delete_notification(self, user_id: str, notification_id: str) -> bool:
        """Delete a notification."""
        from sqlalchemy import delete, select
        from app.core.database import get_async_session_context
        from app.models.base import Notification as NotificationModel

        async with get_async_session_context() as session:
            row = (
                await session.execute(
                    select(NotificationModel).where(
                        NotificationModel.id == notification_id,
                        NotificationModel.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if not row:
                return False
            await session.execute(
                delete(NotificationModel).where(NotificationModel.id == notification_id)
            )
            await session.commit()
            return True


# --- Security Events Service ---

class SecurityEventService:
    """Persistent security event logging service."""

    def __init__(self):
        self.logger = logger.bind(service="security_events")

    async def log_event(
        self,
        event_type: SecurityEventType,
        description: str,
        user_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        severity: str = "medium",
        metadata: dict[str, Any] | None = None,
    ) -> SecurityEvent:
        """Persist a security event and emit a structured log."""
        from app.core.database import get_async_session_context
        from app.models.base import SecurityEvent as SecurityEventModel

        event = SecurityEvent(
            id=str(uuid.uuid4()),
            event_type=event_type,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            description=description,
            severity=severity,
            metadata=metadata or {},
        )

        details = {
            "description": description,
            "severity": severity,
            "user_agent": user_agent,
            "ip_address": ip_address,
            "metadata": metadata or {},
        }

        try:
            async with get_async_session_context() as session:
                session.add(
                    SecurityEventModel(
                        id=event.id,
                        event_type=event_type.value,
                        source_ip=ip_address,
                        user_id=user_id,
                        details=details,
                        created_at=datetime.now(UTC).replace(tzinfo=None),
                    )
                )
                await session.commit()
        except Exception as exc:  # pragma: no cover - best-effort persistence
            self.logger.warning("security_event_persistence_failed", error=str(exc))

        # Emit structured log (console)
        log_security_event(
            event_type=event_type.value,
            detail=description,
            actor=user_id or "unknown",
            outcome="success" if severity != "critical" else "failure",
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self.logger.warning(
            "security_event",
            event_type=event_type.value,
            user_id=user_id,
            severity=severity,
            description=description,
        )

        return event

    async def get_events(
        self,
        user_id: str | None = None,
        event_type: SecurityEventType | None = None,
        severity: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[SecurityEvent], int]:
        """Get persisted security events with filters."""
        from sqlalchemy import func, select
        from app.core.database import get_async_session_context
        from app.models.base import SecurityEvent as SecurityEventModel

        async with get_async_session_context() as session:
            query = select(SecurityEventModel)
            count_query = select(func.count()).select_from(SecurityEventModel)
            conditions = []
            if user_id:
                conditions.append(SecurityEventModel.user_id == user_id)
            if event_type:
                conditions.append(SecurityEventModel.event_type == event_type.value)
            if start_date:
                conditions.append(SecurityEventModel.created_at >= start_date)
            if end_date:
                conditions.append(SecurityEventModel.created_at <= end_date)
            if conditions:
                from sqlalchemy import and_
                query = query.where(and_(*conditions))
                count_query = count_query.where(and_(*conditions))

            total = (await session.execute(count_query)).scalar_one()
            rows = (
                await session.execute(
                    query.order_by(SecurityEventModel.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).scalars().all()

            events = []
            for r in rows:
                details = r.details or {}
                events.append(
                    SecurityEvent(
                        id=r.id,
                        event_type=_coerce_event_type(r.event_type),
                        user_id=r.user_id,
                        ip_address=details.get("ip_address") or r.source_ip,
                        user_agent=details.get("user_agent"),
                        description=details.get("description", ""),
                        severity=details.get("severity", "medium"),
                        metadata=details.get("metadata") or {},
                        created_at=r.created_at,
                    )
                )

            # Post-filter severity (stored inside JSON details, not a column)
            if severity:
                events = [e for e in events if e.severity == severity]
                total = len(events)

            return events, total

    async def get_failed_logins_count(
        self,
        user_id: str,
        since: datetime,
    ) -> int:
        """Count failed login security events for a user since a date."""
        from sqlalchemy import func, select
        from app.core.database import get_async_session_context
        from app.models.base import SecurityEvent as SecurityEventModel

        async with get_async_session_context() as session:
            return (
                await session.execute(
                    select(func.count())
                    .select_from(SecurityEventModel)
                    .where(
                        SecurityEventModel.user_id == user_id,
                        SecurityEventModel.event_type == SecurityEventType.LOGIN_FAILURE.value,
                        SecurityEventModel.created_at >= since,
                    )
                )
            ).scalar_one()


# --- Global Services ---

_notification_service: NotificationService | None = None
_security_event_service: SecurityEventService | None = None


def get_notification_service() -> NotificationService:
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


def get_security_event_service() -> SecurityEventService:
    global _security_event_service
    if _security_event_service is None:
        _security_event_service = SecurityEventService()
    return _security_event_service


async def create_notification(
    user_id: str,
    notification_type: NotificationType,
    title: str,
    message: str,
    priority: NotificationPriority = NotificationPriority.MEDIUM,
    **kwargs,
) -> Notification:
    service = get_notification_service()
    return await service.create_notification(
        user_id, notification_type, title, message, priority, **kwargs
    )


async def log_security_event_wrapper(
    event_type: SecurityEventType,
    description: str,
    **kwargs,
) -> SecurityEvent:
    service = get_security_event_service()
    return await service.log_event(event_type, description, **kwargs)

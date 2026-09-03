from datetime import UTC, datetime

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


def log_audit(
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    status: str,
    before: dict | None = None,
    after: dict | None = None,
    extra: dict | None = None,
) -> None:
    """Log an audit event AND persist it to PostgreSQL.

    The audit trail is the authoritative record of every important action. It is
    written to the ``audit_log`` table (immutable) in addition to structured
    console logging. Persistence is best-effort so a DB outage never breaks the
    primary business operation, but the event is still emitted to logs.
    """
    logger = structlog.get_logger()
    audit_event = {
        "actor": actor,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "status": status,
        "before": before,
        "after": after,
    }
    if extra:
        audit_event.update(extra)
    logger.info("audit_event", **audit_event)

    try:
        from app.core.database import get_session
        from app.models.base import AuditLog

        session = get_session()
        try:
            session.add(
                AuditLog(
                    actor_id=actor if actor not in ("system", "anonymous") else None,
                    actor_role=extra.get("actor_role") if extra else None,
                    action=action,
                    entity_type=target_type,
                    entity_id=target_id,
                    target_type=target_type,
                    target_id=target_id,
                    previous_value=before,
                    new_value=after,
                    details=extra,
                    extra=extra,
                    ip_address=extra.get("ip_address") if extra else None,
                    reason=extra.get("reason") if extra else None,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            logger.warning("audit_persistence_failed", action=action)
        finally:
            session.close()
    except Exception:
        logger.warning("audit_persistence_unavailable", action=action)


def log_security_event(
    event_type: str,
    detail: str,
    actor: str,
    outcome: str = "unknown",
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Log a security event."""
    logger = structlog.get_logger()
    security_event = {
        "event_type": event_type,
        "detail": detail,
        "actor": actor,
        "outcome": outcome,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if ip_address:
        security_event["ip_address"] = ip_address
    if user_agent:
        security_event["user_agent"] = user_agent
    logger.warning("security_event", **security_event)
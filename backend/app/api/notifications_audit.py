from datetime import datetime

import structlog
from app.api.deps import get_current_user, require_super_admin
from app.services.notifications import (
    SecurityEventType,
    get_notification_service,
    get_security_event_service,
)
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

logger = structlog.get_logger()

notifications_router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@notifications_router.get("/", status_code=status.HTTP_200_OK)
async def list_notifications(current_user: dict = Depends(get_current_user), unread_only: bool = Query(False), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    service = get_notification_service()
    notifications, total = await service.get_user_notifications(user_id=current_user.get("id"), unread_only=unread_only, limit=per_page, offset=(page - 1) * per_page)
    return {"notifications": [{"id": n.id, "type": n.type.value, "priority": n.priority.value, "title": n.title, "message": n.message, "related_entity_type": n.related_entity_type, "related_entity_id": n.related_entity_id, "action_url": n.action_url, "action_label": n.action_label, "is_read": n.is_read, "read_at": n.read_at.isoformat() if n.read_at else None, "created_at": n.created_at.isoformat(), "expires_at": n.expires_at.isoformat() if n.expires_at else None, "metadata": n.metadata} for n in notifications], "total": total, "page": page, "per_page": per_page, "unread_count": await get_notification_service().get_unread_count(current_user.get("id"))}


@notifications_router.post("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_notification_read(notification_id: str, current_user: dict = Depends(get_current_user)):
    service = get_notification_service()
    notification = await service.mark_as_read(current_user.get("id"), notification_id)
    if not notification:
        return JSONResponse(status_code=404, content={"error": "NOTIFICATION_NOT_FOUND", "message": "Notification not found"})
    return {"notification_id": notification_id, "status": "read", "read_at": notification.read_at.isoformat() if notification.read_at else None}


@notifications_router.post("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_notifications_read(current_user: dict = Depends(get_current_user)):
    service = get_notification_service()
    count = await service.mark_all_read(current_user.get("id"))
    return {"marked_read": count, "message": f"Marked {count} notifications as read"}


@notifications_router.get("/unread-count", status_code=status.HTTP_200_OK)
async def get_unread_count(current_user: dict = Depends(get_current_user)):
    service = get_notification_service()
    return {"unread_count": await service.get_unread_count(current_user.get("id"))}


@notifications_router.delete("/{notification_id}", status_code=status.HTTP_200_OK)
async def delete_notification(notification_id: str, current_user: dict = Depends(get_current_user)):
    service = get_notification_service()
    deleted = await service.delete_notification(current_user.get("id"), notification_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": "NOTIFICATION_NOT_FOUND", "message": "Notification not found"})
    return {"notification_id": notification_id, "status": "deleted"}


audit_router = APIRouter(prefix="/api/v1/audit", tags=["audit"], dependencies=[Depends(require_super_admin)])


def _audit_row_to_dict(row) -> dict:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "actor_role": row.actor_role,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "previous_value": row.previous_value,
        "new_value": row.new_value,
        "before_state": row.before_state,
        "after_state": row.after_state,
        "details": row.details,
        "extra": row.extra,
        "ip_address": row.ip_address,
        "reason": row.reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@audit_router.get("/", status_code=status.HTTP_200_OK)
async def list_audit_logs(current_user: dict = Depends(get_current_user), entity_type: str | None = Query(None), entity_id: str | None = Query(None), actor_id: str | None = Query(None), action: str | None = Query(None), start_date: str | None = Query(None), end_date: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    return await _list_audit_impl(entity_type, entity_id, actor_id, action, start_date, end_date, page, per_page)


@audit_router.get("/logs", status_code=status.HTTP_200_OK)
async def list_audit_logs_alias(current_user: dict = Depends(get_current_user), entity_type: str | None = Query(None), entity_id: str | None = Query(None), actor_id: str | None = Query(None), action: str | None = Query(None), start_date: str | None = Query(None), end_date: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    return await _list_audit_impl(entity_type, entity_id, actor_id, action, start_date, end_date, page, per_page)


async def _list_audit_impl(entity_type, entity_id, actor_id, action, start_date, end_date, page, per_page):
    from app.models.base import AuditLog, Department, User
    from sqlalchemy import func, select
    from app.core.database import get_async_session_context

    query = select(AuditLog)
    count_query = select(func.count()).select_from(AuditLog)
    conditions = []
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conditions.append(AuditLog.entity_id == entity_id)
    if actor_id:
        conditions.append(AuditLog.actor_id == actor_id)
    if action:
        conditions.append(AuditLog.action == action)
    if start_date:
        conditions.append(AuditLog.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        conditions.append(AuditLog.created_at <= datetime.fromisoformat(end_date))
    if conditions:
        from sqlalchemy import and_
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    async with get_async_session_context() as db:
        total = (await db.execute(count_query)).scalar_one()
        rows = (await db.execute(query.order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page))).scalars().all()

        # Resolve actor identity/role/department at read time (no write-path change).
        actor_ids = {r.actor_id for r in rows if r.actor_id}
        actor_map: dict = {}
        if actor_ids:
            users = (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
            dept_map = {d.id: d.name for d in (await db.execute(select(Department))).scalars().all()}
            actor_map = {
                u.id: {"name": u.full_name, "role": u.role, "department": dept_map.get(u.department_id)}
                for u in users
            }

        out = []
        for r in rows:
            d = _audit_row_to_dict(r)
            meta = actor_map.get(r.actor_id, {})
            d["actor_name"] = meta.get("name")
            d["actor_role"] = r.actor_role or meta.get("role")
            d["actor_department"] = meta.get("department")
            out.append(d)
        return {"audit_logs": out, "total": total, "page": page, "per_page": per_page}


@audit_router.get("/security-events", status_code=status.HTTP_200_OK)
async def list_security_events(current_user: dict = Depends(get_current_user), event_type: str | None = Query(None), severity: str | None = Query(None), user_id: str | None = Query(None), start_date: str | None = Query(None), end_date: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    from app.models.base import SecurityEvent
    from sqlalchemy import func, select
    from app.core.database import get_async_session_context

    query = select(SecurityEvent)
    count_query = select(func.count()).select_from(SecurityEvent)
    conditions = []
    if event_type:
        conditions.append(SecurityEvent.event_type == event_type)
    if user_id:
        conditions.append(SecurityEvent.user_id == user_id)
    if start_date:
        conditions.append(SecurityEvent.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        conditions.append(SecurityEvent.created_at <= datetime.fromisoformat(end_date))
    if conditions:
        from sqlalchemy import and_
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    async with get_async_session_context() as db:
        total = (await db.execute(count_query)).scalar_one()
        rows = (await db.execute(query.order_by(SecurityEvent.created_at.desc()).offset((page - 1) * per_page).limit(per_page))).scalars().all()
        return {"security_events": [{"id": r.id, "event_type": r.event_type, "user_id": r.user_id, "source_ip": r.source_ip, "details": r.details, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows], "total": total, "page": page, "per_page": per_page}


@audit_router.get("/stats", status_code=status.HTTP_200_OK)
async def get_audit_stats(current_user: dict = Depends(get_current_user)):
    from app.models.base import AuditLog, SecurityEvent
    from sqlalchemy import func, select
    from app.core.database import get_async_session_context

    async with get_async_session_context() as db:
        total_audit = (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one()
        total_security = (await db.execute(select(func.count()).select_from(SecurityEvent))).scalar_one()
    return {"total_audit_logs": total_audit, "total_security_events": total_security, "failed_logins_24h": 0, "locked_accounts": 0, "recent_critical_events": 0}



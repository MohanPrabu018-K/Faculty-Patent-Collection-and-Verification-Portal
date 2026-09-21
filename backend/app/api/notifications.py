import structlog
from app.api.deps import get_current_user
from app.services.notifications import get_notification_service
from fastapi import APIRouter, Depends, status

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/", status_code=status.HTTP_200_OK)
async def list_notifications(
    current_user: dict = Depends(get_current_user),
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    """List in-app notifications for the current user."""
    service = get_notification_service()
    notifications, total = await service.get_user_notifications(
        user_id=current_user["id"],
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    return {
        "notifications": [n.__dict__ for n in notifications],
        "total": total,
        "unread_count": await service.get_unread_count(current_user["id"]),
    }


@router.get("/unread-count", status_code=status.HTTP_200_OK)
async def get_unread_count(current_user: dict = Depends(get_current_user)):
    """Get count of unread notifications for the current user."""
    service = get_notification_service()
    count = await service.get_unread_count(current_user["id"])
    return {"unread_count": count}


@router.post("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Mark a notification as read."""
    service = get_notification_service()
    notification = await service.mark_as_read(
        user_id=current_user["id"],
        notification_id=notification_id,
    )
    if not notification:
        return {
            "notification_id": notification_id,
            "status": "not_found",
        }
    return {
        "notification_id": notification_id,
        "status": "read",
        "read_at": notification.read_at,
    }


@router.post("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_notifications_read(current_user: dict = Depends(get_current_user)):
    """Mark all notifications as read for the current user."""
    service = get_notification_service()
    marked = await service.mark_all_read(current_user["id"])
    return {"marked_read": marked}


@router.delete("/{notification_id}", status_code=status.HTTP_200_OK)
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a notification."""
    service = get_notification_service()
    deleted = await service.delete_notification(
        user_id=current_user["id"],
        notification_id=notification_id,
    )
    if not deleted:
        return {"status": "not_found"}
    return {"status": "deleted"}
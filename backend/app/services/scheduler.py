"""
Background job scheduler for the FPP application.

Uses APScheduler to run periodic background jobs:
- check_and_send_reminders: Sends reminders for association requests approaching expiry
- check_and_expire_requests: Expires overdue association requests
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import scheduler_settings
from app.services.association import AssociationService

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def create_scheduler() -> AsyncIOScheduler:
    """Create a new scheduler instance (for testing/override)."""
    return AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan_scheduler(app) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan handler for scheduler startup/shutdown.
    
    Starts the scheduler on application startup and shuts it down gracefully on shutdown.
    Only starts the scheduler if SCHEDULER_ENABLED is True.
    """
    global _scheduler
    
    if not scheduler_settings.enabled:
        logger.info("Scheduler disabled via SCHEDULER_ENABLED=False")
        yield
        return
    
    _scheduler = get_scheduler()
    
    # Add jobs
    _scheduler.add_job(
        _run_reminder_job,
        trigger=IntervalTrigger(hours=scheduler_settings.reminder_interval_hours),
        id="check_and_send_reminders",
        name="Check and send association reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    
    _scheduler.add_job(
        _run_expiry_job,
        trigger=IntervalTrigger(hours=scheduler_settings.expiry_check_interval_hours),
        id="check_and_expire_requests",
        name="Check and expire overdue association requests",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    
    logger.info(
        "Starting scheduler: reminder_interval_hours=%s, expiry_check_interval_hours=%s",
        scheduler_settings.reminder_interval_hours,
        scheduler_settings.expiry_check_interval_hours,
    )
    
    _scheduler.start()
    logger.info("Scheduler started")
    
    try:
        yield
    finally:
        logger.info("Shutting down scheduler")
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=True)
            except Exception:
                logger.warning("Scheduler shutdown failed", exc_info=True)
            _scheduler = None
        logger.info("Scheduler shut down")


async def _run_reminder_job() -> None:
    """Wrapper to run check_and_send_reminders with proper session handling."""
    logger.info("Running reminder job")
    service = AssociationService()
    try:
        reminders_sent = await service.check_and_send_reminders()
        logger.info("Reminder job completed: reminders_sent=%s", reminders_sent)
    except Exception as e:
        logger.error("Reminder job failed: %s", e)
        raise


async def _run_expiry_job() -> None:
    """Wrapper to run check_and_expire_requests with proper session handling."""
    logger.info("Running expiry job")
    service = AssociationService()
    try:
        expired_count = await service.check_and_expire_requests()
        logger.info("Expiry job completed: expired_count=%s", expired_count)
    except Exception as e:
        logger.error("Expiry job failed: %s", e)
        raise
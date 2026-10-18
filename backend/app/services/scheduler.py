"""
Background job scheduler for the FPP application.

Uses APScheduler to run periodic background jobs:
- check_and_send_reminders: Sends reminders for association requests approaching expiry
- check_and_expire_requests: Expires overdue association requests
"""
from __future__ import annotations

import asyncio
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
    FastAPI lifespan handler for scheduler and performance cache startup/shutdown.
    
    Starts the scheduler on application startup and shuts it down gracefully on shutdown.
    Only starts the scheduler if SCHEDULER_ENABLED is True.
    """
    global _scheduler
    
    cache_task = None
    try:
        from app.core.performance import start_cache_cleanup_task
        cache_task = await start_cache_cleanup_task()
        if hasattr(app, "state"):
            app.state._cache_cleanup_task = cache_task
    except Exception:
        logger.warning("Cache cleanup task failed to start", exc_info=True)

    if not scheduler_settings.enabled:
        logger.info("Scheduler disabled via SCHEDULER_ENABLED=False")
        try:
            yield
        finally:
            if cache_task is not None:
                cache_task.cancel()
                try:
                    await cache_task
                except asyncio.CancelledError:
                    pass
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

    # Durable-ish recovery for the upload pipeline. Uploads schedule the
    # 11-agent orchestrator via FastAPI BackgroundTasks, which lives only in
    # this process; a recycle (deploy, crash, or the free plan's idle
    # spin-down) strands the job at QUEUED/PROCESSING with no way to resume.
    # This re-drives those stranded jobs from the stored document so a
    # recycled worker cannot silently swallow an upload.
    _scheduler.add_job(
        _run_pipeline_recovery_job,
        trigger=IntervalTrigger(minutes=scheduler_settings.pipeline_recovery_interval_minutes),
        id="recover_stuck_pipelines",
        name="Requeue stranded document pipelines",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    logger.info(
        "Starting scheduler: reminder_interval_hours=%s, expiry_check_interval_hours=%s, "
        "pipeline_recovery_interval_minutes=%s",
        scheduler_settings.reminder_interval_hours,
        scheduler_settings.expiry_check_interval_hours,
        scheduler_settings.pipeline_recovery_interval_minutes,
    )
    
    # Idempotent start: the scheduler is a process-wide singleton, so repeated
    # application lifespans in one process (e.g. the test-suite, which opens a
    # TestClient per module) must not call start() twice on the same instance,
    # which raises apscheduler SchedulerAlreadyRunningError.
    if not _scheduler.running:
        _scheduler.start()
        logger.info("Scheduler started")
    
    try:
        yield
    finally:
        if cache_task is not None:
            cache_task.cancel()
            try:
                await cache_task
            except asyncio.CancelledError:
                pass
        logger.info("Shutting down scheduler")
        if _scheduler is not None:
            try:
                if _scheduler.running:
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


async def _run_pipeline_recovery_job() -> None:
    """Re-drive orchestrator jobs stranded by a worker recycle.

    ``run_document_pipeline`` is synchronous and blocking (it calls
    ``asyncio.run`` internally), so it must be offloaded to a worker thread to
    keep this scheduler's event loop responsive.
    """
    import asyncio as _asyncio

    from app.core.config import scheduler_settings
    from app.workers.orchestrator_task import requeue_stuck_pipelines

    try:
        summary = await _asyncio.to_thread(
            requeue_stuck_pipelines,
            stuck_after_seconds=scheduler_settings.pipeline_stuck_after_seconds,
        )
    except Exception as e:
        logger.error("Pipeline recovery job failed: %s", e)
        raise

    if summary.get("requeued") or summary.get("skipped_missing_file"):
        logger.info(
            "Pipeline recovery requeued stranded jobs",
            stuck_found=summary.get("stuck_found"),
            requeued=len(summary.get("requeued") or []),
            skipped_missing_file=len(summary.get("skipped_missing_file") or []),
        )
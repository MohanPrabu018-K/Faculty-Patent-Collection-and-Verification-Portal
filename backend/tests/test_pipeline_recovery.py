# -*- coding: utf-8 -*-
"""Regression tests for stranded-pipeline recovery (defect D-002).

Uploads schedule the 11-agent orchestrator through FastAPI BackgroundTasks,
which is in-process. A worker recycle (deploy, crash, or the Render free
plan's idle spin-down) strands the ProcessingJob at QUEUED/PROCESSING forever
and the record never reaches AWAITING_REVIEW. ``requeue_stuck_pipelines`` must
re-drive those jobs from the stored document.

These tests assert the recovery LOGIC without invoking the real (expensive,
network-touching) pipeline: ``run_document_pipeline`` is monkeypatched to a
spy so the requeue decision itself is what is under test.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core import config as app_config
from app.core.database import get_session
from app.models.base import IpFile, IpRecord, ProcessingJob, User
from app.workers import orchestrator_task
from app.workers.orchestrator_task import requeue_stuck_pipelines


@pytest.fixture()
def ctx(monkeypatch, tmp_path):
    """A stranded record + its orchestrator job, cleaned up afterwards."""
    tag = uuid.uuid4().hex[:8]
    session = get_session()
    try:
        user = User(
            id=str(uuid.uuid4()),
            email=f"rc-{tag}@example.test",
            official_email=f"rc-{tag}@example.test",
            password_hash="x",
            full_name=f"rc-{tag}",
            role="faculty",
            faculty_id=f"FAC-RC-{tag}",
            status="active",
            is_active=True,
        )
        session.add(user)
        session.commit()

        rec = IpRecord(
            id=str(uuid.uuid4()),
            uploader_id=user.id,
            ip_type="UNKNOWN_OTHER",
            processing_status="QUEUED",
            verification_status="UNVERIFIED",
            workflow_state="UPLOADED",
        )
        session.add(rec)
        session.commit()

        record_id = rec.id
        user_id = user.id
    finally:
        session.close()

    calls: list[str] = []
    from app.services.storage import reset_storage_service
    reset_storage_service()
    # requeue_stuck_pipelines imports upload_settings locally at call time, so
    # the settings object's attribute is what must be redirected.
    monkeypatch.setattr(
        app_config.upload_settings, "storage_backend", "local"
    )
    monkeypatch.setattr(
        app_config.upload_settings, "local_storage_root", str(tmp_path)
    )
    monkeypatch.setattr(
        orchestrator_task,
        "run_document_pipeline",
        lambda path, rid: calls.append(path),
    )

    yield {"record_id": record_id, "user_id": user_id, "calls": calls, "tmp": tmp_path}

    reset_storage_service()

    session = get_session()
    try:
        for model, col, value in (
            (ProcessingJob, ProcessingJob.ip_record_id, record_id),
            (IpFile, IpFile.ip_record_id, record_id),
            (IpRecord, IpRecord.id, record_id),
            (User, User.id, user_id),
        ):
            for row in session.query(model).filter(col == value).all():
                session.delete(row)
        session.commit()
    finally:
        session.close()


def _add_job(record_id: str, status: str, age_seconds: int) -> str:
    session = get_session()
    try:
        job = ProcessingJob(
            id=str(uuid.uuid4()),
            ip_record_id=record_id,
            job_type="orchestrator",
            status=status,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
        )
        session.add(job)
        session.commit()
        return job.id
    finally:
        session.close()


def _add_file(record_id: str, storage_key: str | None) -> None:
    session = get_session()
    try:
        session.add(
            IpFile(
                id=str(uuid.uuid4()),
                ip_record_id=record_id,
                storage_key=storage_key,
                original_filename="doc.pdf",
                file_extension=".pdf",
                file_size_bytes=1024,
                mime_type="application/pdf",
                upload_status="COMPLETED",
            )
        )
        session.commit()
    finally:
        session.close()


def _job(record_id: str) -> ProcessingJob:
    session = get_session()
    try:
        job = (
            session.query(ProcessingJob)
            .filter(ProcessingJob.ip_record_id == record_id)
            .one()
        )
        session.refresh(job)
        return {
            "status": job.status,
            "retry_count": job.retry_count,
            "error_message": job.error_message,
        }
    finally:
        session.close()


def test_stranded_queued_job_with_existing_file_is_requeued(ctx):
    """A long-stranded QUEUED job whose document still exists is re-driven."""
    record_id = ctx["record_id"]
    _add_file(record_id, "doc.pdf")
    (ctx["tmp"] / "doc.pdf").write_bytes(b"%PDF-1.4 stub")
    _add_job(record_id, status="QUEUED", age_seconds=3600)

    summary = requeue_stuck_pipelines(stuck_after_seconds=300)

    assert record_id in summary["requeued"], summary
    assert summary["stuck_found"] >= 1
    # The pipeline is re-run from the stored file, not marked done by hand.
    assert ctx["calls"] == [str(ctx["tmp"] / "doc.pdf")]

    job = _job(record_id)
    assert job["status"] == "QUEUED"
    assert job["retry_count"] == 1
    assert job["error_message"] is None


def test_recently_created_job_is_not_raced(ctx):
    """A job that is merely still running must never be double-driven."""
    record_id = ctx["record_id"]
    _add_file(record_id, "doc.pdf")
    _add_job(record_id, status="PROCESSING", age_seconds=10)

    summary = requeue_stuck_pipelines(stuck_after_seconds=300)

    assert record_id not in summary["requeued"]
    assert ctx["calls"] == []
    assert _job(record_id)["retry_count"] == 0


def test_terminal_job_is_left_alone(ctx):
    """Completed pipelines are never re-run."""
    record_id = ctx["record_id"]
    _add_file(record_id, "doc.pdf")
    _add_job(record_id, status="SUCCESS", age_seconds=9999)

    summary = requeue_stuck_pipelines(stuck_after_seconds=300)

    assert record_id not in summary["requeued"]
    assert ctx["calls"] == []


def test_missing_document_is_reported_not_crashed(ctx):
    """An orphaned job (file gone) is reported, never silently dropped or 500ed.

    On the free plan LOCAL_STORAGE_ROOT is ephemeral, so the document can be
    legitimately missing after a redeploy. The sweep must surface that fact
    instead of raising, so an operator can see the unrecoverable records.
    """
    record_id = ctx["record_id"]
    _add_file(record_id, "gone.pdf")
    _add_job(record_id, status="QUEUED", age_seconds=3600)

    summary = requeue_stuck_pipelines(stuck_after_seconds=300)

    assert record_id in summary["skipped_missing_file"], summary
    assert record_id not in summary["requeued"]
    assert ctx["calls"] == []
    assert _job(record_id)["retry_count"] == 0


def test_storage_key_is_confined_to_storage_root(ctx):
    """A traversal storage_key must never escape the storage root."""
    record_id = ctx["record_id"]
    _add_file(record_id, "../outside.pdf")
    outside = ctx["tmp"].parent / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4 escape")
    _add_job(record_id, status="QUEUED", age_seconds=3600)

    try:
        summary = requeue_stuck_pipelines(stuck_after_seconds=300)

        assert record_id in summary["skipped_missing_file"], summary
        assert ctx["calls"] == []
    finally:
        if outside.exists():
            outside.unlink()

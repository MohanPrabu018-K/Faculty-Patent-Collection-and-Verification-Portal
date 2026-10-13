# -*- coding: utf-8 -*-
"""Malformed-document regression tests (Priority 3).

Async contract: an HTTP 202 means "accepted for processing", NOT "processed
successfully". Malformed PDFs may therefore be accepted and must then fail
SAFELY in the pipeline. Proves with the REAL pipeline (no mocks):

A. plain .txt upload            -> 400 UPLOAD_ERROR, no record created.
B. truncated PDF (.pdf)         -> accepted shape, pipeline fails safe:
   no fabricated title/identifiers/dates/names, no VERIFIED/GRANTED state,
   no association requests, terminal job, no exception.
C. PDF-prefix garbage (.pdf)    -> same safe-failure invariants.
D. valid 1-page PDF (.pdf)      -> extracts identifier + filing date and
   verifies (proves the invariants don't break normal uploads).

Hermetic: synthetic mp-* rows/files, deleted by fixtures (FK-safe order:
snapshot/jobs/attempts/contributors/requests/cases/files/audit/notify/
secevent/record/user).
"""
import os
import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_, select

from app.core.config import app_settings
from app.core.database import get_async_session_context, get_session
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import (
    AssociationRequest,
    AuditLog,
    ConflictCase,
    DuplicateCase,
    FacultyProfileSnapshot,
    IpContributor,
    IpFile,
    IpRecord,
    Notification,
    ProcessingJob,
    SecurityEvent,
    User,
    VerificationAttempt,
)

TAG = uuid.uuid4().hex[:8]

VALID_TEXT = ("Indian Patent Application No. 202541777777 A\n"
              "Title: Malformed Probe Widget\n"
              "Applicant: Staging Test Fixture\nFiling Date: 05/05/2024\n")
GARBAGE = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nzzzz not a real pdf \x00\x01\x02" * 4


def _make_pdf_bytes(text):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 120), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _clear_rate_limiters():
    from app.api.deps import rate_limit_state
    from app.core.security_middleware import _rate_limiter

    rate_limit_state.counts.clear()
    if hasattr(_rate_limiter, "_buckets"):
        _rate_limiter._buckets.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    _clear_rate_limiters()
    yield


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tok(sub, role="faculty"):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=sub, department_id="", full_name=sub,
    )


def _h(client, token):
    client.cookies.set("csrf_token", "t")
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": "t"}


@pytest.fixture(scope="module")
def faculty():
    uid = f"mp-fac-{TAG}"

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(id=uid, email=f"{uid}@faculty.edu", full_name="MP Faculty",
                        password_hash=hash_password("secret123"), role="faculty",
                        faculty_id=uid, is_active=True, status="active"))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            for model, col in ((Notification, Notification.user_id),
                               (SecurityEvent, SecurityEvent.user_id)):
                for row in (await db.execute(select(model).where(col == uid))).scalars().all():
                    await db.delete(row)
            for a in (await db.execute(select(AuditLog).where(
                    (AuditLog.actor_id == uid) | (AuditLog.entity_id == uid)
                    | (AuditLog.target_id == uid)))).scalars().all():
                await db.delete(a)
            u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    import asyncio
    asyncio.run(_create())
    try:
        yield {"id": uid, "email": f"{uid}@faculty.edu"}
    finally:
        asyncio.run(_delete())


def _record_count():
    import asyncio

    async def _q():
        async with get_async_session_context() as db:
            return len((await db.execute(select(IpRecord.id))).all())

    return asyncio.run(_q())


def _run_pipeline_case(name, payload):
    """Create a synthetic record, run the REAL pipeline, return fresh state."""
    from app.workers.orchestrator_task import run_document_pipeline

    import asyncio
    tag = f"mp-{name}-{TAG}"
    tmp = tempfile.mkdtemp(prefix="mp-case-")
    path = os.path.join(tmp, name + ".pdf")
    with open(path, "wb") as f:
        f.write(payload)

    async def _create():
        async with get_async_session_context() as db:
            u = (await db.execute(select(User).where(User.id == f"mp-fac-{TAG}"))).scalar_one()
            db.add(IpRecord(id=tag, uploader_id=u.id, ip_type="UNKNOWN_OTHER",
                            processing_status="QUEUED", verification_status="UNVERIFIED",
                            workflow_state="UPLOADED"))
            await db.commit()

    asyncio.run(_create())
    try:
        out = run_document_pipeline(path, tag)  # must never raise to caller
    finally:
        pass

    async def _read():
        async with get_async_session_context() as db:
            r = (await db.execute(select(IpRecord).where(IpRecord.id == tag))).scalar_one()
            contribs = (await db.execute(select(IpContributor).where(
                IpContributor.ip_record_id == tag))).scalars().all()
            reqs = (await db.execute(select(AssociationRequest).where(
                AssociationRequest.ip_record_id == tag))).scalars().all()
            jobs = (await db.execute(select(ProcessingJob).where(
                ProcessingJob.ip_record_id == tag))).scalars().all()
            return (r.workflow_state, r.processing_status, r.verification_status,
                    r.title, r.patent_number, r.design_number, r.application_number,
                    r.serial_number, r.filing_date, r.published_date, r.grant_date,
                    r.registration_date,
                    [(c.is_external, c.name, c.user_id) for c in contribs],
                    len(reqs), [(j.job_type, j.status) for j in jobs])

    state = asyncio.run(_read())

    async def _delete():
        async with get_async_session_context() as db:
            for model, cond in ((ProcessingJob, ProcessingJob.ip_record_id == tag),
                               (VerificationAttempt, VerificationAttempt.ip_record_id == tag),
                               (IpContributor, IpContributor.ip_record_id == tag),
                               (AssociationRequest, AssociationRequest.ip_record_id == tag),
                               (DuplicateCase, or_(DuplicateCase.ip_record_id_1 == tag,
                                                   DuplicateCase.ip_record_id_2 == tag)),
                               (ConflictCase, ConflictCase.ip_record_id == tag),
                               (IpFile, IpFile.ip_record_id == tag)):
                for row in (await db.execute(select(model).where(cond))).scalars().all():
                    await db.delete(row)
            for snap in (await db.execute(select(FacultyProfileSnapshot).where(
                    FacultyProfileSnapshot.faculty_id == f"mp-fac-{TAG}"))).scalars().all():
                await db.delete(snap)
            rec = (await db.execute(select(IpRecord).where(IpRecord.id == tag))).scalar_one_or_none()
            if rec is not None:
                await db.delete(rec)
            await db.commit()

    asyncio.run(_delete())
    return out, state


def test_txt_upload_rejected_without_record(client, faculty):
    before = _record_count()
    r = client.post("/api/v1/uploads/", files={"file": ("evil.txt", b"not a pdf", "text/plain")},
                    headers=_h(client, _tok(faculty["id"])))
    assert r.status_code == 400, r.text
    assert r.json().get("error") == "UPLOAD_ERROR"
    assert _record_count() == before


def _assert_safe_failure(state):
    (wf, proc, ver, title, pat, des, appn, ser, fil, pub, grant, reg,
     contribs, n_reqs, jobs) = state
    # No fabricated metadata of any kind.
    assert title is None
    assert pat is None and des is None and appn is None and ser is None
    assert fil is None and pub is None and grant is None and reg is None
    # No invented associations or identities.
    assert contribs == []
    assert n_reqs == 0
    # Never a false success state.
    assert wf not in ("VERIFIED", "GRANTED", "FACULTY_ASSOCIATION_COMPLETE"), wf
    assert ver != "VERIFIED"
    # Terminal, recorded outcome (orchestrator job completed-with-errors or failed).
    terminal = {"SUCCESS", "COMPLETED_WITH_ERRORS", "AWAITING_REVIEW", "FAILED"}
    assert jobs, "pipeline must leave job traceability"
    assert all(s in terminal for _, s in jobs), jobs


def test_truncated_pdf_fails_safe(faculty):
    out, state = _run_pipeline_case("truncated", _make_pdf_bytes(VALID_TEXT)[:400])
    assert out.get("status") in ("SUCCESS", "FAILURE"), out
    _assert_safe_failure(state)


def test_pdf_prefix_garbage_fails_safe(faculty):
    out, state = _run_pipeline_case("garbage", GARBAGE)
    assert out.get("status") in ("SUCCESS", "FAILURE"), out
    _assert_safe_failure(state)


def test_valid_pdf_still_processes(faculty):
    out, state = _run_pipeline_case("valid", _make_pdf_bytes(VALID_TEXT))
    assert out.get("status") == "SUCCESS", out
    (wf, proc, ver, title, pat, des, appn, ser, fil, pub, grant, reg,
     contribs, n_reqs, jobs) = state
    assert appn == "202541777777", state
    # Filing midnight IST is stored as the same instant in UTC (2024-05-04
    # 18:30Z); compare the calendar day in IST, not the raw UTC string.
    from datetime import timedelta, timezone as _tz

    _ist = _tz(timedelta(hours=5, minutes=30))
    assert fil is not None and fil.astimezone(_ist).date().isoformat() == "2024-05-05", fil
    assert ver == "VERIFIED" and wf == "FACULTY_ASSOCIATION_COMPLETE"
    assert n_reqs == 0

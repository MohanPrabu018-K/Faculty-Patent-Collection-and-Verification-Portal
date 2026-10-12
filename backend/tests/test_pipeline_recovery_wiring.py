# -*- coding: utf-8 -*-
"""Scheduler wiring + authz for stranded-pipeline recovery (defect D-002).

``requeue_stuck_pipelines`` is only useful if it is actually scheduled and
reachable by an operator. These tests pin the wiring so a future refactor
cannot silently drop the recovery sweep (re-introducing permanently-stuck
uploads) or open the endpoint to non-admin roles.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import app_settings, scheduler_settings
from app.core.security import generate_jwt_token
from app.main import app
from app.services.scheduler import get_scheduler, lifespan_scheduler

client = TestClient(app)


def _csrf_client():
    """CSRF is checked before routing/authorization, so a bare client would
    only ever assert the CSRF layer. Seed a matching cookie+header pair to
    reach the role check underneath."""
    c = TestClient(app)
    c.cookies.set("csrf_token", "t")
    return c


CSRF = {"X-CSRF-Token": "t"}


def _tok(sub, role, dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


ADMIN = {"Authorization": f"Bearer {_tok('test-admin-001', 'super_admin')}"}
HOD_A = {"Authorization": f"Bearer {_tok('hod-a-001', 'hod_admin', 'dept-a', 'HODA001')}"}
FAC_A = {"Authorization": f"Bearer {_tok('fac-a-001', 'faculty', 'dept-a', 'FACA001')}"}

REQUEUE_PATH = "/api/v1/verification/pipeline/requeue-stalled"


class TestPipelineRecoveryWiring:
    @pytest.mark.asyncio
    async def test_recovery_job_is_registered(self):
        import app.services.scheduler as scheduler_module

        scheduler_module._scheduler = None
        async with lifespan_scheduler(app):
            job_ids = {job.id for job in get_scheduler().get_jobs()}
            assert "recover_stuck_pipelines" in job_ids
        scheduler_module._scheduler = None

    @pytest.mark.asyncio
    async def test_recovery_job_runs_on_a_fixed_interval(self):
        """A recovery sweep must be periodic; a one-shot would never re-fire."""
        import app.services.scheduler as scheduler_module

        scheduler_module._scheduler = None
        async with lifespan_scheduler(app):
            job = next(j for j in get_scheduler().get_jobs() if j.id == "recover_stuck_pipelines")
            assert job.trigger.interval.total_seconds() > 0
        scheduler_module._scheduler = None

    @pytest.mark.asyncio
    async def test_recovery_job_is_not_duplicated_across_lifespans(self):
        import app.services.scheduler as scheduler_module

        scheduler_module._scheduler = None
        async with lifespan_scheduler(app):
            async with lifespan_scheduler(app):
                jobs = [j for j in get_scheduler().get_jobs() if j.id == "recover_stuck_pipelines"]
                assert len(jobs) == 1
        scheduler_module._scheduler = None


class TestRecoverySettings:
    def test_stuck_threshold_is_positive(self):
        """A non-positive threshold would race every in-flight pipeline."""
        assert scheduler_settings.pipeline_stuck_after_seconds > 0

    def test_interval_is_positive(self):
        assert scheduler_settings.pipeline_recovery_interval_minutes > 0

    def test_default_stuck_threshold_allows_a_slow_pipeline(self):
        """Default 300s must exceed a normal 11-agent run, or healthy jobs get re-driven."""
        assert scheduler_settings.pipeline_stuck_after_seconds >= 60


class TestRequeueEndpointAuthz:
    def test_endpoint_is_exposed(self):
        # Routers are lazily mounted (_IncludedRouter), so the concrete path
        # table is only materialised in the OpenAPI schema.
        schema = app.openapi()
        assert REQUEUE_PATH in schema["paths"], sorted(schema["paths"])
        assert "post" in schema["paths"][REQUEUE_PATH]

    def test_unauthenticated_cannot_requeue(self):
        c = _csrf_client()
        assert c.post(REQUEUE_PATH, headers=CSRF).status_code in (401, 403)

    def test_faculty_cannot_requeue(self):
        c = _csrf_client()
        assert c.post(REQUEUE_PATH, headers={**FAC_A, **CSRF}).status_code in (401, 403)

    def test_hod_cannot_requeue(self):
        c = _csrf_client()
        assert c.post(REQUEUE_PATH, headers={**HOD_A, **CSRF}).status_code in (401, 403)

    def test_super_admin_can_requeue(self):
        c = _csrf_client()
        r = c.post(REQUEUE_PATH, headers={**ADMIN, **CSRF})
        assert r.status_code == 200
        body = r.json()
        # The operator must be told what happened, not just "ok".
        assert set(body) >= {"message", "stuck_found", "requeued", "skipped_missing_file"}
        assert isinstance(body["requeued"], list)

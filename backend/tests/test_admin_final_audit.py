"""Regression tests for final admin module audit (behavioral, repo-style)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_institutional_requires_auth():
    r = client.post("/api/v1/verification/institutional/some-id", json={"decision": "verify"})
    assert r.status_code in (400, 401, 403, 404)


def test_institutional_get_requires_auth():
    r = client.get("/api/v1/verification/institutional/some-id")
    assert r.status_code in (401, 403, 404)


def test_admin_settings_patch_requires_auth():
    # No CSRF token -> middleware 400 before auth, same convention as faculty upload test.
    r = client.patch("/api/v1/admin/settings", json={"max_upload_mb": 25})
    assert r.status_code in (400, 401, 403)


def test_admin_settings_get_requires_auth():
    r = client.get("/api/v1/admin/settings")
    assert r.status_code in (401, 403)


def test_export_docx_renders():
    from app.services.export_renderers import render_csv, render_docx, render_pdf, render_xlsx
    for renderer in (render_csv, render_docx, render_pdf, render_xlsx):
        data = renderer([])
        assert isinstance(data, bytes) and len(data) > 0
    assert render_docx([])[:2] == b"PK"  # zip container
    assert render_xlsx([])[:2] == b"PK"
    assert render_pdf([]).startswith(b"%PDF")


def test_export_formats_distinct():
    from app.services.export_renderers import render_csv, render_docx, render_pdf, render_xlsx
    assert render_csv([]) != render_pdf([])
    assert render_docx([]) != render_xlsx([])


def test_runtime_settings_bounds():
    import pytest

    from app.core.runtime_settings import MAX_UPLOAD_MB, MIN_UPLOAD_MB, set_max_upload_mb
    assert MIN_UPLOAD_MB == 1.0
    assert MAX_UPLOAD_MB == 100.0
    with pytest.raises(ValueError):
        set_max_upload_mb(1000)
    with pytest.raises(ValueError):
        set_max_upload_mb(0)


def test_export_service_supports_docx_and_filters():
    import asyncio

    from app.services.search_analytics import ExportFormat, get_export_service
    assert ExportFormat("docx") is not None
    svc = get_export_service()
    job = asyncio.run(svc.create_export(ExportFormat.DOCX, {"ip_type": "PATENT", "search": "zzz-no-match", "processing_status": "COMPLETED"}, "test-user"))
    assert job.format == ExportFormat.DOCX
    status = asyncio.run(svc.get_job_status(job.id))
    assert status["record_count"] == 0

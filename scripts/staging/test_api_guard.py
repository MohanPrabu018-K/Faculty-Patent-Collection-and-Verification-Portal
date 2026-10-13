"""Focused, dependency-free tests for the Python API-target guard + sandboxed env.

These never touch a database or a network socket: they exercise the pure
decision logic only, so they can run anywhere pytest is available. Run them with
the backend virtualenv:

    & backend\\.venv\\Scripts\\python.exe -m pytest scripts/staging/test_api_guard.py -q

They prove the fail-closed contract implemented for the Python E2E entry points
reported as risky in QA (``scripts/e2e_backgroundtasks_pipeline.py`` and
``scripts/verify_real_upload_459641.py``):

1. A target is only ever driven with ``STAGING_CONFIRM=1`` and an explicit,
   valid ``STAGING_API_URL``.
2. Production hosts and the production hosting namespaces are refused even when
   allow-listed.
3. Non-loopback targets require an exact ``STAGING_ALLOWED_HOSTS`` entry.
4. A spawned backend subprocess can only inherit a validated disposable
   ``DATABASE_URL``; an ambient production ``DATABASE_URL`` can never leak.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard  # noqa: E402

LOOPBACK_API = "http://127.0.0.1:8099"
LOOPBACK_API_V6 = "http://[::1]:8000"
PROD_PAGES_DEV = "https://faculty-patent-collection-and-verification-portal.pages.dev"
PROD_RENDER_API = "https://faculty-patent-portal-api.onrender.com"
SUFFIX_SPOOF = "https://evil.pages.dev.example.net"
NON_PROVIDER_REMOTE = "https://staging-api.internal.example.net"
DB_LOOPBACK = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_staging"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "STAGING_CONFIRM",
        "STAGING_API_URL",
        "STAGING_ALLOWED_HOSTS",
        "STAGING_FRONTEND_URL",
        "STAGING_DATABASE_URL",
        "STAGING_ALLOW_REMOTE_DB",
        "STAGING_DB_HOST_ALLOWLIST",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGING_CONFIRM", "1")


# --- require_staging_confirm / resolve_staging_api_url ------------------------


def test_confirm_is_required() -> None:
    with pytest.raises(guard.ProductionTargetError, match="STAGING_CONFIRM"):
        guard.resolve_staging_api_url()


def test_api_url_is_required_even_with_confirm(monkeypatch) -> None:
    _confirm(monkeypatch)
    with pytest.raises(guard.ProductionTargetError, match="STAGING_API_URL is required"):
        guard.resolve_staging_api_url()


def test_loopback_resolves_with_confirm(monkeypatch) -> None:
    _confirm(monkeypatch)
    monkeypatch.setenv("STAGING_API_URL", LOOPBACK_API)
    assert guard.resolve_staging_api_url() == LOOPBACK_API


def test_resolve_never_falls_back_to_a_default(monkeypatch) -> None:
    _confirm(monkeypatch)
    # No STAGING_API_URL anywhere: nothing may be driven by default.
    with pytest.raises(guard.ProductionTargetError, match="STAGING_API_URL is required"):
        guard.resolve_staging_api_url()


# --- assert_staging_api_url: unsafe / malformed targets -----------------------


@pytest.mark.parametrize(
    "url",
    ["", "  ", None, "not-a-url", "localhost:8000", "ftp://127.0.0.1/x"],
)
def test_unsafe_targets_refused(url) -> None:
    with pytest.raises(guard.ProductionTargetError):
        guard.assert_staging_api_url("STAGING_API_URL", url)


def test_scheme_checked() -> None:
    with pytest.raises(guard.ProductionTargetError, match="scheme"):
        guard.assert_staging_api_url("STAGING_API_URL", "mysql://127.0.0.1:3306/db")


# --- production targets refused even when allow-listed ------------------------


@pytest.mark.parametrize("url", [PROD_PAGES_DEV, PROD_RENDER_API])
def test_production_hosts_refused_even_when_allowlisted(monkeypatch, url) -> None:
    host = guard.api_host_of(url)
    monkeypatch.setenv("STAGING_ALLOWED_HOSTS", host)
    with pytest.raises(guard.ProductionTargetError, match="production host"):
        guard.assert_staging_api_url("STAGING_API_URL", url)


def test_production_suffix_refused_even_when_allowlisted(monkeypatch) -> None:
    # Any host under .pages.dev / .onrender.com is production-namespaced and can
    # never be allow-listed in, even with an exact-looking entry.
    monkeypatch.setenv("STAGING_ALLOWED_HOSTS", "foo.pages.dev")
    with pytest.raises(guard.ProductionTargetError, match="production host"):
        guard.assert_staging_api_url("STAGING_API_URL", "https://foo.pages.dev")


def test_production_suffix_detected_at_label_boundary() -> None:
    # "notpages.dev" does not end in ".pages.dev" on a label boundary: it is not
    # production, but it is also not loopback or allow-listed, so it must refuse
    # for a different reason (missing allowlist entry), never silently pass.
    with pytest.raises(guard.ProductionTargetError, match="STAGING_ALLOWED_HOSTS"):
        guard.assert_staging_api_url("STAGING_API_URL", "https://notpages.dev")


# --- remote non-production targets require an exact allowlist entry -----------


def test_remote_requires_allowlist(monkeypatch) -> None:
    with pytest.raises(guard.ProductionTargetError, match="STAGING_ALLOWED_HOSTS"):
        guard.assert_staging_api_url("STAGING_API_URL", NON_PROVIDER_REMOTE)


def test_remote_requires_exact_allowlist_entry(monkeypatch) -> None:
    monkeypatch.setenv("STAGING_ALLOWED_HOSTS", "some-other-host.example.net")
    with pytest.raises(guard.ProductionTargetError, match="not in STAGING_ALLOWED_HOSTS"):
        guard.assert_staging_api_url("STAGING_API_URL", NON_PROVIDER_REMOTE)


def test_remote_allowlisted_is_ok(monkeypatch) -> None:
    monkeypatch.setenv("STAGING_ALLOWED_HOSTS", "staging-api.internal.example.net")
    assert guard.assert_staging_api_url("STAGING_API_URL", NON_PROVIDER_REMOTE) == "staging-api.internal.example.net"


# --- loopback always allowed, host normalization ------------------------------


def test_loopback_always_allowed_without_allowlist() -> None:
    guard.assert_staging_api_url("STAGING_API_URL", LOOPBACK_API)
    guard.assert_staging_api_url("STAGING_API_URL", LOOPBACK_API_V6)
    guard.assert_staging_api_url("STAGING_API_URL", "http://localhost:8000")
    guard.assert_staging_api_url("STAGING_API_URL", "http://127.0.0.1./health")


def test_known_limitation_scheme_only_http_https_pinned() -> None:
    """Pins current behaviour: the API guard accepts http + https only."""
    assert guard.API_ACCEPTED_SCHEMES == ("http", "https")


# --- sandboxed_backend_env ----------------------------------------------------


def test_sandbox_env_overrides_db_and_pins_nonprod(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@ep-x.aws.neon.tech/neondb")
    monkeypatch.setenv("STAGING_ALLOW_REMOTE_DB", "1")
    monkeypatch.setenv("STAGING_ALLOWED_HOSTS", "horse.example.net")
    env = guard.sandboxed_backend_env(DB_LOOPBACK, backend_dir=r"C:\\repo\\backend")
    assert env["DATABASE_URL"] == DB_LOOPBACK
    assert env["STAGING_DATABASE_URL"] == DB_LOOPBACK
    assert env["APP_ENV"] == "development"
    assert env["E2E_TEST"] == "1"
    assert env["SCHEDULER_ENABLED"] == "false"
    assert env["COOKIE_SECURE"] == "false"
    assert env["PYTHONPATH"] == r"C:\\repo\\backend"
    # Parent's remote-opt-in / allowlist tokens are never passed to the child.
    assert "STAGING_ALLOW_REMOTE_DB" not in env
    assert "STAGING_ALLOWED_HOSTS" not in env
    assert "STAGING_DB_HOST_ALLOWLIST" not in env


def test_sandbox_env_rejects_unsafe_db() -> None:
    with pytest.raises(guard.ProductionTargetError, match="sandboxed backend env"):
        guard.sandboxed_backend_env(
            "postgresql+asyncpg://u:p@ep-x.aws.neon.tech/neondb",
            backend_dir=r"C:\\repo\\backend",
        )


def test_sandbox_env_keeps_unrelated_ambient_keys(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "C:\\Windows\\System32")
    monkeypatch.setenv("TMP", r"C:\\Temp")
    env = guard.sandboxed_backend_env(DB_LOOPBACK, backend_dir=r"C:\\repo\\backend")
    assert env["PATH"] == "C:\\Windows\\System32"
    assert env["TMP"] == r"C:\\Temp"
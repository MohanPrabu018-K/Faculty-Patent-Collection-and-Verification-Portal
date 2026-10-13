"""Local, dependency-free tests for the staging DB guard (``guard.py``).

These never touch a database: they exercise the pure decision logic only, so
they can run anywhere. Run them with the backend virtualenv:

    & backend\\.venv\\Scripts\\python.exe -m pytest scripts/staging/test_guard.py -q

They exist to prove two things for the hosted-staging review:

1. The allowlist path CANNOT be configured to reach production (provider hosts
   are refused before the allowlist is ever consulted; reserved DB names are
   refused even when opt-in + allowlisted).
2. The guard's documented limitations (provider-marker blanket refusal, the
   loose ``ci`` disposable marker) are pinned so a future change cannot silently
   weaken them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard  # noqa: E402

LOOPBACK = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_staging"
RENDER_PUBLIC = "postgresql+asyncpg://u:p@dpg-abc123-a.oregon-postgres.render.com/faculty_portal_staging"
NEON_PUBLIC = "postgresql+asyncpg://u:p@ep-cool-1.us-east-2.aws.neon.tech/faculty_portal_staging"
SUPABASE = "postgresql+asyncpg://u:p@db.abcdefgh.supabase.co/faculty_portal_staging"
NON_PROVIDER = "postgresql+asyncpg://u:p@staging-db.internal.example.net/faculty_portal_staging"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "STAGING_ALLOW_REMOTE_DB",
        "STAGING_DB_HOST_ALLOWLIST",
        "STAGING_DATABASE_URL",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _opt_in(monkeypatch: pytest.MonkeyPatch, hosts: str) -> None:
    monkeypatch.setenv("STAGING_ALLOW_REMOTE_DB", "1")
    monkeypatch.setenv("STAGING_DB_HOST_ALLOWLIST", hosts)


# --- positive paths -----------------------------------------------------------


def test_loopback_is_always_allowed() -> None:
    guard.assert_disposable_database(LOOPBACK)  # no exception


def test_non_provider_remote_allowed_when_opt_in_and_allowlisted(monkeypatch) -> None:
    _opt_in(monkeypatch, "staging-db.internal.example.net")
    guard.assert_disposable_database(NON_PROVIDER)


# --- production-safety: the allowlist can never reach production --------------


@pytest.mark.parametrize("url", [RENDER_PUBLIC, NEON_PUBLIC, SUPABASE])
def test_production_provider_hosts_refused_even_when_allowlisted(monkeypatch, url) -> None:
    # Opt in AND explicitly allowlist the provider host: it must still be refused.
    host = guard.host_of(url)
    _opt_in(monkeypatch, host)
    with pytest.raises(guard.ProductionTargetError, match="managed-cloud marker"):
        guard.assert_disposable_database(url)


@pytest.mark.parametrize("db_name", ["faculty_portal", "neondb", "postgres", "prod", "production"])
def test_reserved_db_names_refused_even_when_allowlisted(monkeypatch, db_name) -> None:
    _opt_in(monkeypatch, "staging-db.internal.example.net")
    url = f"postgresql+asyncpg://u:p@staging-db.internal.example.net/{db_name}"
    with pytest.raises(guard.ProductionTargetError, match="reserved for production"):
        guard.assert_disposable_database(url)


def test_remote_requires_opt_in(monkeypatch) -> None:
    with pytest.raises(guard.ProductionTargetError, match="STAGING_ALLOW_REMOTE_DB"):
        guard.assert_disposable_database(NON_PROVIDER)


def test_remote_requires_exact_allowlist_entry(monkeypatch) -> None:
    monkeypatch.setenv("STAGING_ALLOW_REMOTE_DB", "1")
    monkeypatch.setenv("STAGING_DB_HOST_ALLOWLIST", "some-other-host.example.net")
    with pytest.raises(guard.ProductionTargetError, match="not in STAGING_DB_HOST_ALLOWLIST"):
        guard.assert_disposable_database(NON_PROVIDER)


def test_non_disposable_db_name_refused(monkeypatch) -> None:
    _opt_in(monkeypatch, "staging-db.internal.example.net")
    url = "postgresql+asyncpg://u:p@staging-db.internal.example.net/customers"
    with pytest.raises(guard.ProductionTargetError, match="does not look disposable"):
        guard.assert_disposable_database(url)


def test_non_postgres_scheme_refused() -> None:
    with pytest.raises(guard.ProductionTargetError, match="non-PostgreSQL URL scheme"):
        guard.assert_disposable_database("mysql://u:p@127.0.0.1:3306/faculty_portal_staging")


# --- resolve_staging_database_url never falls back to the app DATABASE_URL ----


def test_resolve_never_falls_back_to_database_url(monkeypatch) -> None:
    # A leftover production DATABASE_URL must NOT make the tooling target it.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@ep-x.aws.neon.tech/neondb")
    with pytest.raises(guard.ProductionTargetError):
        guard.resolve_staging_database_url()


def test_resolve_uses_only_staging_database_url(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@ep-x.aws.neon.tech/neondb")
    monkeypatch.setenv("STAGING_DATABASE_URL", LOOPBACK)
    assert guard.resolve_staging_database_url() == LOOPBACK


# --- documented limitations (pinned; hardening candidates, NOT applied) -------


def test_known_limitation_ci_marker_is_loose(monkeypatch) -> None:
    """``DISPOSABLE_DB_MARKERS`` includes ``"ci"``, a two-character substring that
    also appears inside ordinary names (e.g. "citations", "facility", "special").
    This pins the CURRENT behaviour so tightening it later is a deliberate,
    visible change rather than a silent regression."""
    _opt_in(monkeypatch, "staging-db.internal.example.net")
    url = "postgresql+asyncpg://u:p@staging-db.internal.example.net/faculty_portal_citations"
    guard.assert_disposable_database(url)  # currently allowed (host is not a marker)


# --- CLI exit codes -----------------------------------------------------------


def test_cli_accepts_loopback() -> None:
    assert guard.main(["guard.py", LOOPBACK]) == 0


def test_cli_refuses_production_provider() -> None:
    assert guard.main(["guard.py", RENDER_PUBLIC]) == 1

"""Fail-closed guard for staging/test database + target URLs.

This module is the single source of truth for "is it safe to write to this
database / drive this URL?" It is intentionally dependency-free so it can be
imported by:

  * ``provision_staging.py`` / ``teardown_staging.py`` (Python tooling)
  * the pytest safety conftest (backend)
  * a CLI: ``python scripts/staging/guard.py <database-url>``

Design rules (fail closed):

Databases:

1. Loopback hosts are always allowed (local disposable Postgres).
2. Known production / managed-cloud hosts are ALWAYS refused, even with an
   explicit opt-in. There is no override for the production host.
3. Any other remote host requires BOTH ``STAGING_ALLOW_REMOTE_DB=1`` and the
   host to appear in ``STAGING_DB_HOST_ALLOWLIST`` (comma-separated).
4. The database name itself must look disposable (``staging`` or ``test``)
   unless it is loopback.
5. ``STAGING_DATABASE_URL`` is the only env var the staging tooling reads;
   it never falls back to the application ``DATABASE_URL``. This makes it
   impossible to "accidentally" point the tooling at production by leaving the
   app env unset.

API / hosted targets (mirrors ``frontend/tests-staging/guard.ts``):

6. ``STAGING_CONFIRM=1`` is required for any run that drives a real API.
7. Loopback API hosts are always allowed.
8. The known production hosts AND both production hosting namespaces
   (``.pages.dev`` / ``.onrender.com``) are ALWAYS refused, even if allow-listed.
9. Any other non-loopback API host must appear in ``STAGING_ALLOWED_HOSTS``.

The production host deny-list is derived from what this repo actually uses in
production (Neon Postgres + Render). Extend it if new managed providers are
adopted.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

# Hosts / suffixes that are unconditionally refused (production or managed
# cloud where a "staging" mistake would hit real infrastructure).
PRODUCTION_HOST_MARKERS: tuple[str, ...] = (
    "neon.tech",
    "onrender.com",
    "render.com",
    "supabase.co",
    "supabase.com",
    "amazonaws.com",
    "azure.com",
    "rds.amazonaws.com",
)

# Exact database names that must never be written by staging tooling.
PRODUCTION_DB_NAMES: frozenset[str] = frozenset(
    {"neondb", "faculty_portal", "production", "prod", "postgres"}
)

LOOPBACK_HOSTS: frozenset[str] = frozenset({"", "localhost", "127.0.0.1", "::1", "[::1]"})

ACCEPTED_SCHEMES: tuple[str, ...] = (
    "postgresql",
    "postgresql+asyncpg",
    "postgresql+psycopg2",
    "postgres",
)

DISPOSABLE_DB_MARKERS: tuple[str, ...] = ("staging", "stage", "test", "ci", "disposable", "scratch")


class ProductionTargetError(RuntimeError):
    """Raised when a target looks like production or is otherwise unsafe."""


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def db_name_of(url: str) -> str:
    return (urlsplit(url).path or "").lstrip("/").lower()


def is_loopback(url: str) -> bool:
    return host_of(url) in LOOPBACK_HOSTS


def _host_allowlist() -> set[str]:
    raw = os.environ.get("STAGING_DB_HOST_ALLOWLIST", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def assert_disposable_database(url: str | None, *, context: str = "staging tooling") -> None:
    """Raise ProductionTargetError unless *url* is a disposable staging DB.

    Never reads ``DATABASE_URL``: callers pass the already-resolved staging URL.
    """
    if not url or not isinstance(url, str):
        raise ProductionTargetError(
            f"{context}: no database URL supplied. Set STAGING_DATABASE_URL to an "
            "explicit disposable staging/test database."
        )
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ACCEPTED_SCHEMES:
        raise ProductionTargetError(
            f"{context}: refusing non-PostgreSQL URL scheme {scheme!r}."
        )

    host = host_of(url)
    db_name = db_name_of(url)

    # Rule 3/1: loopback is the safe default path.
    if host in LOOPBACK_HOSTS:
        return

    # Rule 2: production / managed cloud is an absolute refusal.
    if any(marker in host for marker in PRODUCTION_HOST_MARKERS):
        raise ProductionTargetError(
            f"{context}: refusing remote host {host!r} — it matches a production/"
            "managed-cloud marker. Staging tooling must never touch production."
        )

    # Rule 3: opt-in + allowlist for any other remote host.
    if os.environ.get("STAGING_ALLOW_REMOTE_DB") != "1":
        raise ProductionTargetError(
            f"{context}: refusing non-loopback host {host!r}. Set "
            "STAGING_ALLOW_REMOTE_DB=1 AND list the host in "
            "STAGING_DB_HOST_ALLOWLIST to acknowledge a deliberately chosen "
            "remote staging database."
        )
    if host not in _host_allowlist():
        raise ProductionTargetError(
            f"{context}: host {host!r} is not in STAGING_DB_HOST_ALLOWLIST "
            f"({sorted(_host_allowlist()) or 'empty'})."
        )

    # Rule 4: the database name must look disposable too.
    if db_name in PRODUCTION_DB_NAMES:
        raise ProductionTargetError(
            f"{context}: refusing database name {db_name!r} — it is reserved for "
            "production."
        )
    if not any(marker in db_name for marker in DISPOSABLE_DB_MARKERS):
        raise ProductionTargetError(
            f"{context}: database name {db_name!r} does not look disposable "
            f"(expected to contain one of {DISPOSABLE_DB_MARKERS})."
        )


def resolve_staging_database_url() -> str:
    """Return STAGING_DATABASE_URL after validating it. Never falls back."""
    url = os.environ.get("STAGING_DATABASE_URL", "").strip()
    assert_disposable_database(url, context="STAGING_DATABASE_URL")
    return url


# --- API / hosted target guard -------------------------------------------------
# Mirrors the frontend staging guard (frontend/tests-staging/guard.ts) so that
# Python entry points and Playwright agree on what an acceptable target is.

API_ACCEPTED_SCHEMES: tuple[str, ...] = ("http", "https")

API_LOOPBACK_HOSTS: frozenset[str] = frozenset({"", "localhost", "127.0.0.1", "::1", "[::1]"})

# Exact production hosts this repo actually uses.
API_PRODUCTION_HOSTS: frozenset[str] = frozenset(
    {
        "faculty-patent-collection-and-verification-portal.pages.dev",
        "faculty-patent-portal-api.onrender.com",
    }
)

# Production hosting namespaces — refused for ANY host ending in these labels,
# including in the middle of a hostname (suffix spoofing).
API_PRODUCTION_HOST_SUFFIXES: tuple[str, ...] = (".pages.dev", ".onrender.com")


def api_host_of(url: str) -> str:
    """Normalized hostname (lowercase, single trailing DNS dot collapsed)."""
    host = host_of(url)
    if host.endswith(".") and len(host) > 1:
        host = host[:-1]
    return host


def is_loopback_api_host(host: str) -> bool:
    return host in API_LOOPBACK_HOSTS


def is_api_production_host(host: str) -> bool:
    return host in API_PRODUCTION_HOSTS or any(
        host.endswith(suffix) for suffix in API_PRODUCTION_HOST_SUFFIXES
    )


def _api_host_allowlist() -> set[str]:
    raw = os.environ.get("STAGING_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def require_staging_confirm(context: str) -> None:
    """Fail closed unless STAGING_CONFIRM=1 (explicit human acknowledgement)."""
    if os.environ.get("STAGING_CONFIRM") != "1":
        raise ProductionTargetError(
            f"{context}: STAGING_CONFIRM must be \"1\". Set it only after "
            "verifying the target environment is NOT production."
        )


def assert_staging_api_url(label: str, url: str) -> str:
    """Raise `ProductionTargetError` unless *url* is a safe API target.

    Loopback is always allowed. Production hosts and production hosting
    namespaces are ALWAYS refused (even if allow-listed). Any other non-loopback
    host must appear in ``STAGING_ALLOWED_HOSTS``. Returns the normalized
    hostname when safe.
    """
    if not url or not isinstance(url, str):
        raise ProductionTargetError(f"{label}: target URL is missing.")
    value = url.strip()
    if urlsplit(value).scheme.lower() not in API_ACCEPTED_SCHEMES:
        raise ProductionTargetError(
            f"{label}: refusing URL scheme {urlsplit(value).scheme!r} — only "
            "http/https API targets are supported."
        )
    host = api_host_of(value)
    if not host:
        raise ProductionTargetError(f"{label}: URL has no host: {value!r}.")
    if is_loopback_api_host(host):
        return host
    if is_api_production_host(host):
        raise ProductionTargetError(
            f"{label}: host {host!r} is a known production host. Refusing to "
            "target production."
        )
    if host not in _api_host_allowlist():
        raise ProductionTargetError(
            f"{label}: host {host!r} is not loopback and not in "
            f"STAGING_ALLOWED_HOSTS ({sorted(_api_host_allowlist()) or 'empty'})."
        )
    return host


def resolve_staging_api_url(label: str = "STAGING_API_URL") -> str:
    """Return a validated, explicitly confirmed API target URL.

    Requires ``STAGING_CONFIRM=1`` and a well-formed address; never falls back
    to an application default or any production URL.
    """
    require_staging_confirm(f"{label}")
    url = os.environ.get(label, "").strip()
    if not url:
        raise ProductionTargetError(
            f"{label} is required. Pass an explicit non-production API URL "
            "(loopback or an allow-listed staging host)."
        )
    assert_staging_api_url(label, url)
    return url


# Env pins forced onto any backend subprocess the staging tooling spawns.
_BACKEND_CHILD_ENV_PINS: dict[str, str] = {
    "APP_ENV": "development",
    "E2E_TEST": "1",
    "SCHEDULER_ENABLED": "false",
    "COOKIE_SECURE": "false",
}


def sandboxed_backend_env(
    staging_db_url: str, *, backend_dir: str, base_env: dict[str, str] | None = None
) -> dict[str, str]:
    """Build the ONLY environment a spawned backend subprocess may inherit.

    The subprocess keeps the ambient environment (PATH, TEMP, ...) but cannot
    accidentally inherit a database/API override:

    * ``staging_db_url`` MUST already be validated (``assert_disposable_database``
      or ``resolve_staging_database_url``) — it is re-validated here.
    * ``DATABASE_URL`` is force-set to the validated disposable target, so the
      app's root ``.env`` DATABASE_URL (if any) is never consulted and an
      ambient production ``DATABASE_URL`` can never leak into the child.
      ``STAGING_DATABASE_URL`` is pinned to the same value for consistency.
    * Remote-opt-in / allowlist tokens are dropped from the child environment so
      a parent's ``STAGING_ALLOW_*`` values cannot silently broaden what the
      child may reach.
    * Non-production run flags are pinned and ``PYTHONPATH`` forces the backend
      package onto the import path.
    """
    assert_disposable_database(staging_db_url, context="sandboxed backend env")
    base = dict(base_env if base_env is not None else os.environ)
    for drop in (
        "STAGING_ALLOW_REMOTE_DB",
        "STAGING_DB_HOST_ALLOWLIST",
        "STAGING_ALLOWED_HOSTS",
    ):
        base.pop(drop, None)
    base.update(
        {
            "DATABASE_URL": staging_db_url,
            "STAGING_DATABASE_URL": staging_db_url,
            "PYTHONPATH": str(backend_dir),
            **_BACKEND_CHILD_ENV_PINS,
        }
    )
    return base


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/staging/guard.py <database-url>", file=sys.stderr)
        return 2
    try:
        assert_disposable_database(argv[1], context="guard CLI")
    except ProductionTargetError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print("OK: target is a disposable staging/test database")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Pytest configuration for the backend test-suite.

Safety guard
------------
The suite creates and deletes real rows (departments, users, records, ...).
There is no separate ``TEST_DATABASE_URL``; the tests use whatever
``DATABASE_URL`` the app resolves (environment variable, else the repo ``.env``).
The repo ``.env`` points at the hosted production database while
``APP_ENV=development``, so a plain ``pytest`` run would write to production.

To prevent that, abort the run unless ``DATABASE_URL`` resolves to a local
host. Running against a deliberately chosen remote/staging database requires
an explicit opt-in:

    set ALLOW_REMOTE_TEST_DB=1   # PowerShell: $env:ALLOW_REMOTE_TEST_DB='1'
"""
import os
from urllib.parse import urlsplit

import pytest

_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
_ALLOW_ENV = "ALLOW_REMOTE_TEST_DB"


def pytest_configure(config: pytest.Config) -> None:
    # Importing the app settings here reflects the same effective DATABASE_URL
    # (process env overriding .env) that the tests themselves will use.
    from app.core.config import database_settings

    url = database_settings.database_url or ""
    host = (urlsplit(url).hostname or "").lower()

    if host in _LOCAL_HOSTS or os.environ.get(_ALLOW_ENV) == "1":
        return

    pytest.exit(
        "Refusing to run the backend test-suite against a non-local database "
        f"(host={host!r}). These tests create and delete rows and must run "
        "against a disposable/local database. Point DATABASE_URL at localhost, "
        f"or set {_ALLOW_ENV}=1 to override this guard deliberately.",
        returncode=1,
    )

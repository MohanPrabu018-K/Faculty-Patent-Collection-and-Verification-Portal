from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from app.core.config import database_settings

# Under pytest the FastAPI TestClient opens/closes a fresh event loop per
# request; a pooled asyncpg connection bound to a closed loop then raises
# "Event loop is closed". Use NullPool during tests so every request gets a
# fresh connection. Production/dev keep the real pool.
_UNDER_PYTEST = "pytest" in sys.modules

_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def _resolve_db_urls(configured: str) -> tuple[str, dict, str, dict]:
    """Split the configured DATABASE_URL into async/sync URLs + connect_args.

    Managed Postgres (Neon) requires TLS. asyncpg does not understand
    libpq-style ``sslmode`` / ``channel_binding`` query parameters, so they are
    stripped from the async URL and translated into ``connect_args``. psycopg2
    (sync engine, used by the background-task pipeline) does understand
    ``sslmode``, so it is passed through its own ``connect_args``.

    SSL is enabled when the URL carries an explicit ``sslmode`` that is not a
    plaintext mode, or when the host is not local.
    """
    parts = urlsplit(configured)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)  # libpq-only; unused by asyncpg/psycopg2 here

    host = (parts.hostname or "").lower()
    ssl_required = (
        sslmode not in (None, "disable", "allow", "prefer")
        or host not in _LOCAL_HOSTS
    )

    scheme = parts.scheme if "+" in parts.scheme else parts.scheme.replace(
        "postgresql", "postgresql+asyncpg", 1
    )
    async_url = urlunsplit((scheme, parts.netloc, parts.path, "", ""))
    sync_url = async_url.replace("+asyncpg", "+psycopg2")

    async_connect_args = {"ssl": "require"} if ssl_required else {}
    sync_connect_args = {"sslmode": sslmode or "require"} if ssl_required else {}
    return async_url, async_connect_args, sync_url, sync_connect_args


_async_url, _async_connect_args, _sync_url, _sync_connect_args = _resolve_db_urls(
    database_settings.database_url
)

# Create async engine
_async_engine_kwargs: dict = dict(echo=False, connect_args=_async_connect_args)
if _UNDER_PYTEST:
    # TestClient opens/closes a fresh event loop per request; a pooled asyncpg
    # connection bound to a closed loop then raises "Event loop is closed".
    # NullPool = a fresh connection per request. pool_pre_ping still validates
    # each fresh connection, and asyncpg connect/command timeouts turn a slow
    # remote (e.g. Neon free tier) into a clear error instead of a hang.
    _async_engine_kwargs["poolclass"] = NullPool
    _async_engine_kwargs["pool_pre_ping"] = True
    _async_engine_kwargs["connect_args"] = {
        **_async_connect_args,
        "timeout": 30,
        "command_timeout": 60,
    }
else:
    _async_engine_kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)
engine = create_async_engine(_async_url, **_async_engine_kwargs)

# Create async session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Create sync engine for background-task pipeline persistence
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker as sync_sessionmaker

sync_engine = create_engine(
    _sync_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=_sync_connect_args,
)

sync_session_factory = sync_sessionmaker(
    sync_engine,
    class_=Session,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncSession:
    """Get async database session for FastAPI."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


def get_session() -> Session:
    """Get sync database session for the background-task pipeline."""
    return sync_session_factory()


@asynccontextmanager
async def get_async_session_context():
    """Get async database session context manager."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
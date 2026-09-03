from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
import os
import sys

# Add the backend app to the path so we can import models
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.base import Base
# Explicitly import all models to ensure they're registered
from app.models import base

target_metadata = Base.metadata

# Use the same DATABASE_URL the application uses (from the backend .env). We take
# the resolved *sync* URL + per-driver SSL connect_args from app.core.database so
# the secret stays in one place and Neon's required TLS is honoured here too.
try:
    from app.core.database import _sync_url as _APP_SYNC_URL
    from app.core.database import _sync_connect_args as _APP_SYNC_CONNECT_ARGS

    if _APP_SYNC_URL:
        config.set_main_option("sqlalchemy.url", _APP_SYNC_URL)
except Exception:  # pragma: no cover - fall back to alembic.ini value
    _APP_SYNC_CONNECT_ARGS = {}

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=globals().get("_APP_SYNC_CONNECT_ARGS", {}),
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


# Alembic's standard entrypoint dispatch. This runs when the module is loaded by
# the `alembic` CLI (e.g. `alembic upgrade head`), not on a bare import.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
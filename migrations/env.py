"""Alembic environment: runs migrations against DATABASE_URL.

The URL comes from ``backend.settings`` and is never written to the Alembic
config or logs, because it contains a password. A caller that already has a
connection, such as a test, can pass it as ``config.attributes["connection"]``.
"""

from alembic import context
from sqlalchemy import Connection

from backend.settings import Settings
from copilot_core.db import Base, create_db_engine, database_url

config = context.config
target_metadata = Base.metadata

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    from logging.config import fileConfig

    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _url():
    url = Settings().database_url
    if url is None:
        raise SystemExit(
            "DATABASE_URL is not set. Start Postgres and set DATABASE_URL as "
            "described in _docs/AGENTS.md, then run the command again."
        )
    return database_url(url)


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_db_engine(_url())
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

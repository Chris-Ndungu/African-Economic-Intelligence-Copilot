"""Shared fixtures: a real Postgres for the integration tests.

They need ``DATABASE_URL`` and are skipped, with the reason shown, when it is
not set. Each database is created on that server for the test and dropped
afterwards, so the role in ``DATABASE_URL`` needs ``CREATEDB``.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.settings import Settings
from copilot_core.db import create_db_engine, database_url

ROOT = Path(__file__).resolve().parent.parent


HOW_TO_RUN = (
    "DATABASE_URL is not set, so the Postgres integration tests did not run. "
    "Start Postgres and set DATABASE_URL as described in _docs/AGENTS.md, "
    "then run: uv run pytest tests/test_migrations.py"
)


@pytest.fixture(scope="module")
def server_url():
    url = Settings().database_url
    if url is None:
        pytest.skip(HOW_TO_RUN)
    return database_url(url)


@pytest.fixture
def empty_database(server_url):
    """The URL of a new, empty database, dropped after the test."""
    name = f"copilot_test_{uuid.uuid4().hex[:12]}"
    admin = create_db_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        yield server_url.set(database=name)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic(url, *args):
    """Run the Alembic CLI, as a developer would, against ``url``."""
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture
def migrated(empty_database):
    """An engine on an empty database upgraded to head."""
    alembic(empty_database, "upgrade", "head")
    engine = create_db_engine(empty_database)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def migrated_url(server_url):
    """A database upgraded to head, shared by one test module."""
    name = f"copilot_test_{uuid.uuid4().hex[:12]}"
    admin = create_db_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        url = server_url.set(database=name)
        alembic(url, "upgrade", "head")
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def empty_table(migrated_url):
    """The module's database with an empty investigations table."""
    engine = create_db_engine(migrated_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE investigations"))
    yield migrated_url
    engine.dispose()

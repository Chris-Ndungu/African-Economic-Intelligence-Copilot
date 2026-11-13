"""Database settings and the Alembic setup that run without Postgres.

The tests that need a real database are in ``test_migrations.py``.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from backend.settings import Settings
from copilot_core.db import Base, InvestigationRecord, create_db_engine, database_url

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "s3cret-Pa55word"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def test_database_url_is_unset_by_default():
    assert Settings().database_url is None


def test_database_url_is_read_from_database_url(monkeypatch):
    url = f"postgresql://copilot:{PASSWORD}@localhost:5432/copilot"
    monkeypatch.setenv("DATABASE_URL", url)

    settings = Settings()

    assert settings.database_url.get_secret_value() == url
    assert PASSWORD not in repr(settings)
    assert PASSWORD not in str(settings.model_dump())


def test_blank_database_url_counts_as_unset(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "  ")

    assert Settings().database_url is None


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@h/db",
        "postgresql://u:p@h/db",
        "postgresql+psycopg://u:p@h/db",
    ],
)
def test_postgres_urls_use_psycopg_3(url):
    assert database_url(url).drivername == "postgresql+psycopg"


def test_engine_masks_the_password():
    engine = create_db_engine(SecretStr(f"postgresql://copilot:{PASSWORD}@localhost/copilot"))

    assert PASSWORD not in repr(engine)
    assert PASSWORD not in str(engine.url)


@pytest.mark.parametrize(
    "url",
    [
        f"not a url {PASSWORD}",
        f"mysql://copilot:{PASSWORD}@localhost/copilot",
    ],
)
def test_invalid_url_error_does_not_contain_it(url):
    with pytest.raises(ValueError) as error:
        database_url(url)

    assert "DATABASE_URL" in str(error.value)
    assert PASSWORD not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None or error.value.__suppress_context__


def run_alembic(*args, env_overrides, cwd):
    """Run the Alembic CLI from a directory with no .env file."""
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_alembic_without_database_url_says_how_to_set_it(tmp_path):
    result = run_alembic("upgrade", "head", env_overrides={}, cwd=tmp_path)

    assert result.returncode != 0
    assert "DATABASE_URL is not set" in result.stderr


def test_alembic_connection_error_does_not_contain_the_password(tmp_path):
    # Nothing listens on port 1, so the connection is refused.
    url = f"postgresql://copilot:{PASSWORD}@127.0.0.1:1/copilot?connect_timeout=5"

    result = run_alembic("upgrade", "head", env_overrides={"DATABASE_URL": url}, cwd=tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "OperationalError" in output
    assert PASSWORD not in output


def test_alembic_invalid_url_error_does_not_contain_it(tmp_path):
    url = f"not a url {PASSWORD}"

    result = run_alembic("upgrade", "head", env_overrides={"DATABASE_URL": url}, cwd=tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "DATABASE_URL is not a valid database URL" in output
    assert PASSWORD not in output


def test_migrations_have_a_single_head(tmp_path):
    result = run_alembic("heads", env_overrides={}, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0005", "(head)"]


def test_investigations_table_has_the_required_columns():
    table = Base.metadata.tables["investigations"]

    assert table is InvestigationRecord.__table__
    assert set(table.columns.keys()) == {
        "id",
        "question",
        "title",
        "request",
        "result",
        "selections",
        "parameters",
        "findings",
        "chart_config",
        "sources",
        "data_mode",
        "status",
        "error",
        "error_code",
        "error_service",
        "owner",
        "run",
        "created_at",
        "updated_at",
    }
    assert [c.name for c in table.primary_key] == ["id"]
    nullable = {c.name for c in table.columns if c.nullable}
    assert nullable == {
        "question",
        "request",
        "result",
        "chart_config",
        "error",
        "error_code",
        "error_service",
        "run",
    }
    for name in ("created_at", "updated_at"):
        assert table.columns[name].type.timezone is True


def test_core_has_no_web_framework_imports():
    source = (ROOT / "copilot_core" / "db.py").read_text(encoding="utf-8")

    assert "fastapi" not in source
    assert "backend" not in source

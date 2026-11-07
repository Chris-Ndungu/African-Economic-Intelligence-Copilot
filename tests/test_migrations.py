"""Integration tests: the Alembic migrations against a real Postgres.

They need ``DATABASE_URL`` and are skipped, with the reason shown, when it is
not set. Each test run creates its own empty database on that server, so the
role in ``DATABASE_URL`` needs ``CREATEDB``, and drops it afterwards; the
database ``DATABASE_URL`` names is only used to create and drop it.
"""

import os
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.settings import Settings
from copilot_core.db import InvestigationRecord, create_db_engine, database_url
from copilot_core.models import Finding

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


def finding_json():
    return Finding(
        id="f1",
        kind="anomaly",
        metric="inflation_cpi",
        statement="Inflation in Kenya in 2022 was 2.4 standard deviations above its 2018-2021 mean.",
        value=7.66,
        unit="percent",
        period={"start": "2022", "end": "2022", "frequency": "annual"},
        geography={"country_code": "KEN", "country_name": "Kenya"},
        method={
            "name": "z_score",
            "description": "Distance from the baseline mean in standard deviations.",
            "parameters": {"baseline_periods": 4, "threshold": 2.0, "countries": ["KEN"]},
        },
        source={
            "id": "imf_weo",
            "name": "World Economic Outlook",
            "provider": "IMF",
            "url": "https://www.imf.org/en/Publications/WEO",
            "last_updated": "2026-04-15",
        },
        caveats=["Annual averages hide within-year movements."],
        result_ids=["a1"],
    ).model_dump(mode="json")


def new_record(**overrides):
    values = {
        "question": "Why did inflation in Kenya rise in 2022?",
        "selections": {
            "countries": ["KEN"],
            "indicators": ["inflation_cpi"],
            "period": {"start": "2018", "end": "2023"},
        },
        "parameters": {"baseline_periods": 4, "anomaly_method": "z_score", "anomaly_threshold": 2},
        "findings": [finding_json()],
        "chart_config": {"type": "line", "series": ["inflation_cpi:KEN"], "options": {"log": False}},
        "sources": [finding_json()["source"]],
        "data_mode": "demo",
        "status": "succeeded",
    }
    return InvestigationRecord(**{**values, **overrides})


def test_upgrade_insert_read_back_and_downgrade(empty_database):
    alembic(empty_database, "upgrade", "head")
    engine = create_db_engine(empty_database)
    try:
        assert "investigations" in inspect(engine).get_table_names()
        record = new_record()
        expected = {
            column: getattr(record, column)
            for column in ("question", "selections", "parameters", "findings", "chart_config", "sources")
        }
        with Session(engine) as session:
            session.add(record)
            session.commit()
            record_id = record.id

        with Session(engine) as session:
            stored = session.get(InvestigationRecord, record_id)
            for column, value in expected.items():
                assert getattr(stored, column) == value, column
            assert Finding.model_validate(stored.findings[0]).model_dump(mode="json") == finding_json()
            assert stored.status == "succeeded"
            assert stored.error is None
    finally:
        engine.dispose()

    alembic(empty_database, "downgrade", "base")

    engine = create_db_engine(empty_database)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
        with engine.connect() as connection:
            functions = connection.execute(
                text("SELECT proname FROM pg_proc WHERE proname = 'investigations_set_updated_at'")
            ).all()
        assert functions == []
    finally:
        engine.dispose()


def test_models_and_migrations_agree(migrated, empty_database):
    result = alembic(empty_database, "check")

    assert "No new upgrade operations detected" in result.stdout + result.stderr


def test_defaults_for_an_investigation_started_from_selections(migrated):
    with Session(migrated) as session:
        record = InvestigationRecord(selections={"countries": ["KEN", "NGA"]}, data_mode="live")
        session.add(record)
        session.commit()

        assert isinstance(record.id, uuid.UUID)
        assert record.question is None
        assert record.parameters == {}
        assert record.findings == []
        assert record.sources == []
        assert record.chart_config is None
        assert record.status == "pending"
        assert record.error is None


def test_timestamps_are_utc_and_updated_at_changes_on_every_update(migrated):
    with Session(migrated) as session:
        record = new_record(status="running")
        session.add(record)
        session.commit()
        created_at, first_update = record.created_at, record.updated_at

        assert created_at.utcoffset() == timedelta(0)
        assert first_update.utcoffset() == timedelta(0)

        updated = []
        for status in ("failed", "failed"):
            time.sleep(0.01)
            session.execute(
                update(InvestigationRecord)
                .where(InvestigationRecord.id == record.id)
                .values(status=status, error="Gemini timed out")
            )
            session.commit()
            updated.append(
                session.scalar(
                    select(InvestigationRecord.updated_at).where(InvestigationRecord.id == record.id)
                )
            )

        assert first_update < updated[0] < updated[1]
        assert session.get(InvestigationRecord, record.id).created_at == created_at


def test_updated_at_changes_with_raw_sql_too(migrated):
    with migrated.begin() as connection:
        record_id = connection.execute(
            text(
                "INSERT INTO investigations (selections, data_mode) "
                "VALUES ('{}', 'live') RETURNING id"
            )
        ).scalar_one()
    with migrated.begin() as connection:
        before = connection.execute(
            text("SELECT updated_at FROM investigations WHERE id = :id"), {"id": record_id}
        ).scalar_one()
        connection.execute(
            text("UPDATE investigations SET status = 'running' WHERE id = :id"), {"id": record_id}
        )
        after = connection.execute(
            text("SELECT updated_at FROM investigations WHERE id = :id"), {"id": record_id}
        ).scalar_one()

    assert after > before


INVALID_ROWS = [
    ("data_mode", {"data_mode": "sample", "status": "pending"}),
    ("data_mode", {"data_mode": "DEMO", "status": "pending"}),
    ("data_mode", {"data_mode": None, "status": "pending"}),
    ("status", {"data_mode": "demo", "status": "done"}),
    ("status", {"data_mode": "demo", "status": ""}),
    ("status", {"data_mode": "demo", "status": None}),
]


@pytest.mark.parametrize("column, row", INVALID_ROWS)
def test_database_rejects_invalid_data_mode_and_status(migrated, column, row):
    # Raw SQL, so only the database can reject the value. NULL fails the
    # NOT NULL constraint rather than the check.
    expected = f"ck_investigations_{column}" if row[column] is not None else "not-null"
    with pytest.raises(IntegrityError, match=expected):
        with migrated.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO investigations (selections, data_mode, status) "
                    "VALUES ('{}', :data_mode, :status)"
                ),
                row,
            )


def test_newest_first_listing_uses_the_index(migrated):
    with migrated.begin() as connection:
        for _ in range(3):
            connection.execute(text("INSERT INTO investigations (selections, data_mode) VALUES ('{}', 'demo')"))
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            connection.execute(
                text("EXPLAIN SELECT id FROM investigations ORDER BY created_at DESC, id DESC LIMIT 20")
            ).scalars()
        )

    assert "Scan using ix_investigations_created_at_id" in plan
    assert "Sort" not in plan

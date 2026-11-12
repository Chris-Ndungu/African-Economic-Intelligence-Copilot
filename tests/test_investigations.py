"""Investigation persistence: repository and endpoints against a real Postgres (#19).

Every test starts from an empty ``investigations`` table (the ``empty_table``
fixture in conftest.py), so the tests do not depend on order. They are
skipped with the reason shown when ``DATABASE_URL`` is not set; the 503 tests
need no database.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.main import create_app
from backend.settings import Settings
from copilot_core.data import DuckDBDataService
from copilot_core.db import create_db_engine
from copilot_core.investigation import run_trend_investigation
from copilot_core.repository import (
    InvalidStatusTransitionError,
    InvestigationNotFoundError,
    InvestigationRepository,
)
from copilot_core.schemas import InvestigationCreate, InvestigationUpdate

TINY = Path(__file__).resolve().parent / "fixtures" / "tiny"


def result_json():
    data = DuckDBDataService(TINY)
    return run_trend_investigation(data, "KEN", "PCPIPCH", "2018", "2023").result.model_dump(
        mode="json"
    )


RESULT = result_json()


def body(title="Kenya inflation"):
    return {"title": title, "request": RESULT["request"], "result": RESULT}


@pytest.fixture
def repository(empty_table):
    engine = create_db_engine(empty_table)
    yield InvestigationRepository(engine)
    engine.dispose()


@pytest.fixture
def client(empty_table):
    url = SecretStr(empty_table.render_as_string(hide_password=False))
    settings = Settings(database_url=url, data_dir=TINY)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


# --- Repository ---------------------------------------------------------------


def test_create_get_and_validate_on_the_way_out(repository):
    saved = repository.create(InvestigationCreate.model_validate(body()), data_mode="demo")
    assert saved.status == "pending"
    fetched = repository.get(saved.id)
    assert fetched == saved
    assert fetched.result.findings[0].kind == "trend"
    assert fetched.result.sources[0].name == "IMF DataMapper"


def test_findings_sources_and_chart_config_are_stored(repository, empty_table):
    saved = repository.create(InvestigationCreate.model_validate(body()), data_mode="demo")
    engine = create_db_engine(empty_table)
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT findings, sources, chart_config FROM investigations WHERE id = %s",
            (saved.id,),
        ).one()
    engine.dispose()
    assert row.findings[0]["id"] == RESULT["findings"][0]["id"]
    assert row.sources == RESULT["sources"]
    assert row.chart_config == {"type": "line", "series_ids": [RESULT["series"][0]["id"]]}


def test_update_moves_updated_at_and_follows_status_rules(repository):
    saved = repository.create(InvestigationCreate.model_validate(body()), data_mode="demo")
    running = repository.update(saved.id, InvestigationUpdate(status="running"))
    assert running.updated_at > saved.updated_at
    done = repository.update(saved.id, InvestigationUpdate(status="succeeded"))
    assert done.status == "succeeded"
    with pytest.raises(InvalidStatusTransitionError, match="'succeeded' to 'running'"):
        repository.update(saved.id, InvestigationUpdate(status="running"))
    other = repository.create(InvestigationCreate.model_validate(body()), data_mode="demo")
    assert repository.update(other.id, InvestigationUpdate(status="failed")).status == "failed"


def test_title_only_update_still_moves_updated_at(repository):
    saved = repository.create(InvestigationCreate.model_validate(body()), data_mode="demo")
    renamed = repository.update(saved.id, InvestigationUpdate(title="Renamed"))
    assert renamed.title == "Renamed" and renamed.updated_at > saved.updated_at


def test_concurrent_updates_both_finish_and_the_later_one_wins(repository):
    saved = repository.create(InvestigationCreate.model_validate(body()), data_mode="demo")

    def rename(title):
        return repository.update(saved.id, InvestigationUpdate(title=title))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rename, ["first", "second"]))
    later = max(results, key=lambda r: r.updated_at)
    assert repository.get(saved.id).title == later.title


def test_list_is_newest_first_and_paginated(repository):
    ids = [
        repository.create(InvestigationCreate.model_validate(body(f"n{i}")), "demo").id
        for i in range(5)
    ]
    first = repository.list(limit=2)
    assert [i.id for i in first.items] == ids[::-1][:2]
    second = repository.list(limit=2, cursor=first.next_cursor)
    third = repository.list(limit=2, cursor=second.next_cursor)
    assert [i.id for i in second.items + third.items] == ids[::-1][2:]
    assert third.next_cursor is None
    with pytest.raises(ValueError, match="between 1 and 100"):
        repository.list(limit=101)


def test_missing_investigation_raises_not_found(repository):
    with pytest.raises(InvestigationNotFoundError):
        repository.get(uuid.uuid4())


# --- API ----------------------------------------------------------------------


def test_create_fetch_update_and_list_through_the_api(client):
    created = client.post("/api/investigations", json=body())
    assert created.status_code == 201
    saved = created.json()
    assert created.headers["location"] == f"/api/investigations/{saved['id']}"
    assert saved["status"] == "succeeded" and saved["data_mode"] == "demo"

    fetched = client.get(f"/api/investigations/{saved['id']}")
    assert fetched.status_code == 200 and fetched.json() == saved

    updated = client.patch(f"/api/investigations/{saved['id']}", json={"title": "New title"})
    assert updated.status_code == 200 and updated.json()["title"] == "New title"

    page = client.get("/api/investigations").json()
    assert page["data_mode"] == "demo" and page["limit"] == 20
    assert [i["id"] for i in page["items"]] == [saved["id"]]
    assert page["items"][0]["countries"] == ["KEN"]


def test_empty_database_lists_an_empty_page(client):
    assert client.get("/api/investigations").json() == {
        "data_mode": "demo",
        "items": [],
        "limit": 20,
        "next_cursor": None,
    }


def test_page_size_limits_come_from_the_contract(client):
    assert client.get("/api/investigations", params={"limit": 101}).status_code == 422
    assert client.get("/api/investigations", params={"limit": 0}).status_code == 422
    assert client.get("/api/investigations", params={"cursor": "nonsense"}).status_code == 422


@pytest.mark.parametrize("method", ["get", "patch"])
def test_unknown_id_is_404_with_the_error_schema(client, method):
    missing = uuid.uuid4()
    response = client.request(method.upper(), f"/api/investigations/{missing}", json={"title": "x"})
    assert response.status_code == 404
    assert response.json() == {
        "code": "not_found",
        "message": f"Investigation {missing} was not found.",
        "service": None,
        "details": [],
    }


def test_invalid_uuid_is_422(client):
    response = client.get("/api/investigations/not-a-uuid")
    assert response.status_code == 422
    assert response.json()["details"][0]["field"] == "investigation_id"


def test_invalid_body_is_422_naming_the_field(client):
    bad = body()
    bad["result"] = {**RESULT, "data_mode": "staging"}
    response = client.post("/api/investigations", json=bad)
    assert response.status_code == 422
    assert "result.data_mode" in [d["field"] for d in response.json()["details"]]


def test_invalid_status_change_is_422(client):
    saved = client.post("/api/investigations", json=body()).json()
    response = client.patch(f"/api/investigations/{saved['id']}", json={"status": "running"})
    assert response.status_code == 422
    assert "succeeded" in response.json()["message"]


# --- Postgres unavailable (no database needed) ---------------------------------


@pytest.fixture
def unreachable_client():
    # Nothing listens on port 1, so every connection is refused.
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://copilot:copilot@127.0.0.1:1/copilot"),
        data_dir=TINY,
    )
    return TestClient(create_app(settings))


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/investigations"),
        ("POST", "/api/investigations"),
        ("GET", f"/api/investigations/{uuid.UUID(int=1)}"),
        ("PATCH", f"/api/investigations/{uuid.UUID(int=1)}"),
    ],
)
def test_unreachable_postgres_is_503_and_the_api_keeps_running(unreachable_client, method, path):
    response = unreachable_client.request(
        method, path, json=body() if method == "POST" else {"title": "x"}
    )
    assert response.status_code == 503
    assert response.json()["service"] == "database"
    assert response.json()["code"] == "service_unavailable"
    assert unreachable_client.get("/health").json() == {"status": "ok"}


def test_no_database_configured_is_503():
    client = TestClient(create_app(Settings(database_url=None, data_dir=TINY)))
    assert client.get("/api/investigations").status_code == 503

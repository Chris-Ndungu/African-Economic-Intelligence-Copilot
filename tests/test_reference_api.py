"""Integration tests: the reference endpoints on data/demo/ (#15)."""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(Settings()))


@pytest.fixture
def broken_client(tmp_path):
    return TestClient(create_app(Settings(data_dir=tmp_path)), raise_server_exceptions=False)


def test_countries(client):
    response = client.get("/api/countries")
    assert response.status_code == 200
    body = response.json()
    assert body["data_mode"] == "demo"
    assert len(body["countries"]) == 54
    kenya = next(c for c in body["countries"] if c["code"] == "KEN")
    assert kenya == {"code": "KEN", "name": "Kenya", "region": "Eastern Africa"}


def test_indicators(client):
    body = client.get("/api/indicators").json()
    assert body["data_mode"] == "demo"
    assert len(body["indicators"]) == 14
    inflation = next(i for i in body["indicators"] if i["code"] == "PCPIPCH")
    assert inflation["frequency"] == "annual"
    assert inflation["category"] == "inflation"
    assert inflation["source"]["provider"] == "IMF DataMapper"


def test_coverage_filters(client):
    response = client.get("/api/coverage", params={"country": ["KEN"], "indicator": ["PCPIPCH"]})
    assert response.status_code == 200
    (entry,) = response.json()["entries"]
    assert entry["country_code"] == "KEN"
    assert entry["first_period"] <= entry["last_period"]
    assert entry["missing_count"] >= 0


def test_coverage_without_filters_returns_every_pair(client):
    body = client.get("/api/coverage").json()
    assert body["data_mode"] == "demo"
    assert len(body["entries"]) > 500


def test_coverage_unknown_country_is_422_naming_it(client):
    response = client.get("/api/coverage", params={"country": ["XXX"]})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert "XXX" in body["message"]
    assert body["details"][0]["field"] == "countries"


@pytest.mark.parametrize("path", ["/api/countries", "/api/indicators", "/api/coverage"])
def test_unreadable_data_is_503_with_the_error_schema(broken_client, path):
    response = broken_client.get(path)
    assert response.status_code == 503
    assert response.json() == {
        "code": "service_unavailable",
        "message": "The data service is unavailable.",
        "service": "data_service",
        "details": [],
    }


def test_routes_contain_no_sql():
    """Routes call the DataService and the repository; SQL stays in copilot_core."""
    for path in (ROOT / "backend").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        modules = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                modules |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        assert not modules & {"duckdb", "psycopg"}, path.name
        for keyword in ("SELECT ", "INSERT INTO", "DELETE FROM", "CREATE VIEW"):
            assert keyword not in source.upper(), f"{path.name} contains {keyword.strip()}"

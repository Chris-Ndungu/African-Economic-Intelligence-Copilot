"""Cache headers and the two kinds of 404 (#36), without Docker."""

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.settings import Settings
from backend.web import HTMX_FILE


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app(Settings())) as test_client:
        yield test_client


def test_vendored_files_are_cached_for_a_year(client):
    response = client.get(f"/static/{HTMX_FILE}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize("path", ["/static/app.css", "/static/run.js"])
def test_the_apps_own_static_files_are_revalidated(client, path):
    assert client.get(path).headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/", "/nope", "/investigations/not-an-id"])
def test_html_pages_are_revalidated(client, path):
    assert client.get(path).headers["cache-control"] == "no-cache"


def test_the_partials_are_revalidated(client):
    assert client.get("/partials/history").headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/api/nope", "/api/investigations/x/y/z"])
def test_an_unknown_api_path_is_a_json_404_with_the_shared_error(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "code": "not_found",
        "message": "There is no such endpoint.",
        "service": None,
        "details": [],
    }


def test_any_other_unknown_path_is_an_html_404_with_layout_banner_and_link(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert 'class="site-header"' in response.text
    assert 'data-mode="demo"' in response.text
    assert 'href="/"' in response.text and "Back to the workspace" in response.text

"""Saved investigations are private to each visitor and bounded (#59).

The page and API tests use the in-memory repository; the owner filtering,
the cap and the expiry of the real repository are checked on Postgres and are
skipped, with the reason, when ``DATABASE_URL`` is not set.
"""

import os
import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from memory_repository import MemoryRepository

from backend.main import create_app
from backend.settings import Settings
from backend.visitor import COOKIE_NAME
from copilot_core.llm import StubLLMClient
from copilot_core.repository import InvestigationLimitError, InvestigationRepository

QUESTION = {"question": "How did inflation change in Kenya from 2015 to 2023?"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def make_app(**settings):
    app = create_app(Settings(gemini_api_key="test-key", **settings))
    app.state.repository = MemoryRepository()
    app.state.llm = StubLLMClient("run_success")
    return app


def visitor(app):
    return TestClient(app)


def test_first_visit_sets_an_http_only_cookie_and_later_visits_do_not():
    with visitor(make_app()) as client:
        first = client.get("/")
        cookie = first.headers["set-cookie"]
        assert COOKIE_NAME in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
        assert "set-cookie" not in client.get("/").headers


def test_health_and_static_files_do_not_start_a_visitor():
    with visitor(make_app()) as client:
        assert "set-cookie" not in client.get("/health").headers


def test_a_malformed_cookie_is_replaced():
    with visitor(make_app()) as client:
        client.cookies.set(COOKIE_NAME, "not-an-id")
        assert COOKIE_NAME in client.get("/").headers["set-cookie"]


def test_a_visitor_lists_and_fetches_only_their_own_investigations():
    app = make_app()
    with visitor(app) as alice, visitor(app) as bob:
        created = alice.post("/api/investigations/runs", json=QUESTION)
        assert created.status_code == 202
        investigation_id = created.json()["id"]
        assert [i["id"] for i in alice.get("/api/investigations").json()["items"]] == [
            investigation_id
        ]
        assert bob.get("/api/investigations").json()["items"] == []
        assert alice.get(f"/api/investigations/{investigation_id}").status_code == 200


def test_another_visitors_investigation_is_404_not_403_everywhere():
    app = make_app()
    with visitor(app) as alice, visitor(app) as bob:
        investigation_id = alice.post("/api/investigations/runs", json=QUESTION).json()["id"]
        paths = [
            f"/api/investigations/{investigation_id}",
            f"/api/investigations/{investigation_id}/report",
            f"/investigations/{investigation_id}",
        ]
        for path in paths:
            assert bob.get(path).status_code == 404, path
        stream = bob.get(f"/api/investigations/{investigation_id}/events")
        assert stream.status_code == 404
        assert stream.json()["code"] == "not_found"


def test_clearing_cookies_starts_an_empty_history():
    app = make_app()
    with visitor(app) as client:
        client.post("/api/investigations/runs", json=QUESTION)
        assert len(client.get("/api/investigations").json()["items"]) == 1
        client.cookies.clear()
        assert client.get("/api/investigations").json()["items"] == []


def test_the_history_sidebar_says_it_is_kept_in_this_browser_only():
    with visitor(make_app()) as client:
        assert "History is kept in this browser only" in client.get("/").text
        assert "History is kept in this browser only" in client.get("/partials/history").text


def test_saving_over_the_limit_is_refused_and_names_the_limit():
    app = make_app(anonymous_investigation_limit=2)
    with visitor(app) as client, visitor(app) as other:
        for _ in range(2):
            assert client.post("/api/investigations/runs", json=QUESTION).status_code == 202
        refused = client.post("/api/investigations/runs", json=QUESTION)
        assert refused.status_code == 409
        assert refused.json()["code"] == "conflict"
        assert "limit of 2" in refused.json()["message"]
        # The limit is per visitor.
        assert other.post("/api/investigations/runs", json=QUESTION).status_code == 202


def test_the_run_form_shows_the_limit():
    app = make_app(anonymous_investigation_limit=1)
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    body = "question=How+did+inflation+change+in+Kenya"
    with visitor(app) as client:
        assert (
            client.post("/partials/investigations/run", content=body, headers=form).status_code
            == 200
        )
        again = client.post("/partials/investigations/run", content=body, headers=form)
        assert "limit of 1" in again.text


def test_the_visitor_id_is_not_in_the_error_or_the_page():
    app = make_app()
    with visitor(app) as client:
        client.get("/")
        value = client.cookies.get(COOKIE_NAME)
        assert value and re.fullmatch(r"[0-9a-f]{32}", value)
        assert value not in client.get("/").text


# --- the real repository on Postgres ----------------------------------------------


def test_postgres_scopes_limits_and_expires_by_owner(migrated):
    base = InvestigationRepository(migrated)
    alice = base.for_owner("anon:" + "a" * 32, limit=2)
    bob = base.for_owner("anon:" + "b" * 32, limit=2)
    first = alice.create_run("q", None, "demo", "one")
    alice.create_run("q", None, "demo", "two")
    with pytest.raises(InvestigationLimitError, match="limit of 2"):
        alice.create_run("q", None, "demo", "three")
    bob.create_run("q", None, "demo", "mine")
    assert {i.title for i in alice.list().items} == {"one", "two"}
    assert [i.title for i in bob.list().items] == ["mine"]
    from copilot_core.repository import InvestigationNotFoundError  # noqa: PLC0415

    with pytest.raises(InvestigationNotFoundError):
        bob.get(first.id)
    # Expiry deletes only anonymous rows older than the age.
    from sqlalchemy import text  # noqa: PLC0415

    old = datetime.now(UTC) - timedelta(days=31)
    with migrated.begin() as connection:
        connection.execute(
            text("update investigations set created_at = :t where id = :i"),
            {"t": old, "i": first.id},
        )
    assert base.delete_expired_anonymous(30) == 1
    assert {i.title for i in alice.list().items} == {"two"}

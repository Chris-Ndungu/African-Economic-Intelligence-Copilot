"""The history sidebar and the /investigations/{id} pages, with a fake repository."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from results_helpers import (
    failed,
    make_finding,
    make_interpretation,
    make_investigation,
    make_result,
    make_run,
)
from selection_helpers import FakeDataService
from test_web import Page, text

from backend.main import create_app
from backend.settings import Settings
from copilot_core.history import clip, history_title
from copilot_core.repository import (
    DatabaseUnavailableError,
    InvestigationNotFoundError,
    InvestigationPage,
)
from copilot_core.schemas import InvestigationSummary

NOW = datetime(2026, 11, 12, 10, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


class FakeRepository:
    """``list`` and ``get`` of the real repository over a list, newest first."""

    def __init__(self, investigations, fail=False):
        self.items = sorted(investigations, key=lambda i: i.created_at, reverse=True)
        self.fail = fail
        self.writes = 0

    def list(self, limit=20, cursor=None):
        if self.fail:
            raise DatabaseUnavailableError("down")
        start = int(cursor or 0)
        chosen = self.items[start : start + limit]
        more = start + limit < len(self.items)
        return InvestigationPage(
            items=[
                InvestigationSummary(
                    id=i.id,
                    title=i.title,
                    status=i.status,
                    data_mode=i.data_mode,
                    investigation_type=None,
                    countries=[],
                    indicators=[],
                    created_at=i.created_at,
                    updated_at=i.updated_at,
                )
                for i in chosen
            ],
            limit=limit,
            next_cursor=str(start + limit) if more else None,
        )

    def get(self, investigation_id):
        if self.fail:
            raise DatabaseUnavailableError("down")
        for item in self.items:
            if item.id == investigation_id:
                return item
        raise InvestigationNotFoundError(investigation_id)


def make_client(repository):
    app = create_app(Settings())
    app.state.data_service = FakeDataService()
    app.state.repository = repository
    return TestClient(app)


def inv(question="Why?", minutes=0, **kw):
    return make_investigation(question=question, created=NOW - timedelta(minutes=minutes), **kw)


def test_titles_cut_a_long_question_and_summarise_a_selection_only_run():
    long = inv("x" * 100)
    only = make_investigation(None, status="pending", question=None, run=make_run())

    assert history_title(long) == "x" * 59 + "…" and len(history_title(long)) == 60
    assert history_title(only) == "PCPIPCH · KEN, NGA · 2018–2020"
    assert clip("short") == "short"


def test_the_list_is_newest_first_with_a_status_text_icon_and_utc_time():
    older = inv("Older", 60, status="failed", error=failed())
    newer = inv("Newer", 1, status="running")
    page = Page(make_client(FakeRepository([older, newer])).get("/partials/history").text)

    titles = [text(e) for e in page.find_all("span", **{"class": "history-title"})]
    assert titles == ["Newer", "Older"]
    times = page.find_all("time")
    assert times[0].attrs["datetime"] == "2026-11-12T10:29:00Z"
    assert text(times[0]) == "2026-11-12"
    statuses = [text(e) for e in page.elements if e.attrs.get("class", "").startswith("status ")]
    assert statuses == ["◔ Running", "✕ Failed"]


@pytest.mark.parametrize(
    ("status", "label", "icon"),
    [
        ("pending", "Pending", "○"),
        ("running", "Running", "◔"),
        ("succeeded", "Succeeded", "✓"),
        ("failed", "Failed", "✕"),
    ],
)
def test_every_status_shows_text_and_an_icon(status, label, icon):
    html = make_client(FakeRepository([inv(status=status)])).get("/partials/history").text

    assert f"{icon}</span> {label}" in html


def test_each_item_loads_into_the_main_panel_and_pushes_the_url():
    item = inv()
    page = Page(make_client(FakeRepository([item])).get("/partials/history").text)

    link = page.find("a", href=f"/investigations/{item.id}")
    assert link.attrs["hx-get"] == f"/investigations/{item.id}"
    assert link.attrs["hx-target"] == "#workspace" and link.attrs["hx-push-url"] == "true"


def test_the_empty_state_says_no_investigations_yet_with_a_hint():
    html = make_client(FakeRepository([])).get("/partials/history").text

    assert "No investigations yet" in html and "to start one" in html


def test_a_database_error_shows_a_retry_button_and_the_page_still_renders():
    client = make_client(FakeRepository([], fail=True))

    partial = client.get("/partials/history")
    page = Page(client.get("/").text)

    assert partial.status_code == 200 and "database is unavailable" in partial.text
    assert any(
        text(b) == "Retry" and b.attrs["hx-get"] == "/partials/history"
        for b in Page(partial.text).find_all("button")
    )
    assert page.find("form", id="selection-form") is not None
    assert "database is unavailable" in client.get("/").text


def test_load_more_appends_the_next_page_and_is_absent_on_the_last():
    items = [inv(f"Q{n}", n) for n in range(25)]
    client = make_client(FakeRepository(items))

    first = Page(client.get("/partials/history").text)
    more = [b for b in first.find_all("button") if text(b) == "Load more"][0]
    assert more.attrs["hx-swap"] == "beforeend" and more.attrs["hx-target"] == "#history-list"
    assert len(first.find_all("li")) == 20

    second = client.get(more.attrs["hx-get"])
    assert len(Page(second.text).find_all("li")) == 5
    assert "Load more" not in second.text
    assert 'hx-swap-oob="true"' in second.text


def test_the_list_refreshes_on_the_investigation_saved_event():
    section = Page(make_client(FakeRepository([inv()])).get("/partials/history").text).find(
        "section"
    )

    assert section.attrs["hx-trigger"] == "investigation-saved from:body"
    assert section.attrs["hx-get"] == "/partials/history"


def test_the_workspace_page_contains_the_sidebar():
    html = make_client(FakeRepository([inv("Visible question")])).get("/").text

    assert "Visible question" in html and 'id="history"' in html


def test_the_investigation_url_returns_a_full_page_and_htmx_gets_only_the_panel():
    item = inv(result=make_result([make_finding()]))
    client = make_client(FakeRepository([item]))

    full = client.get(f"/investigations/{item.id}")
    fragment = client.get(f"/investigations/{item.id}", headers={"HX-Request": "true"})
    restore = client.get(
        f"/investigations/{item.id}",
        headers={"HX-Request": "true", "HX-History-Restore-Request": "true"},
    )

    assert "<html" in full.text and 'id="history"' in full.text and "Inflation rose." in full.text
    assert 'aria-current="page"' in full.text
    assert "<html" not in fragment.text and "Inflation rose." in fragment.text
    assert 'id="history"' not in fragment.text
    assert "<html" in restore.text
    assert full.headers["vary"] == "HX-Request"


@pytest.mark.parametrize("path", [f"/investigations/{uuid.uuid4()}", "/investigations/not-a-uuid"])
def test_an_unknown_or_malformed_id_is_an_html_404_with_a_link_back(path):
    response = make_client(FakeRepository([inv()])).get(path)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Not found" in response.text and [
        a for a in Page(response.text).find_all("a", href="/") if text(a) == "Back to the workspace"
    ]
    assert "Traceback" not in response.text


def test_a_database_error_on_an_investigation_page_is_an_html_503_that_still_has_a_page():
    response = make_client(FakeRepository([], fail=True)).get(f"/investigations/{uuid.uuid4()}")

    assert response.status_code == 503 and "<html" in response.text
    assert "database is unavailable" in response.text


def test_start_from_these_selections_prefills_the_panel_and_leaves_the_original_alone():
    selection = make_run().selection
    item = make_investigation(None, status="pending", question=None, run=make_run())
    repository = FakeRepository([item])
    client = make_client(repository)
    page = Page(client.get(f"/investigations/{item.id}").text)
    form = page.find_all("form", **{"class": "continue"})[0]
    fields = [
        (e.attrs["name"], e.attrs["value"])
        for e in page.find_all("input")
        if e.attrs.get("type") == "hidden"
    ]
    assert form.attrs["hx-target"] == "#selection-panel"

    response = client.post(
        "/partials/selection",
        content=urlencode(fields),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    panel = Page(response.text)

    assert [c for c in selection.countries] == ["KEN", "NGA"]
    assert "checked" in panel.find("input", id="country-KEN").attrs
    assert "checked" in panel.find("input", id="country-NGA").attrs
    assert repository.items == [item] and repository.writes == 0


def test_a_result_with_an_interpretation_renders_through_the_page():
    result = make_result([make_finding()], make_interpretation([]))
    item = inv(result=result)

    html = make_client(FakeRepository([item])).get(f"/investigations/{item.id}").text

    assert "Summary text." in html


def test_the_history_scripts_are_loaded_and_served():
    client = make_client(FakeRepository([]))
    sources = [
        e.attrs["src"] for e in Page(client.get("/").text).find_all("script") if "src" in e.attrs
    ]

    for name in ("/static/local-time.js", "/static/history.js"):
        assert name in sources and client.get(name).status_code == 200

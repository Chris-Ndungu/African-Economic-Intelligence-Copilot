"""The data-mode banner, the error messages and the unavailable states (#31)."""

import json
import os
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from memory_repository import MemoryRepository
from results_helpers import make_interpretation, make_investigation, make_result
from test_web import Page, text

from backend import web
from backend.main import create_app
from backend.settings import Settings
from copilot_core.error_messages import (
    ERROR_MESSAGES,
    RUN_CODES,
    UI_CODES,
    error_message,
    message_table,
    unsupported_message,
)
from copilot_core.meta import banner_text, get_meta, read_snapshot_date
from copilot_core.schemas import InvestigationError, Meta


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def make_client(repository=None, key="test-key", **settings):
    app = create_app(Settings(gemini_api_key=key, **settings))
    app.state.repository = repository or MemoryRepository()
    return TestClient(app)


def stored(repository, investigation):
    repository.items[investigation.id] = investigation
    return investigation


# --- The meta function and the API ---------------------------------------------------


def test_the_demo_snapshot_date_comes_from_the_demo_readme():
    assert read_snapshot_date(Settings().data_dir) == date(2026, 11, 11)


def test_meta_reports_demo_with_its_date_and_gemini_state():
    meta = get_meta(Settings().data_dir, gemini_configured=False)

    assert meta == Meta(data_mode="demo", snapshot_date=date(2026, 11, 11), gemini_configured=False)


def test_a_setting_overrides_the_readme_date(tmp_path):
    meta = get_meta(tmp_path, True, snapshot_date=date(2026, 1, 2))

    assert meta.data_mode == "demo" and meta.snapshot_date == date(2026, 1, 2)


def test_meta_is_unknown_when_the_snapshot_date_cannot_be_read(tmp_path):
    assert get_meta(tmp_path, True).data_mode == "unknown"
    (tmp_path / "README.md").write_text("Snapshot date: someday", encoding="utf-8")
    assert get_meta(tmp_path, True).data_mode == "unknown"


def test_meta_in_live_mode_has_no_snapshot_date(tmp_path):
    meta = get_meta(tmp_path, True, data_mode="live")

    assert meta.data_mode == "live" and meta.snapshot_date is None


def test_api_meta_in_demo_mode():
    response = make_client().get("/api/meta")

    assert response.status_code == 200
    assert response.json() == {
        "data_mode": "demo",
        "snapshot_date": "2026-11-11",
        "gemini_configured": True,
    }


def test_api_meta_says_when_gemini_is_not_configured():
    assert make_client(key=None).get("/api/meta").json()["gemini_configured"] is False


# --- The banner ------------------------------------------------------------------------


def banner(html):
    return Page(html).find("div", **{"class": "mode-banner mode-demo"})


def test_the_workspace_has_the_demo_banner_with_its_date():
    html = make_client().get("/").text
    box = banner(html)

    assert text(box) == "Sample data from 2026-11-11. Not live economic data."
    assert box.attrs["data-mode"] == "demo"
    assert "dismiss" not in html.lower() and "<button" not in html.split("</header>")[0]


def test_the_not_found_page_has_the_banner_too():
    response = make_client().get(f"/investigations/{uuid.uuid4()}")

    assert response.status_code == 404
    assert "Sample data from 2026-11-11" in response.text


def test_the_unavailable_page_has_the_banner_too():
    client = make_client()
    client.app.state.repository = None
    response = client.get(f"/investigations/{uuid.uuid4()}")

    assert response.status_code == 503
    assert "Sample data from 2026-11-11" in response.text


def test_the_live_banner_says_live_in_words_and_has_its_own_style(monkeypatch):
    live = Meta(data_mode="live", snapshot_date=None, gemini_configured=True)
    monkeypatch.setitem(web.templates.env.globals, "page_meta", lambda request: live)
    html = make_client().get("/").text
    box = Page(html).find("div", **{"class": "mode-banner mode-live"})

    assert text(box) == "Live data"
    assert "Sample data" not in html


def test_an_unreadable_snapshot_date_makes_the_page_say_the_mode_is_unknown(tmp_path):
    html = make_client(data_dir=tmp_path).get("/").text
    box = Page(html).find("div", **{"class": "mode-banner mode-unknown"})

    assert "Data mode unknown" in text(box)
    assert "Live data" not in html


def test_banner_wording_states_the_mode_in_text():
    demo = Meta(data_mode="demo", snapshot_date=date(2026, 11, 11), gemini_configured=True)

    assert banner_text(demo) == "Sample data from 2026-11-11. Not live economic data."


# --- The data mode of a saved investigation ----------------------------------------------


def test_the_results_and_history_show_the_mode_the_run_used_not_the_apps():
    repository = MemoryRepository()
    old = make_investigation(make_result())
    stored(repository, old.model_copy(update={"data_mode": "live"}))
    client = make_client(repository)

    results = client.get(f"/investigations/{old.id}").text
    history = client.get("/partials/history").text
    assert "Sample data from 2026-11-11" in results  # the app is in demo mode
    assert 'class="data-mode data-mode-live">Live data' in results
    assert 'class="data-mode data-mode-live">Live data' in history


# --- The error messages -----------------------------------------------------------------


def test_every_error_code_a_run_can_produce_has_a_message():
    for code in RUN_CODES:
        entry = ERROR_MESSAGES[code]
        assert entry.title and entry.action, code
    assert set(UI_CODES) <= ERROR_MESSAGES.keys()
    assert {"connection_lost", "client_disconnected", "not_started"} <= ERROR_MESSAGES.keys()


def test_an_unknown_code_gets_a_generic_message_naming_the_code():
    entry = error_message("weird_code")

    assert "weird_code" in entry.text and "Something went wrong" in entry.text
    assert "none" in error_message(None).text


@pytest.mark.parametrize("code", RUN_CODES)
def test_the_results_view_shows_each_codes_own_message(code):
    repository = MemoryRepository()
    failed = make_investigation(
        None,
        status="failed",
        error=InvestigationError(code=code, message="raw backend text", service=None),
    )
    stored(repository, failed)
    html = make_client(repository).get(f"/investigations/{failed.id}").text

    assert error_message(code).text in html.replace("&#39;", "'")
    assert "raw backend text" not in html
    assert "Observed facts" not in html


def test_each_message_says_what_happened_and_what_to_do():
    for code in (
        "data_unavailable",
        "gemini_not_configured",
        "gemini_unavailable",
        "gemini_timeout",
    ):
        assert error_message(code).title != error_message(code).action
    assert error_message("client_disconnected").title == "Cancelled"
    assert "fewer countries" in error_message("step_limit_reached").action


def test_an_unsupported_question_shows_the_reason():
    repository = MemoryRepository()
    result = make_result(
        [], make_interpretation([], summary="", unsupported="Only African countries are covered.")
    )
    stored(repository, make_investigation(result))
    investigation_id = next(iter(repository.items))
    html = make_client(repository).get(f"/investigations/{investigation_id}").text

    assert "This question is not supported: Only African countries are covered." in html
    assert unsupported_message(None) == ERROR_MESSAGES["unsupported_question"].text


def test_the_progress_partial_uses_the_same_wording_and_a_generic_message_for_unknown_codes():
    template = web.templates.get_template("partials/run_outcome.html")
    known = template.render(kind="failed", investigation_id="x", code="gemini_timeout")
    unknown = template.render(kind="failed", investigation_id="x", code="weird_code")

    assert error_message("gemini_timeout").text in known
    assert "weird_code" in unknown and "Something went wrong" in unknown


def test_the_history_shows_the_failure_title_for_a_failed_run():
    repository = MemoryRepository()
    stored(
        repository,
        make_investigation(
            None,
            status="failed",
            error=InvestigationError(code="gemini_unavailable", message="x", service="gemini"),
        ),
    )
    html = make_client(repository).get("/partials/history").text

    assert "Gemini is unavailable" in html


def test_the_page_carries_the_messages_once_as_json_for_scripts():
    page = Page(make_client().get("/").text)
    tags = [s for s in page.find_all("script") if s.attrs.get("id") == "error-messages"]

    assert len(tags) == 1 and tags[0].attrs["type"] == "application/json"
    table = json.loads(text(tags[0]))
    assert table == message_table()
    assert table["connection_lost"]["text"] and table["client_disconnected"]["title"] == "Cancelled"


# --- Gemini not configured -------------------------------------------------------------------


def test_the_run_button_is_disabled_with_the_message_when_gemini_is_not_configured():
    html = make_client(key=None).get("/").text
    page = Page(html)
    button = page.find("button", id="run-button")

    assert "disabled" in button.attrs
    assert button.attrs["data-unavailable"] == "gemini_not_configured"
    assert error_message("gemini_not_configured").text in text(
        page.find("p", **{"data-error": "gemini_not_configured"})
    )


def test_the_run_button_has_no_unavailable_marker_when_gemini_is_configured():
    page = Page(make_client().get("/").text)

    assert "data-unavailable" not in page.find("button", id="run-button").attrs
    assert not page.find_all("p", **{"data-error": "gemini_not_configured"})

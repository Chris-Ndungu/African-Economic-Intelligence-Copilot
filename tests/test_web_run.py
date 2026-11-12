"""The natural-language input and live progress partials (#30).

Run with ``TestClient``, ``StubLLMClient``, the demo data and an in-memory
repository, so they need no Postgres.
"""

import os
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from memory_repository import MemoryRepository
from test_web import Page, text

from backend.main import create_app
from backend.settings import Settings
from copilot_core.events import AnalysisFinishedEvent, FetchingDataEvent, InterpretingEvent
from copilot_core.llm import StubLLMClient
from copilot_core.progress import EMPTY_HINT, build_run_request, describe_event

QUESTION = "How did inflation change in Kenya and Nigeria from 2015 to 2023?"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}
SELECTION = "indicator=PCPIPCH&country=KEN&start=2015&end=2023"
PROGRESS_URL = re.compile(r"/partials/investigations/([0-9a-f-]{36})/progress")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def build():
    clients = []

    def make(scenario="run_success", **settings):
        app = create_app(Settings(gemini_api_key="test-key", **settings))
        app.state.repository = MemoryRepository()
        app.state.llm = StubLLMClient(scenario)
        client = TestClient(app)
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def post(client, body, path="/partials/investigations/run"):
    return client.post(path, content=body, headers=FORM)


def fragments(body):
    """The ``(event, data)`` of each server-sent event in a body."""
    out = []
    for block in body.split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if lines:
            event = lines[0].removeprefix("event: ")
            data = "\n".join(line.removeprefix("data: ") for line in lines[1:])
            out.append((event, data))
    return out


def start(client, body=None):
    response = post(client, body or "question=" + QUESTION.replace(" ", "+"))
    assert response.status_code == 200
    return response, PROGRESS_URL.search(response.text)


def stream(client, investigation_id):
    return fragments(client.get(f"/partials/investigations/{investigation_id}/progress").text)


# --- The form ----------------------------------------------------------------------


def test_the_workspace_has_a_labelled_question_box_above_the_selection(build):
    html = build().get("/").text
    page = Page(html)

    box = page.find("textarea", name="question")
    assert box.attrs["maxlength"] == "1000"
    assert box.attrs["placeholder"]
    assert text(page.find("label", **{"for": "question"})) == "Ask a question"
    assert html.index('id="question"') < html.index('id="selection-form"')
    assert "0 / 1,000 characters" in html
    form = page.find("form", id="run-form")
    assert form.attrs["hx-post"] == "/partials/investigations/run"
    assert form.attrs["hx-include"] == "#selection-form"
    assert "/static/run.js" in html


def test_the_button_starts_disabled_with_a_hint_saying_what_is_missing(build):
    page = Page(build().get("/").text)

    assert "disabled" in page.find("button", id="run-button").attrs
    assert EMPTY_HINT in text(page.find("p", id="run-hint"))


# --- Starting ------------------------------------------------------------------------


def test_a_valid_question_returns_a_progress_partial_with_the_id_only(build):
    client = build()
    response, match = start(client)

    investigation_id = match.group(1)
    page = Page(response.text)
    section = page.find("section", id="results")
    assert section.attrs["hx-ext"] == "sse"
    assert section.attrs["sse-connect"] == f"/partials/investigations/{investigation_id}/progress"
    assert section.attrs["sse-close"] == "close"
    assert "Kenya" not in response.text and "inflation" not in response.text
    assert page.find("ol", id="run-steps").attrs["aria-live"] == "polite"
    assert text(page.find("button", **{"data-cancel-run": None})) == "Cancel"
    saved = client.app.state.repository.get(uuid.UUID(investigation_id))
    assert saved.status == "pending" and saved.run.question == QUESTION


def test_a_selection_alone_starts_a_run(build):
    client = build()
    _, match = start(client, SELECTION)

    item = client.app.state.repository.get(uuid.UUID(match.group(1)))
    assert item.run.question is None and item.run.selection.countries == ["KEN"]


@pytest.mark.parametrize("body", ["question=", "question=+%0D%0A+", "indicator=PCPIPCH"])
def test_an_empty_request_shows_the_hint_and_creates_nothing(build, body):
    client = build()
    response = post(client, body)

    assert response.status_code == 200
    assert response.headers["hx-retarget"] == "#run-form"
    assert response.headers["hx-reswap"] == "outerHTML"
    assert EMPTY_HINT in response.text and "sse-connect" not in response.text
    assert not client.app.state.repository.items


def test_a_question_over_the_limit_shows_the_hint_and_keeps_the_text(build):
    client = build()
    response = post(client, "question=" + "a" * 1001)

    assert response.status_code == 200
    assert "1,001 characters; the limit is 1,000" in response.text
    assert "a" * 1001 in response.text
    assert not client.app.state.repository.items
    assert "the limit is" not in post(client, "question=" + "a" * 1000).text


def test_browser_line_breaks_count_once():
    assert build_run_request("a\r\n" * 400, None).hint is None


def test_without_a_database_the_form_says_so():
    client = TestClient(create_app(Settings(gemini_api_key="test-key")))
    response = post(client, "question=hello")

    assert response.status_code == 200
    assert "database is unavailable" in response.text and "sse-connect" not in response.text


# --- The stream ----------------------------------------------------------------------


def test_a_successful_run_streams_steps_then_saved_then_close(build):
    client = build()
    _, match = start(client)
    response = client.get(f"/partials/investigations/{match.group(1)}/progress")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = fragments(response.text)
    names = [name for name, _ in events]
    assert names[-2:] == ["outcome", "close"] and set(names[:-2]) == {"step"}
    steps = [text(Page(data).find("li")) for name, data in events if name == "step"]
    assert steps[0].endswith("Starting the investigation")
    assert any("Fetching data for the trend analysis" in step for step in steps)
    assert steps[-2].endswith("Interpreting the results")
    assert steps[-1].endswith("Checking numbers")
    saved = Page(events[-2][1]).find("div", **{"data-outcome": "saved"})
    assert saved.attrs["hx-get"] == f"/investigations/{match.group(1)}"
    assert saved.attrs["hx-push-url"] == "true" and saved.attrs["hx-target"] == "#workspace"
    assert client.app.state.repository.get(uuid.UUID(match.group(1))).status == "succeeded"


def test_a_gemini_outage_ends_with_a_failed_outcome_and_a_retry_button(build):
    client = build("run_gemini_down")
    _, match = start(client)
    events = stream(client, match.group(1))

    assert [name for name, _ in events] == ["step", "outcome", "close"]
    failed = Page(events[1][1])
    box = failed.find("div", **{"data-outcome": "failed"})
    assert box.attrs["data-code"] == "gemini_unavailable"
    retry = failed.find("button")
    assert retry.attrs["hx-post"] == f"/partials/investigations/{match.group(1)}/retry"
    assert text(retry) == "Try again"
    assert "Gemini" in text(box)


def test_retry_runs_the_same_input_as_a_new_run(build):
    client = build("run_gemini_down")
    _, match = start(client)
    stream(client, match.group(1))
    response = client.post(f"/partials/investigations/{match.group(1)}/retry")

    new = PROGRESS_URL.search(response.text).group(1)
    assert new != match.group(1)
    created = client.app.state.repository.get(uuid.UUID(new))
    assert created.run.question == QUESTION and created.status == "pending"


def test_a_finished_run_streams_only_its_final_event(build):
    client = build()
    _, match = start(client)
    stream(client, match.group(1))
    events = stream(client, match.group(1))

    assert [name for name, _ in events] == ["outcome", "close"]
    assert 'data-outcome="saved"' in events[0][1]


def test_an_unknown_run_is_answered_inside_the_stream(build):
    client = build()
    for bad in (str(uuid.uuid4()), "not-an-id"):
        response = client.get(f"/partials/investigations/{bad}/progress")
        assert response.status_code == 200
        assert [name for name, _ in fragments(response.text)] == ["outcome", "close"]


def test_a_script_in_the_question_is_escaped_in_every_fragment(build):
    client = build("run_gemini_down")
    response, match = start(client, "question=%3Cscript%3Ealert(1)%3C%2Fscript%3E")
    streamed = client.get(f"/partials/investigations/{match.group(1)}/progress").text
    retried = client.post(f"/partials/investigations/{match.group(1)}/retry").text
    too_long = post(client, "question=%3Cscript%3E" + "a" * 1001).text

    for body in (response.text, streamed, retried, too_long):
        assert "<script>" not in body
    assert "&lt;script&gt;" in too_long


def test_the_run_routes_stay_out_of_the_contract(build):
    paths = build().get("/openapi.json").json()["paths"]

    assert not [p for p in paths if p.startswith("/partials")]


# --- Words for the steps -------------------------------------------------------------


def test_steps_are_plain_words_and_a_failed_analysis_shows_its_error():
    assert describe_event(FetchingDataEvent(tool="analyze_trend")).text == (
        "Fetching data for the trend analysis"
    )
    failure = describe_event(
        AnalysisFinishedEvent(tool="detect_anomalies", result_id="r1", error="No data")
    )
    assert failure.kind == "error" and "No data" in failure.text
    assert describe_event(InterpretingEvent()).text == "Interpreting the results"

"""Streaming an investigation run over server-sent events (#29).

Integration tests with ``StubLLMClient``, the demo data and a real Postgres;
skipped with the reason shown when ``DATABASE_URL`` is not set.
"""

import asyncio
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.main import create_app
from backend.settings import Settings
from copilot_core.data import DuckDBDataService
from copilot_core.db import create_db_engine
from copilot_core.events import Heartbeat
from copilot_core.llm import StubLLMClient
from copilot_core.repository import InvestigationRepository
from copilot_core.runs import InvestigationService, RunSettings
from copilot_core.schemas import InvestigationRunRequest

QUESTION = "How did inflation change in Kenya and Nigeria from 2015 to 2023?"
KEY = "AIzaTEST-stream-key-987654"
TOOL_EVENTS = ["fetching_data", "analysis_started", "analysis_finished"]


def parse(text):
    """The ``(id, event, data)`` of each event in a stream body."""
    events = []
    for block in text.split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if lines:
            fields = dict(line.split(": ", 1) for line in lines)
            events.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return events


@pytest.fixture
def app_for(empty_table):
    clients = []

    def build(scenario="run_success", **settings):
        url = SecretStr(empty_table.render_as_string(hide_password=False))
        app = create_app(Settings(database_url=url, gemini_api_key=KEY, **settings))
        app.state.llm = StubLLMClient(scenario)
        client = TestClient(app)
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.close()


def start(client, body=None):
    response = client.post("/api/investigations/runs", json=body or {"question": QUESTION})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def stream(client, investigation_id):
    response = client.get(f"/api/investigations/{investigation_id}/events")
    return response, parse(response.text)


def names(events):
    return [name for _, name, _ in events]


# --- Creating a run -------------------------------------------------------------------


def test_creating_a_run_returns_202_pending_without_starting_it(app_for):
    client = app_for()
    response = client.post("/api/investigations/runs", json={"question": QUESTION})
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["events_url"] == f"/api/investigations/{body['id']}/events"
    assert response.headers["location"] == body["events_url"]
    assert "inflation" not in response.headers["location"]
    assert client.get(f"/api/investigations/{body['id']}").json()["status"] == "pending"
    assert client.app.state.llm.calls == []


@pytest.mark.parametrize(
    ("body", "fragment"),
    [({}, "question, a selection or both"), ({"question": "x" * 1001}, "1000")],
)
def test_creating_a_run_has_the_same_422_rules(app_for, body, fragment):
    response = app_for().post("/api/investigations/runs", json=body)
    assert response.status_code == 422
    assert fragment in response.text


# --- Outcomes -------------------------------------------------------------------------


def test_success_with_two_tools_streams_every_step(app_for):
    client = app_for("run_success")
    investigation_id = start(client)
    response, events = stream(client, investigation_id)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert names(events) == [
        "started",
        *TOOL_EVENTS,
        *TOOL_EVENTS,
        "interpreting",
        "validating",
        "saved",
    ]
    assert [number for number, _, _ in events] == list(range(1, len(events) + 1))
    assert events[0][2] == {"investigation_id": investigation_id}
    assert events[3][2] == {"tool": "analyze_trend", "result_id": "r1", "error": None}
    assert events[-1][2] == {"investigation_id": investigation_id, "status": "succeeded"}
    saved = client.get(f"/api/investigations/{investigation_id}").json()
    assert saved["status"] == "succeeded"
    assert len(saved["result"]["charts"]) == 2


@pytest.mark.parametrize(
    ("scenario", "settings", "middle", "code", "service"),
    [
        ("run_gemini_down", {}, [], "gemini_unavailable", "gemini"),
        ("run_success", {"data_dir": "missing-folder"}, [], "data_unavailable", "data_service"),
        ("run_step_limit", {"tool_step_limit": 2}, TOOL_EVENTS * 2, "step_limit_reached", None),
        ("run_slow", {"investigation_time_limit_seconds": 0.3}, [], "timeout", None),
    ],
)
def test_failures_end_in_one_failed_event_matching_the_saved_row(
    app_for, scenario, settings, middle, code, service
):
    client = app_for(scenario, **settings)
    investigation_id = start(client)
    _, events = stream(client, investigation_id)
    assert names(events) == ["started", *middle, "failed"]
    failed = events[-1][2]
    assert (failed["code"], failed["service"]) == (code, service)
    saved = client.get(f"/api/investigations/{investigation_id}").json()
    assert saved["status"] == "failed"
    assert saved["error"] == {"code": code, "message": failed["message"], "service": service}
    assert saved["result"] is None


def test_an_unsupported_question_ends_in_saved(app_for):
    client = app_for("run_unsupported")
    _, events = stream(client, start(client))
    assert names(events) == ["started", "interpreting", "validating", "saved"]


# --- Reopening and concurrency ----------------------------------------------------------


def test_an_unknown_id_answers_404(app_for):
    response = app_for().get(f"/api/investigations/{uuid.uuid4()}/events")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_reopening_a_finished_run_sends_only_its_final_event(app_for):
    client = app_for("run_success")
    investigation_id = start(client)
    stream(client, investigation_id)
    _, events = stream(client, investigation_id)
    assert names(events) == ["saved"]
    assert len(client.app.state.llm.calls) == 3  # not run again


def test_reopening_a_failed_run_sends_only_its_failed_event(app_for):
    client = app_for("run_gemini_down")
    investigation_id = start(client)
    stream(client, investigation_id)
    _, events = stream(client, investigation_id)
    assert names(events) == ["failed"]
    assert events[0][2]["code"] == "gemini_unavailable"


def test_a_second_connection_while_running_gets_in_progress_and_no_second_run(app_for, empty_table):
    client = app_for("run_success")
    investigation_id = start(client)
    engine = create_db_engine(empty_table)
    InvestigationRepository(engine).claim(uuid.UUID(investigation_id), 60)  # another connection
    _, events = stream(client, investigation_id)
    assert names(events) == ["in_progress"]
    assert events[0][2] == {"investigation_id": investigation_id, "status": "running"}
    assert client.app.state.llm.calls == []
    engine.dispose()


def test_a_stale_pending_run_fails_as_not_started(app_for):
    client = app_for("run_success", pending_run_timeout_seconds=0.1)
    investigation_id = start(client)
    time.sleep(0.3)
    _, events = stream(client, investigation_id)
    assert names(events) == ["failed"]
    assert events[0][2]["code"] == "not_started"
    assert client.app.state.llm.calls == []


def test_the_startup_sweep_fails_stale_pending_runs(app_for, empty_table):
    client = app_for("run_success", pending_run_timeout_seconds=0.1)
    investigation_id = start(client)
    time.sleep(0.3)
    with app_for("run_success", pending_run_timeout_seconds=0.1):
        pass
    saved = client.get(f"/api/investigations/{investigation_id}").json()
    assert saved["status"] == "failed"
    assert saved["error"]["code"] == "not_started"


# --- The stream itself --------------------------------------------------------------------


def test_a_ping_comment_is_sent_while_a_step_runs(app_for):
    client = app_for("run_slow_tools", stream_ping_seconds=0.3)
    response, events = stream(client, start(client))
    assert ": ping\n\n" in response.text
    assert names(events)[-1] == "saved"


def test_events_contain_no_keys_tool_data_or_stack_traces(app_for):
    client = app_for("run_success")
    response, _ = stream(client, start(client))
    for leak in (KEY, '"points"', '"series"', "Traceback", "slope"):
        assert leak not in response.text


def test_the_synchronous_endpoint_still_works(app_for):
    client = app_for("run_success")
    response = client.post("/api/investigations/run", json={"question": QUESTION})
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


# --- In copilot_core ----------------------------------------------------------------------


@pytest.fixture
def service(empty_table):
    engine = create_db_engine(empty_table)
    repository = InvestigationRepository(engine)

    def build(scenario, **settings):
        return InvestigationService(
            repository,
            data=DuckDBDataService,
            llm=lambda: StubLLMClient(scenario),
            settings=RunSettings(**settings),
        )

    yield build
    engine.dispose()


def test_events_are_emitted_as_each_step_happens_not_buffered(service):
    runs = service("run_slow_tools")
    investigation = runs.create(InvestigationRunRequest(question=QUESTION))

    async def read():
        began = time.perf_counter()
        return [
            (type(e).__name__, time.perf_counter() - began)
            async for e in runs.stream(investigation)
            if not isinstance(e, Heartbeat)
        ]

    timed = asyncio.run(read())
    seen = dict(timed)
    assert seen["AnalysisFinishedEvent"] < 1.0  # before the two-second reply
    assert seen["SavedEvent"] >= 2.0


def test_a_client_disconnect_cancels_the_run_and_saves_it_failed(service):
    runs = service("run_slow")
    investigation = runs.create(InvestigationRunRequest(question=QUESTION))

    async def disconnect_after_first_event():
        events = runs.stream(investigation)
        first = await anext(events)
        await events.aclose()  # what the server does when the client goes away
        await asyncio.sleep(0.1)
        return first

    first = asyncio.run(disconnect_after_first_event())
    assert type(first).__name__ == "StartedEvent"
    saved = runs.get(investigation.id)
    assert saved.status == "failed"
    assert saved.error is not None and saved.error.code == "client_disconnected"
    assert saved.result is None

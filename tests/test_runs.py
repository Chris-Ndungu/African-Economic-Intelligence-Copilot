"""Running an investigation through the API (#28).

Integration tests with ``StubLLMClient``, the demo data and a real Postgres.
They are skipped, with the reason shown, when ``DATABASE_URL`` is not set;
the request-rule tests that need no database run anyway.
"""

import time

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.main import create_app
from backend.settings import Settings
from copilot_core.db import create_db_engine
from copilot_core.llm import StubLLMClient
from copilot_core.repository import InvestigationRepository
from copilot_core.schemas import Selection

SELECTION = {"countries": ["KEN"], "indicator": "PCPIPCH", "start": "2015", "end": "2023"}
QUESTION = "How did inflation change in Kenya and Nigeria from 2015 to 2023?"


def make_client(url, scenario, **settings):
    database = SecretStr(url.render_as_string(hide_password=False)) if url else None
    app = create_app(Settings(database_url=database, **settings))
    app.state.llm = StubLLMClient(scenario)
    return TestClient(app)


@pytest.fixture
def run(empty_table):
    """Post a run with a scenario; returns the response, the saved row and the stub."""
    clients = []

    def post(body, scenario="run_success", **settings):
        client = make_client(empty_table, scenario, **settings)
        clients.append(client)
        response = client.post("/api/investigations/run", json=body)
        newest = client.get("/api/investigations").json()["items"]
        saved = client.get(f"/api/investigations/{newest[0]['id']}").json() if newest else None
        return response, saved, client.app.state.llm

    yield post
    for client in clients:
        client.close()


# --- Request rules ------------------------------------------------------------------


@pytest.fixture
def no_db_client():
    with make_client(None, "run_success") as client:
        yield client


def test_a_request_with_neither_question_nor_selection_is_rejected(no_db_client):
    response = no_db_client.post("/api/investigations/run", json={})
    assert response.status_code == 422
    assert "question, a selection or both" in response.text


def test_a_question_longer_than_1000_characters_is_rejected_naming_the_limit(no_db_client):
    response = no_db_client.post("/api/investigations/run", json={"question": "x" * 1001})
    assert response.status_code == 422
    assert "1000" in response.json()["details"][0]["message"]


def test_a_null_question_is_rejected(no_db_client):
    body = {"question": None, "selection": SELECTION}
    assert no_db_client.post("/api/investigations/run", json=body).status_code == 422


def test_without_a_database_the_run_answers_503(no_db_client):
    response = no_db_client.post("/api/investigations/run", json={"question": QUESTION})
    assert response.status_code == 503
    assert response.json()["service"] == "database"


# --- Success ------------------------------------------------------------------------


def test_a_question_runs_and_is_saved_as_succeeded(run):
    response, saved, stub = run({"question": QUESTION})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == saved
    assert body["status"] == "succeeded"
    assert body["error"] is None
    assert body["data_mode"] == "demo"

    result = body["result"]
    interpretation = result["interpretation"]
    assert interpretation["prompt_version"] == "interpret_v1"
    assert interpretation["model"] == "stub-gemini"
    assert [f["verification"] for f in interpretation["findings"]] == ["verified"] * 3
    assert interpretation["unverified_count"] == 0
    assert [r["result_id"] for r in result["tool_results"]] == ["r1", "r2"]
    assert [(c["result_id"], c["kind"]) for c in result["charts"]] == [
        ("r1", "line"),
        ("r2", "line"),
    ]
    assert result["charts"][0]["series_ids"] == ["series:PCPIPCH:KEN:2015-2023"]
    assert body["request"]["countries"] == ["KEN", "NGA"]
    assert body["request"]["question"] == QUESTION

    run_record = body["run"]
    assert run_record["question"] == QUESTION
    assert run_record["prompt_version"] == "interpret_v1"
    assert [c["result_id"] for c in run_record["tool_calls"]] == ["r1", "r2"]
    assert run_record["validation"] == {
        "verified_count": interpretation["verified_count"],
        "unverified_count": 0,
        "unverified_findings": 0,
    }
    assert run_record["usage"]["calls"] == 3
    assert "<question>How did inflation" in stub.calls[0].messages[0].text


def test_a_selection_alone_runs_with_the_fixed_question(run):
    response, saved, stub = run({"selection": SELECTION}, scenario="run_selection")
    assert response.status_code == 200, response.text
    expected = "Describe the trend in PCPIPCH for KEN from 2015 to 2023"
    assert f"<question>{expected}</question>" in stub.calls[0].messages[0].text
    assert saved["title"] == expected
    assert saved["run"]["selection"] == SELECTION
    assert saved["request"]["investigation_type"] == "trend"


def test_with_both_the_selection_limits_what_the_tools_may_query(run):
    body = {"question": "Compare Kenya with Nigeria", "selection": SELECTION}
    response, saved, _ = run(body, scenario="run_out_of_selection")
    assert response.status_code == 200, response.text
    nigeria, kenya = saved["run"]["tool_calls"]
    assert nigeria["status"] == "error" and "outside the selection" in nigeria["error"]
    assert kenya["status"] == "ok"


def test_unverified_claims_do_not_fail_the_run_and_are_saved_flagged(run):
    response, saved, _ = run({"question": QUESTION}, scenario="run_unverified")
    assert response.status_code == 200
    findings = saved["result"]["interpretation"]["findings"]
    assert findings[-1]["verification"] == "unverified"
    assert "not in any tool result" in findings[-1]["reasons"][0]
    assert saved["run"]["validation"]["unverified_findings"] == 1


def test_an_unsupported_question_succeeds_with_a_reason_and_no_findings(run):
    response, saved, _ = run(
        {"question": "What will inflation in Kenya be next year?"}, scenario="run_unsupported"
    )
    assert response.status_code == 200
    interpretation = saved["result"]["interpretation"]
    assert saved["status"] == "succeeded"
    assert interpretation["unsupported_reason"]
    assert interpretation["findings"] == []
    assert saved["result"]["charts"] == []
    assert saved["request"] is None


# --- Failures -----------------------------------------------------------------------


def assert_failed(saved, code, service):
    assert saved["status"] == "failed"
    assert saved["error"]["code"] == code
    assert saved["error"]["service"] == service
    assert saved["result"] is None  # no findings presented as a success


@pytest.mark.parametrize(
    ("scenario", "code"),
    [
        ("run_gemini_down", "gemini_unavailable"),
        ("run_not_configured", "gemini_not_configured"),
        ("run_gemini_blocked", "gemini_blocked"),
        ("run_gemini_timeout", "gemini_timeout"),
        ("run_malformed", "interpretation_invalid"),
    ],
)
def test_gemini_failures_are_saved_and_answer_503_naming_gemini(run, scenario, code):
    response, saved, _ = run({"question": QUESTION}, scenario=scenario)
    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert response.json()["service"] == "gemini"
    assert_failed(saved, code, "gemini")


def test_a_data_outage_is_saved_and_answers_503_naming_data(run, tmp_path):
    response, saved, stub = run({"question": QUESTION}, data_dir=tmp_path / "missing")
    assert response.status_code == 503
    assert response.json()["service"] == "data_service"
    assert_failed(saved, "data_unavailable", "data_service")
    assert stub.calls == []


def test_the_step_limit_is_saved_and_answers_422_suggesting_a_narrower_question(run):
    response, saved, _ = run({"question": QUESTION}, scenario="run_step_limit", tool_step_limit=2)
    assert response.status_code == 422
    assert response.json()["code"] == "step_limit_reached"
    assert "narrower question" in response.json()["message"]
    assert_failed(saved, "step_limit_reached", None)
    assert len(saved["run"]["tool_calls"]) == 2


def test_a_run_over_the_time_limit_is_saved_as_timeout(run):
    response, saved, _ = run(
        {"question": QUESTION}, scenario="run_slow", investigation_time_limit_seconds=0.3
    )
    assert response.status_code == 503
    assert_failed(saved, "timeout", None)


# --- Restarts -----------------------------------------------------------------------


def test_runs_left_running_by_a_restart_are_marked_interrupted(empty_table):
    engine = create_db_engine(empty_table)
    repository = InvestigationRepository(engine)
    stale = repository.create_run(QUESTION, None, "demo", "Stale run")
    repository.claim(stale.id, pending_timeout_seconds=60)
    time.sleep(0.2)
    with make_client(empty_table, "run_success", investigation_time_limit_seconds=0.1):
        pass  # starting the app runs the sweep
    swept = repository.get(stale.id)
    assert swept.status == "failed"
    assert swept.error is not None and swept.error.code == "interrupted"
    engine.dispose()


def test_recent_running_runs_are_left_alone_by_the_sweep(empty_table):
    engine = create_db_engine(empty_table)
    repository = InvestigationRepository(engine)
    current = repository.create_run(None, Selection(**SELECTION), "demo", "Current run")
    repository.claim(current.id, pending_timeout_seconds=60)
    with make_client(empty_table, "run_success"):
        pass
    assert repository.get(current.id).status == "running"
    engine.dispose()

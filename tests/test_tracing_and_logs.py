"""Backend spans, structured logs and the leak check (#42).

A full investigation runs with the stub client. Most tests use the in-memory
repository; the last uses real Postgres to check the SQL spans and is skipped,
with the reason, when ``DATABASE_URL`` is not set.
"""

import json
import logging
import os

import pytest
from fastapi.testclient import TestClient
from memory_repository import MemoryRepository
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.logging_config import JsonFormatter
from backend.main import create_app
from backend.settings import Settings
from backend.telemetry import instrument_engine
from copilot_core.llm import StubLLMClient
from copilot_core.repository import InvestigationRepository
from copilot_core.telemetry import is_sensitive, safe_attributes

API_KEY = "TEST-KEY-123"
PASSWORD = "TEST-PASSWORD-123"
QUESTION = "TEST-QUESTION-123 how did inflation change in Kenya?"
SECRETS = (API_KEY, PASSWORD, "TEST-QUESTION-123")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith(("COPILOT_", "OTEL_")) or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    # The fake database URL is never connected to: the startup jobs are not needed here.
    monkeypatch.setattr("backend.main.sweep_stale_runs", lambda settings: 0)
    monkeypatch.setattr("backend.main.delete_expired_anonymous", lambda settings: 0)


def everything_in(spans) -> str:
    """Every span with its name, attributes, events, status and resource, as text."""
    return json.dumps(
        [
            {
                "name": s.name,
                "attributes": dict(s.attributes or {}),
                "events": [(e.name, dict(e.attributes or {})) for e in s.events],
                "status": [str(s.status.status_code), s.status.description],
                "resource": dict(s.resource.attributes),
            }
            for s in spans
        ],
        default=str,
    )


def make_app(exporter, scenario="run_success", **settings):
    app = create_app(
        Settings(
            gemini_api_key=API_KEY,
            database_url=f"postgresql+psycopg://copilot:{PASSWORD}@127.0.0.1:1/copilot",
            **settings,
        ),
        span_exporter=exporter,
    )
    app.state.llm = StubLLMClient(scenario)
    return app


def run_one(app, expect=200):
    with TestClient(app) as client:
        response = client.post("/api/investigations/run", json={"question": QUESTION})
    assert response.status_code == expect, response.text
    return response.json()


def test_a_run_has_the_documented_span_tree_and_no_secret_in_spans_or_logs(caplog, capsys):
    exporter = InMemorySpanExporter()
    app = make_app(exporter)
    app.state.repository = MemoryRepository()
    with caplog.at_level(logging.DEBUG):
        saved = run_one(app)
    spans = exporter.get_finished_spans()
    by_name = {s.name: s for s in spans}

    server = next(s for s in spans if s.kind.name == "SERVER")
    run = by_name["investigation.run"]
    loop = by_name["llm.tool_loop"]
    assert run.parent.span_id == server.context.span_id
    assert loop.parent.span_id == run.context.span_id
    tools = [s for s in spans if s.name.startswith("tool.")]
    assert tools and all(t.parent.span_id == loop.context.span_id for t in tools)
    series = [s for s in spans if s.name == "data.get_series"]
    tool_ids = {t.context.span_id for t in tools}
    assert series and all(s.parent.span_id in tool_ids for s in series)
    query = next(s for s in spans if s.name == "duckdb.query")
    assert "?" in query.attributes["db.statement"] and query.attributes["row.count"] >= 1
    for name in ("interpretation.validate", "investigation.save"):
        assert by_name[name].parent.span_id == run.context.span_id
    assert run.attributes["investigation.id"] == saved["id"]
    assert run.attributes["data.mode"] == "demo"
    assert tools[0].attributes["tool.name"] == tools[0].name.removeprefix("tool.")
    assert "result.id" in tools[0].attributes and "row.count" in tools[0].attributes
    assert "claims.verified" in by_name["interpretation.validate"].attributes

    text = everything_in(spans)
    printed = capsys.readouterr().out
    formatted = [JsonFormatter().format(r) for r in caplog.records]
    for secret in SECRETS:
        assert secret not in text, f"{secret} is in a span"
        assert secret not in printed, f"{secret} is in the stdout logs"
        assert all(secret not in line for line in formatted), f"{secret} is in a log line"
        for record in caplog.records:
            assert secret not in record.getMessage()
            assert secret not in json.dumps(vars(record), default=str)


def test_logs_are_single_line_json_with_trace_ids_and_one_outcome_line(capsys):
    exporter = InMemorySpanExporter()
    app = make_app(exporter, log_level="info")
    app.state.repository = MemoryRepository()
    saved = run_one(app)
    out = capsys.readouterr().out.splitlines()
    lines = [json.loads(line) for line in out if line.startswith("{")]
    assert lines
    for line in lines:
        assert {"timestamp", "level", "logger", "message", "trace_id", "span_id"} <= line.keys()
    outcomes = [line for line in lines if line["message"] == "investigation succeeded"]
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["investigation_id"] == saved["id"] and outcome["outcome"] == "succeeded"
    run = next(s for s in exporter.get_finished_spans() if s.name == "investigation.run")
    assert outcome["trace_id"] == format(run.context.trace_id, "032x")
    assert not any("testclient" in line["message"] for line in lines)


def test_a_failed_run_sets_an_error_status_with_the_code_and_no_message(capsys):
    exporter = InMemorySpanExporter()
    app = make_app(exporter, scenario="run_gemini_down")  # Gemini is down: the run fails
    app.state.repository = MemoryRepository()
    with TestClient(app) as client:
        response = client.post("/api/investigations/run", json={"question": QUESTION})
    assert response.status_code >= 400
    spans = exporter.get_finished_spans()
    run = next(s for s in spans if s.name == "investigation.run")
    assert run.status.status_code.name == "ERROR"
    assert run.attributes["error.code"] and run.attributes["error.type"]
    assert "TEST-QUESTION-123" not in everything_in(spans)
    failed = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and '"investigation failed"' in line
    ]
    assert len(failed) == 1 and failed[0]["error_code"] == run.attributes["error.code"]


def test_the_redaction_drops_names_that_look_like_secrets():
    names = ["question", "prompt", "api_key", "password", "token", "authorization", "database_url"]
    assert all(is_sensitive(n) for n in names)
    assert is_sensitive("user.question") and is_sensitive("access_token")
    assert not is_sensitive("gen_ai.usage.input_tokens")
    assert safe_attributes({"question": "x", "tool.name": "trend", "none": None}) == {
        "tool.name": "trend"
    }


def test_sql_spans_keep_placeholders_and_never_the_question(migrated):
    exporter = InMemorySpanExporter()
    app = make_app(exporter)
    instrument_engine(app, migrated)
    app.state.repository = InvestigationRepository(migrated)
    run_one(app)
    spans = exporter.get_finished_spans()
    sql = [
        s
        for s in spans
        if s.attributes and "db.statement" in s.attributes and s.name != "duckdb.query"
    ]
    assert any("investigations" in s.attributes["db.statement"] for s in sql)
    text = everything_in(spans)
    for secret in SECRETS:
        assert secret not in text

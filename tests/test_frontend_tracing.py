"""Browser-to-server tracing (#44): trace context in the run and stream routes, and the forwarder."""

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from memory_repository import MemoryRepository
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import backend.otlp
from backend.main import create_app
from backend.settings import Settings
from copilot_core.llm import StubLLMClient

ROOT = Path(__file__).resolve().parent.parent
TRACE = "0af7651916cd43dd8448eb211c80319c"
PARENT = "b7ad6b7169203331"
TRACEPARENT = f"00-{TRACE}-{PARENT}-01"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}
BODY = "question=How+did+inflation+change+in+Kenya+from+2015+to+2023"
PROGRESS = re.compile(r'sse-connect="(/partials/investigations/[0-9a-f-]{36}/progress[^"]*)"')
SPAN_DOCUMENT = (
    b'{"resourceSpans":[{"resource":{},"scopeSpans":[{"spans":'
    b'[{"name":"ui.run_investigation","traceId":"x","spanId":"y"}]}]}]}'
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith(("COPILOT_", "OTEL_")) or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def make(**settings):
    exporter = InMemorySpanExporter()
    app = create_app(Settings(gemini_api_key="k", **settings), span_exporter=exporter)
    app.state.repository = MemoryRepository()
    app.state.llm = StubLLMClient("run_success")
    return app, exporter


def start_run(client, headers=None):
    response = client.post(
        "/partials/investigations/run", content=BODY, headers={**FORM, **(headers or {})}
    )
    assert response.status_code == 200, response.text
    match = PROGRESS.search(response.text)
    assert match, response.text
    return match.group(1)


def run_span(exporter):
    return next(s for s in exporter.get_finished_spans() if s.name == "investigation.run")


def test_the_run_request_joins_the_browser_trace_and_the_stream_url_carries_it():
    app, exporter = make()
    with TestClient(app) as client:
        url = start_run(client, {"traceparent": TRACEPARENT})
    assert f"?traceparent=00-{TRACE}-" in url
    post = next(s for s in exporter.get_finished_spans() if s.kind.name == "SERVER")
    assert format(post.context.trace_id, "032x") == TRACE
    assert format(post.parent.span_id, "016x") == PARENT


def test_opening_the_stream_url_runs_the_investigation_in_that_trace():
    app, exporter = make()
    with TestClient(app) as client:
        url = start_run(client, {"traceparent": TRACEPARENT})
        stream = client.get(url)
    assert stream.status_code == 200 and 'data-outcome="saved"' in stream.text
    assert format(run_span(exporter).context.trace_id, "032x") == TRACE


@pytest.mark.parametrize(
    "value",
    ["garbage", "00-" + "0" * 32 + "-" + PARENT + "-01", f"00-{TRACE}-{PARENT}", "ff-" + TRACE],
)
def test_a_malformed_traceparent_starts_a_new_trace_and_is_not_an_error(value):
    app, exporter = make()
    with TestClient(app) as client:
        url = start_run(client)
        stream = client.get(url.split("?")[0], params={"traceparent": value})
    assert stream.status_code == 200 and 'data-outcome="saved"' in stream.text
    assert format(run_span(exporter).context.trace_id, "032x") != TRACE


def test_a_run_without_trace_context_still_renders_a_working_stream_url():
    app, _ = make()
    with TestClient(app) as client:
        url = start_run(client)
        assert client.get(url).status_code == 200


def test_the_forwarder_rejects_bodies_over_1_mb_with_413():
    app, _ = make(otlp_endpoint="http://collector.invalid:4318")
    with TestClient(app) as client:
        response = client.post("/otlp/v1/traces", content=b"x" * (1_000_001))
    assert response.status_code == 413


def test_the_forwarder_drops_the_data_with_204_when_no_endpoint_is_configured(monkeypatch):
    called = []
    monkeypatch.setattr(backend.otlp, "forward_traces", lambda *args: called.append(args))
    app, _ = make()
    with TestClient(app) as client:
        response = client.post("/otlp/v1/traces", content=SPAN_DOCUMENT)
    assert response.status_code == 204 and called == []


def test_the_forwarder_adds_the_auth_header_on_the_server_and_is_not_traced(monkeypatch):
    called = []
    monkeypatch.setattr(backend.otlp, "forward_traces", lambda *args: called.append(args))
    app, exporter = make(
        otlp_endpoint="http://collector.invalid:4318", otlp_headers="Authorization=Basic abc"
    )
    with TestClient(app) as client:
        response = client.post("/otlp/v1/traces", content=SPAN_DOCUMENT)
    assert response.status_code == 204
    endpoint, headers, body = called[0]
    assert endpoint == "http://collector.invalid:4318"
    assert headers == {"Authorization": "Basic abc"} and body == SPAN_DOCUMENT
    assert exporter.get_finished_spans() == ()


def test_a_down_collector_or_a_non_otlp_body_still_answers_204(monkeypatch):
    def down(*args):
        raise OSError("collector is down")

    monkeypatch.setattr(backend.otlp, "forward_traces", down)
    app, _ = make(otlp_endpoint="http://collector.invalid:4318")
    with TestClient(app) as client:
        assert client.post("/otlp/v1/traces", content=SPAN_DOCUMENT).status_code == 204
        assert client.post("/otlp/v1/traces", content=b"not json").status_code == 204
        assert client.post("/otlp/v1/traces", content=b'{"a": 1}').status_code == 204


def test_the_forwarder_is_not_in_the_openapi_contract():
    app, _ = make()
    assert not [path for path in app.openapi()["paths"] if "otlp" in path]


def test_no_collector_address_or_token_is_in_the_static_files_or_the_page():
    app, _ = make(
        otlp_endpoint="http://collector.invalid:4318", otlp_headers="Authorization=Basic SECRET-XYZ"
    )
    with TestClient(app) as client:
        page = client.get("/").text
    files = [
        p
        for p in (ROOT / "backend" / "static").rglob("*")
        if p.is_file() and "vendor" not in p.parts and p.suffix in {".js", ".css", ".html"}
    ]
    assert any(p.name == "tracing.js" for p in files)
    for text in [page, *(p.read_text(encoding="utf-8") for p in files)]:
        assert "collector.invalid" not in text and "SECRET-XYZ" not in text
        assert not re.search(r":4318|:4317|otlp-gateway|grafana\.net", text)
        # The only OTLP address in the browser is the same-origin path.
        for match in re.finditer(r"v1/traces", text):
            assert text[max(0, match.start() - 6) : match.start()] == "/otlp/"
    assert "/static/tracing.js" in page

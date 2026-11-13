"""Tracing of API requests (#41): off without a collector, quiet, and one server span."""

import logging
import time

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.main import create_app
from backend.settings import Settings
from backend.telemetry import OncePerMinute


@pytest.fixture(autouse=True)
def no_database(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)


def test_a_countries_request_produces_one_server_span_named_for_the_route():
    exporter = InMemorySpanExporter()
    with TestClient(create_app(Settings(), span_exporter=exporter)) as client:
        assert client.get("/api/countries").status_code == 200
    spans = exporter.get_finished_spans()
    server = [s for s in spans if s.kind.name == "SERVER"]
    assert len(server) == 1
    span = server[0]
    assert span.name == "GET /api/countries"
    assert span.attributes["http.route"] == "/api/countries"
    attributes = span.attributes
    assert attributes.get("http.status_code", attributes.get("http.response.status_code")) == 200
    assert attributes.get("http.method", attributes.get("http.request.method")) == "GET"
    assert span.resource.attributes["service.name"] == "copilot-api"
    assert span.resource.attributes["deployment.environment"] == "local"


def test_health_requests_are_not_traced():
    exporter = InMemorySpanExporter()
    with TestClient(create_app(Settings(), span_exporter=exporter)) as client:
        assert client.get("/health").status_code == 200
    assert exporter.get_finished_spans() == ()


def test_without_an_endpoint_nothing_is_set_up_and_nothing_is_logged(caplog):
    with caplog.at_level(logging.DEBUG):
        app = create_app(Settings())
        with TestClient(app) as client:
            assert client.get("/api/countries").status_code == 200
    assert not hasattr(app.state, "tracer_provider")
    assert not [
        r for r in caplog.records if "opentelemetry" in r.name or "telemetry" in r.getMessage()
    ]


def test_a_down_collector_adds_no_latency_to_requests():
    app = create_app(Settings(otlp_endpoint="http://127.0.0.1:9"))
    with TestClient(app) as client:
        client.get("/api/countries")  # warm up
        started = time.perf_counter()
        for _ in range(5):
            assert client.get("/api/countries").status_code == 200
        average = (time.perf_counter() - started) / 5
    app.state.tracer_provider.shutdown()
    assert average < 0.25  # the export runs on a background thread


def test_export_errors_are_logged_at_most_once_a_minute():
    throttle = OncePerMinute(interval=60)
    record = logging.LogRecord("x", logging.ERROR, "f", 1, "export failed", None, None)
    assert throttle.filter(record) is True
    assert throttle.filter(record) is False
    info = logging.LogRecord("x", logging.INFO, "f", 1, "ok", None, None)
    assert throttle.filter(info) is True

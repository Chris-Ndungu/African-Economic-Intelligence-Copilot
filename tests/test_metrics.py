"""Investigation and Gemini metrics (#43), read from an in-memory metric reader."""

import os
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from memory_repository import MemoryRepository
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.main import create_app
from backend.settings import Settings
from copilot_core.llm import StubLLMClient

# The meter provider can be set once per process; the instruments in
# copilot_core.telemetry bind to it when it is.
READER = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[READER]))

QUESTION = {"question": "How did inflation change in Kenya from 2015 to 2023?"}
OURS = {
    "investigations_total",
    "investigation_duration_seconds",
    "llm_request_duration_seconds",
    "llm_tokens_total",
    "claims_total",
    "rate_limit_hits_total",
}
ALLOWED_LABELS = {"outcome", "model", "type", "verified", "limit"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith(("COPILOT_", "OTEL_")) or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def snapshot():
    """``{(metric, labels): value}``; a histogram's value is its count."""
    out = {}
    data = READER.get_metrics_data()
    for resource in data.resource_metrics if data else []:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                for point in metric.data.data_points:
                    value = getattr(point, "value", None)
                    if value is None:
                        value = point.count
                    out[(metric.name, tuple(sorted(point.attributes.items())))] = value
    return out


def run(scenario):
    app = create_app(Settings(gemini_api_key="k"), span_exporter=InMemorySpanExporter())
    app.state.repository = MemoryRepository()
    app.state.llm = StubLLMClient(scenario)
    with TestClient(app) as client:
        return client.post("/api/investigations/run", json=QUESTION)


def delta(before, after):
    return Counter({k: after[k] - before.get(k, 0) for k in after if after[k] != before.get(k, 0)})


def test_a_successful_and_a_failed_run_are_counted_with_their_labels():
    before = snapshot()
    assert run("run_success").status_code == 200
    assert run("run_gemini_down").status_code >= 400
    changed = delta(before, snapshot())

    outcomes = {
        dict(labels)["outcome"]: value
        for (name, labels), value in changed.items()
        if name == "investigations_total"
    }
    failures = {k: v for k, v in outcomes.items() if k not in ("succeeded", "unsupported")}
    assert outcomes["succeeded"] == 1
    assert sum(failures.values()) == 1 and all(code.isidentifier() for code in failures)

    durations = [k for k in changed if k[0] == "investigation_duration_seconds"]
    assert sum(changed[k] for k in durations) == 2
    tokens = {
        dict(labels)["type"]: value
        for (name, labels), value in changed.items()
        if name == "llm_tokens_total"
    }
    assert tokens["input"] > 0 and tokens["output"] > 0
    assert any(name == "llm_request_duration_seconds" for name, _ in changed)
    claims = {
        dict(labels)["verified"]: value
        for (name, labels), value in changed.items()
        if name == "claims_total"
    }
    assert claims["true"] > 0


def test_no_metric_has_a_label_with_unbounded_values():
    run("run_success")
    for (name, labels), _ in snapshot().items():
        if name not in OURS:  # the HTTP server metrics of the FastAPI instrumentation
            continue
        assert {key for key, _ in labels} <= ALLOWED_LABELS
        for key, value in labels:
            assert key != "outcome" or isinstance(value, str) and len(value) < 40


def test_a_rate_limit_hit_is_counted_by_limit_kind():
    from copilot_core.rate_limit import (  # noqa: PLC0415
        MemoryAttemptStore,
        RateLimitedError,
        RateLimits,
        RunLimiter,
    )

    limiter = RunLimiter(MemoryAttemptStore(), RateLimits(per_client_limit=1, daily_limit=9))
    before = snapshot()
    limiter.check("a")
    with pytest.raises(RateLimitedError):
        limiter.check("a")
    changed = delta(before, snapshot())
    assert changed[("rate_limit_hits_total", (("limit", "client"),))] == 1

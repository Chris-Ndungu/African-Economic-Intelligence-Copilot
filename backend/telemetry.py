"""OpenTelemetry setup for the API: traces over OTLP, off unless configured.

``setup_telemetry`` runs once at startup. Without ``OTEL_EXPORTER_OTLP_ENDPOINT``
it does nothing: no provider, no exporter, nothing logged per request, so
tests and plain ``uvicorn`` runs stay quiet. With it, spans are batched and
exported on a background thread, so a down collector adds no request latency,
and export errors are logged at most once a minute. Health checks are not
traced. Nothing here records a question, a credential or a connection string.
"""

from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

from backend.settings import Settings

EXCLUDED_URLS = "/health"
EXPORT_LOGGERS = ("opentelemetry.exporter.otlp.proto.http.trace_exporter", "opentelemetry.sdk")
QUIET_SECONDS = 60.0


class OncePerMinute(logging.Filter):
    """Lets a warning or error through at most once per ``interval`` seconds."""

    def __init__(self, interval: float = QUIET_SECONDS) -> None:
        super().__init__()
        self.interval = interval
        self._last = float("-inf")
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            return True
        with self._lock:
            now = time.monotonic()
            if now - self._last < self.interval:
                return False
            self._last = now
            return True


def _traces_url(endpoint: str) -> str:
    return endpoint.rstrip("/") + "/v1/traces"


def setup_telemetry(
    app: FastAPI, settings: Settings, span_exporter: SpanExporter | None = None
) -> TracerProvider | None:
    """Trace requests to ``app``; returns the provider, or ``None`` when tracing is off.

    ``span_exporter`` replaces the OTLP exporter, for tests with an in-memory one.
    """
    if span_exporter is None and not settings.otlp_endpoint:
        return None
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment": settings.deployment_environment,
            }
        )
    )
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    else:
        throttle = OncePerMinute()
        for name in EXPORT_LOGGERS:
            logging.getLogger(name).addFilter(throttle)
        # The endpoint comes from OTEL_EXPORTER_OTLP_ENDPOINT, which the exporter reads itself.
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=_traces_url(settings.otlp_endpoint or ""), timeout=3)
            )
        )
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls=EXCLUDED_URLS)
    app.state.tracer_provider = provider
    return provider

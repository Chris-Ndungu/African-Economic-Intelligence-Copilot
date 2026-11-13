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
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from sqlalchemy import Engine
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.logging_config import LOGGERS, RedactFilter
from backend.settings import Settings
from copilot_core.telemetry import tracer_provider_var

EXCLUDED_URLS = "/health,/otlp/"
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


class TracerProviderMiddleware:
    """Makes this app's tracer provider the one ``copilot_core`` spans use for the request.

    ``copilot_core`` only knows the OpenTelemetry API; this is how it reaches
    the app's SDK provider without a process-wide global, so several apps (as
    in tests) each keep their own spans.
    """

    def __init__(self, app: ASGIApp, provider: TracerProvider) -> None:
        self.app = app
        self.provider = provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = tracer_provider_var.set(self.provider)
        try:
            await self.app(scope, receive, send)
        finally:
            tracer_provider_var.reset(token)


def _traces_url(endpoint: str) -> str:
    return endpoint.rstrip("/") + "/v1/traces"


def _export_logs(resource: Resource, settings: Settings) -> None:
    """Also send the application's logs over OTLP, so Grafana links a line to its trace."""
    endpoint = (settings.otlp_endpoint or "").rstrip("/") + "/v1/logs"
    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, timeout=3))
    )
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logs)
    handler.addFilter(RedactFilter())
    for name in LOGGERS:
        logging.getLogger(name).addHandler(handler)


def _export_metrics(resource: Resource, settings: Settings) -> None:
    """Export the metrics of ``copilot_core.telemetry`` over OTLP every 10 seconds."""
    endpoint = (settings.otlp_endpoint or "").rstrip("/") + "/v1/metrics"
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, timeout=3), export_interval_millis=10_000
    )
    # Only the first provider set in a process counts; later calls are ignored.
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))


def instrument_engine(app: FastAPI, engine: Engine) -> None:
    """Trace the SQL of ``engine`` when tracing is on. Statements keep their placeholders."""
    provider = getattr(app.state, "tracer_provider", None)
    if provider is not None:
        # SQLAlchemy 2.1 is newer than the range the instrumentor declares; its engine events are unchanged.
        SQLAlchemyInstrumentor().instrument(
            engine=engine, tracer_provider=provider, skip_dep_check=True
        )


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
        _export_logs(provider.resource, settings)
        _export_metrics(provider.resource, settings)
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=_traces_url(settings.otlp_endpoint or ""), timeout=3)
            )
        )
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls=EXCLUDED_URLS)
    app.state.tracer_provider = provider
    app.add_middleware(TracerProviderMiddleware, provider=provider)
    return provider

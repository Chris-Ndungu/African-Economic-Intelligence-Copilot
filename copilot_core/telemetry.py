"""Telemetry helpers that use only the OpenTelemetry API, never the SDK.

Without an SDK configured (tests, plain ``uvicorn``) every call here does
nothing. Nothing here takes a question, a prompt, a credential or a connection
string: :func:`safe_attributes` drops any attribute named like one, so a span
attribute or log field cannot carry them by accident. Metric labels have a
small, fixed set of values; never an ID, an IP address or user text.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.trace import Span, Status, StatusCode

__all__ = [
    "annotate",
    "current_investigation_id",
    "investigation_id_var",
    "is_sensitive",
    "record_claims",
    "record_investigation",
    "record_llm_call",
    "record_rate_limit_hit",
    "safe_attributes",
    "span",
    "tracer_provider_var",
]

_SENSITIVE = re.compile(
    r"(^|[._\- ])(question|prompt|api[_-]?key|password|passwd|token|authorization|"
    r"database[_-]?url|secret|cookie)([._\- ]|$)",
    re.IGNORECASE,
)

investigation_id_var: ContextVar[str | None] = ContextVar("investigation_id", default=None)
"""The investigation a log line belongs to, set for the duration of a run."""

tracer_provider_var: ContextVar[trace.TracerProvider | None] = ContextVar(
    "tracer_provider", default=None
)
"""The provider of the app serving this request, set by the API; else the global one."""

_meter = metrics.get_meter("copilot")
_rate_limit_hits = _meter.create_counter(
    "rate_limit_hits_total",
    description="Runs refused because a rate limit was reached",
)

# Buckets reach past the 90-second run limit. No metric has an unbounded label:
# outcomes are a fixed set of codes, models a handful of names.
_investigations = _meter.create_counter(
    "investigations_total", description="Investigation runs by outcome"
)
_investigation_seconds = _meter.create_histogram(
    "investigation_duration_seconds",
    description="End-to-end duration of an investigation run, in seconds",
    explicit_bucket_boundaries_advisory=[1, 2.5, 5, 10, 20, 30, 45, 60, 90, 120, 180],
)
_llm_seconds = _meter.create_histogram(
    "llm_request_duration_seconds",
    description="Duration of one Gemini call, in seconds",
    explicit_bucket_boundaries_advisory=[0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60],
)
_llm_tokens = _meter.create_counter("llm_tokens_total", description="Gemini tokens used")
_claims = _meter.create_counter("claims_total", description="Claims checked against tool results")


def record_investigation(outcome: str, seconds: float) -> None:
    """Count a finished run; ``outcome`` is ``succeeded``, ``unsupported`` or an error code."""
    _investigations.add(1, {"outcome": outcome})
    _investigation_seconds.record(seconds, {"outcome": outcome})


def record_llm_call(model: str, seconds: float, input_tokens: int, output_tokens: int) -> None:
    _llm_seconds.record(seconds, {"model": model})
    _llm_tokens.add(input_tokens, {"type": "input", "model": model})
    _llm_tokens.add(output_tokens, {"type": "output", "model": model})


def record_claims(verified: int, unverified: int) -> None:
    _claims.add(verified, {"verified": "true"})
    _claims.add(unverified, {"verified": "false"})


def is_sensitive(name: str) -> bool:
    """Whether a field or attribute name says it holds a question, prompt or credential."""
    return _SENSITIVE.search(name) is not None


def safe_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """The attributes without sensitive names and without ``None`` values."""
    return {k: v for k, v in attributes.items() if v is not None and not is_sensitive(k)}


def current_investigation_id() -> str | None:
    return investigation_id_var.get()


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Span]:
    """A span that is current inside the block.

    An exception that leaves the block sets the status to error and records
    the exception type and, when it has one, its ``code``. The message is never
    recorded, because it may contain user input.
    """
    tracer = trace.get_tracer("copilot", tracer_provider=tracer_provider_var.get())
    with tracer.start_as_current_span(
        name,
        attributes=safe_attributes(attributes),
        record_exception=False,
        set_status_on_exception=False,
    ) as current:
        try:
            yield current
        except BaseException as exc:
            fail_span(current, type(exc).__name__, getattr(exc, "code", None))
            raise


def fail_span(current: Span, error_type: str, code: str | None = None) -> None:
    """Mark a span as failed with the error type and code, never a message."""
    current.set_status(Status(StatusCode.ERROR, error_type))
    current.set_attribute("error.type", error_type)
    if isinstance(code, str):
        current.set_attribute("error.code", code)


def annotate(**attributes: Any) -> None:
    """Add attributes to the current span."""
    current = trace.get_current_span()
    if current.is_recording():
        current.set_attributes(safe_attributes(attributes))


def record_rate_limit_hit(limit: str) -> None:
    """Count a refused run; ``limit`` is ``client`` or ``daily``."""
    _rate_limit_hits.add(1, {"limit": limit})

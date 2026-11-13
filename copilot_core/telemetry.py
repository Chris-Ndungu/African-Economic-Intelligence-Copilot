"""Telemetry helpers that use only the OpenTelemetry API, never the SDK.

Without an SDK configured (tests, plain ``uvicorn``) every call here does
nothing. Metric labels have a small, fixed set of values; nothing here takes
a question, an ID, an IP address or any other user data.
"""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("copilot")
_rate_limit_hits = _meter.create_counter(
    "rate_limit_hits_total",
    description="Runs refused because a rate limit was reached",
)


def record_rate_limit_hit(limit: str) -> None:
    """Count a refused run; ``limit`` is ``client`` or ``daily``."""
    _rate_limit_hits.add(1, {"limit": limit})

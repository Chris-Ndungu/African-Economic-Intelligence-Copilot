"""W3C trace context for the browser-to-server trace (#44).

The run request carries a ``traceparent`` header. ``EventSource`` cannot send
headers, so the progress stream URL carries the trace context as a
``traceparent`` query parameter, which the stream route checks against the W3C
format before using it. A missing or malformed value is not an error: the run
simply starts a new trace.
"""

import re

from opentelemetry import context, trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


def valid_traceparent(value: str | None) -> str | None:
    """``value`` if it is a version-00 ``traceparent`` with non-zero IDs, else ``None``."""
    if not value:
        return None
    match = _TRACEPARENT.fullmatch(value)
    if match is None or set(match.group(1)) == {"0"} or set(match.group(2)) == {"0"}:
        return None
    return value


def current_traceparent(incoming: str | None = None) -> str | None:
    """The trace context to hand to the progress stream.

    The current span's, when tracing is on; otherwise the validated incoming
    header, so the browser's trace ID survives either way.
    """
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        return f"00-{span_context.trace_id:032x}-{span_context.span_id:016x}-01"
    return valid_traceparent(incoming)


def adopt_traceparent(value: str | None) -> bool:
    """Make a valid ``traceparent`` the parent of the spans created from here on.

    The context stays attached for the rest of the request's task, which is
    what a streamed response needs; it is gone when the request ends.
    """
    checked = valid_traceparent(value)
    if checked is None:
        return False
    extracted = TraceContextTextMapPropagator().extract({"traceparent": checked})
    context.attach(extracted)
    return True

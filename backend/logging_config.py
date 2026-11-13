"""Single-line JSON logs on stdout, tied to the current trace.

Every line has ``timestamp``, ``level``, ``logger``, ``message``, ``trace_id``,
``span_id`` and, where known, ``investigation_id``. Only a short list of extra
fields is ever written (``EXTRA_FIELDS``), so a log call cannot put a question
or a credential in a line by passing it as ``extra``; fields named like a
secret are dropped as well. Uvicorn's access lines lose the client address,
which is personal data, and the query string. An exception is logged as its
type only, because its message may contain user input.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from opentelemetry import trace

from copilot_core.telemetry import current_investigation_id, is_sensitive

EXTRA_FIELDS = ("investigation_id", "outcome", "error_code", "data_mode", "tool")
LOGGERS = ("backend", "copilot_core", "uvicorn", "uvicorn.error", "uvicorn.access")
_MARK = "_copilot_json_handler"


class RedactFilter(logging.Filter):
    """Removes any field named like a secret from a record before it is written."""

    def filter(self, record: logging.LogRecord) -> bool:
        for name in [n for n in vars(record) if is_sensitive(n)]:
            delattr(record, name)
        return True


def _message(record: logging.LogRecord) -> str:
    if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
        _client, method, path, version, status = record.args
        return f"{method} {str(path).split('?', 1)[0]} HTTP/{version} {status}"
    return record.getMessage()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = trace.get_current_span().get_span_context()
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _message(record),
            "trace_id": format(context.trace_id, "032x") if context.is_valid else None,
            "span_id": format(context.span_id, "016x") if context.is_valid else None,
            "investigation_id": getattr(record, "investigation_id", None)
            or current_investigation_id(),
        }
        for field in EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None and field not in payload and not is_sensitive(field):
                payload[field] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Send the application's and Uvicorn's logs to stdout as JSON; safe to call twice."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactFilter())
    setattr(handler, _MARK, True)
    for name in LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = [h for h in logger.handlers if getattr(h, _MARK, False) is False][:0]
        logger.addHandler(handler)
        if name in ("backend", "copilot_core"):
            logger.setLevel(level.upper())
        elif logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)

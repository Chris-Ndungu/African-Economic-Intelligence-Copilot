"""Same-origin forwarding of the browser's spans to the OTLP collector (#44).

The browser never learns the collector's address or any credential: it posts
its span to ``/otlp/v1/traces`` and this route forwards it, adding the
configured auth headers on the server. Not part of the OpenAPI contract, and
not traced itself, so forwarding cannot create a loop of spans.
"""

import json
import logging
import urllib.request
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool

from backend.settings import Settings

logger = logging.getLogger("backend.otlp")

MAX_BODY_BYTES = 1_000_000
router = APIRouter(include_in_schema=False)


def forward_traces(endpoint: str, headers: dict[str, str], body: bytes) -> None:
    """POST ``body`` to the collector. Raises on failure; the caller drops the data."""
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/traces",
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3):  # noqa: S310 - the endpoint is configuration
        pass


def parse_headers(raw: str | None) -> dict[str, str]:
    """``key=value,key2=value2`` as in ``OTEL_EXPORTER_OTLP_HEADERS``."""
    pairs = (item.split("=", 1) for item in (raw or "").split(",") if "=" in item)
    return {key.strip(): value.strip() for key, value in pairs if key.strip()}


async def _read_limited(request: Request) -> bytes | None:
    """The body, or ``None`` once it is over the limit."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return None
    return bytes(body)


@router.post("/otlp/v1/traces")
async def receive_traces(request: Request) -> Response:
    """Forward a browser span: ``413`` over 1 MB, ``204`` when nothing is configured."""
    body = await _read_limited(request)
    if body is None:
        return Response(status_code=413)
    settings: Settings = request.app.state.settings
    if not settings.otlp_endpoint:
        return Response(status_code=204)
    try:
        document: Any = json.loads(body)
        if not isinstance(document, dict) or not isinstance(document.get("resourceSpans"), list):
            return Response(status_code=204)  # not an OTLP trace: drop it
        headers = parse_headers(
            settings.otlp_headers.get_secret_value() if settings.otlp_headers else None
        )
        await run_in_threadpool(forward_traces, settings.otlp_endpoint, headers, body)
    except Exception as exc:  # the page must work when the collector does not
        logger.debug("browser span not forwarded: %s", type(exc).__name__)
    return Response(status_code=204)

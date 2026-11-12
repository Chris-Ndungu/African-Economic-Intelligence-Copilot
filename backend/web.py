"""HTML routes: server-rendered Jinja pages and HTMX partials.

These routes are outside the OpenAPI contract, so the router is registered
with `include_in_schema=False`. Like the JSON routes they stay thin: read
input, call `copilot_core`, render a template. They never call the JSON API
over HTTP.

- Full pages: `GET /` (and `GET /investigations/{id}`, added in #23)
- HTMX fragments: under `/partials/...`
- Static files: served at `/static/...` from `backend/static/`
"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from backend.api import EventStreamResponse
from backend.dependencies import get_data_service, get_investigation_service, get_repository
from copilot_core.data import DataError, DataService, DataUnavailableError
from copilot_core.events import FailedEvent, Heartbeat, InProgressEvent, ProgressEvent, SavedEvent
from copilot_core.findings_view import build_results_view
from copilot_core.formatting import format_number
from copilot_core.history import HistoryEntry, load_history
from copilot_core.investigation import run_trend_investigation
from copilot_core.models import SeriesResult
from copilot_core.progress import build_run_request, describe_event, rerun_request
from copilot_core.repository import (
    DatabaseUnavailableError,
    InvestigationNotFoundError,
    RepositoryError,
)
from copilot_core.schemas import MAX_QUESTION_LENGTH, InvestigationCreate
from copilot_core.selection import (
    MAX_COUNTRIES,
    SelectionPanel,
    SubmittedSelection,
    build_selection_panel,
    submitted_from_form,
)

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"

# The vendored HTMX file, pinned to an exact release. See
# backend/static/vendor/README.md for its source URL and SHA-256.
HTMX_FILE = "vendor/htmx-2.0.11.min.js"
PLOTLY_FILE = "vendor/plotly-basic-2.35.2.min.js"
SSE_FILE = "vendor/htmx-ext-sse-2.2.2.js"

# Jinja2Templates turns autoescaping on for `.html` templates, so any value
# a page renders is escaped unless a template marks it safe.
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["htmx_file"] = HTMX_FILE
templates.env.globals["plotly_file"] = PLOTLY_FILE
templates.env.globals["sse_file"] = SSE_FILE
templates.env.globals["max_question_length"] = MAX_QUESTION_LENGTH
templates.env.globals["max_question_text"] = f"{MAX_QUESTION_LENGTH:,}"
templates.env.filters["number"] = format_number
templates.env.globals["results_view"] = build_results_view

router = APIRouter(include_in_schema=False)

CHART_WIDTH, CHART_HEIGHT, CHART_PAD = 640, 240, 24


def chart_points(series: SeriesResult) -> list[list[tuple[float, float]]]:
    """SVG coordinates of the series, one line per run of non-missing values.

    A missing value breaks the line rather than being drawn as zero.
    """
    values = [p.value for p in series.points]
    present = [v for v in values if v is not None]
    if not present:
        return []
    low, high = min(present), max(present)
    spread = (high - low) or 1.0
    step = (CHART_WIDTH - 2 * CHART_PAD) / max(len(values) - 1, 1)
    lines: list[list[tuple[float, float]]] = [[]]
    for index, value in enumerate(values):
        if value is None:
            if lines[-1]:
                lines.append([])
            continue
        x = CHART_PAD + index * step
        y = CHART_HEIGHT - CHART_PAD - (value - low) / spread * (CHART_HEIGHT - 2 * CHART_PAD)
        lines[-1].append((round(x, 1), round(y, 1)))
    return [line for line in lines if line]


def _get_data(request: Request) -> DataService | None:
    try:
        return get_data_service(request)
    except DataUnavailableError:
        return None


def _panel(request: Request, submitted: SubmittedSelection) -> SelectionPanel | None:
    """The panel state, or ``None`` when the data service cannot be read."""
    data = _get_data(request)
    if data is None:
        return None
    try:
        return build_selection_panel(
            data.list_countries(), data.list_indicators(), data.list_coverage(), submitted
        )
    except DataUnavailableError:
        return None


def _render_panel(
    request: Request,
    name: str,
    submitted: SubmittedSelection,
    extra: dict[str, object],
    status_code: int = 200,
) -> HTMLResponse:
    context = {
        "panel": _panel(request, submitted),
        "max_countries": MAX_COUNTRIES,
        "question": "",
        "hint": None,
        **extra,
    }
    response = templates.TemplateResponse(request, name, context, status_code=status_code)
    response.headers["Vary"] = "HX-Request"
    return response


@dataclass
class HistoryState:
    """What the history partials print: a page of entries or an error."""

    entries: list[HistoryEntry] = field(default_factory=list)
    next_cursor: str | None = None
    error: str | None = None


def _history(request: Request, cursor: str | None = None) -> HistoryState:
    try:
        page = load_history(get_repository(request), cursor=cursor)
    except DatabaseUnavailableError:
        return HistoryState(error="The history could not be loaded: the database is unavailable.")
    except RepositoryError:
        return HistoryState(error="The history could not be loaded.")
    except ValueError:
        return HistoryState(error="The next page could not be loaded.")
    return HistoryState(page.entries, page.next_cursor)


@router.get("/", response_class=HTMLResponse)
def workspace(request: Request) -> HTMLResponse:
    """The workspace: the selection panel, the history and the results area."""
    return _render_panel(
        request, "pages/workspace.html", SubmittedSelection(), {"history": _history(request)}
    )


@router.get("/partials/history", response_class=HTMLResponse)
def history_partial(
    request: Request,
    cursor: Annotated[str | None, Query()] = None,
    active: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """The history list, or with ``cursor`` the next page of its items.

    Errors answer ``200`` so HTMX swaps the message and its Retry button in.
    """
    history = _history(request, cursor)
    context: dict[str, object] = {"history": history, "active": active, "cursor": cursor or ""}
    if cursor is None:
        return templates.TemplateResponse(request, "partials/history.html", context)
    context["oob"] = True
    return templates.TemplateResponse(request, "partials/history_page.html", context)


def _is_fragment_request(request: Request) -> bool:
    """HTMX asks for the main panel only; a history restore needs the whole page."""
    headers = request.headers
    return (
        headers.get("hx-request") == "true" and headers.get("hx-history-restore-request") != "true"
    )


@router.get("/investigations/{investigation_id}", response_class=HTMLResponse)
def investigation_page(request: Request, investigation_id: str) -> HTMLResponse:
    """A saved investigation: the full page, or the main panel for an HTMX request."""
    state, status_code, investigation = "found", 200, None
    try:
        parsed = uuid.UUID(investigation_id)
        investigation = get_repository(request).get(parsed)
    except (ValueError, InvestigationNotFoundError):
        state, status_code = "not_found", 404
    except RepositoryError:
        state, status_code = "unavailable", 503
    context: dict[str, object] = {
        "state": state,
        "investigation": investigation,
        "investigation_id": investigation_id,
        "title": investigation.title if investigation else "Not found",
        "active": str(investigation.id) if investigation else "",
    }
    if _is_fragment_request(request):
        response = templates.TemplateResponse(
            request, "partials/investigation_panel.html", context, status_code=status_code
        )
        response.headers["Vary"] = "HX-Request"
        return response
    context["history"] = _history(request)
    return _render_panel(
        request, "pages/investigation.html", SubmittedSelection(), context, status_code
    )


@router.post("/partials/selection", response_class=HTMLResponse)
async def selection_partial(request: Request) -> HTMLResponse:
    """The selection panel for the submitted form values.

    The form is URL-encoded and parsed with the standard library. The state
    comes from `copilot_core.selection`, not from the JSON API.
    """
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    submitted = submitted_from_form(form)
    return await run_in_threadpool(_render_panel, request, "partials/selection.html", submitted, {})


@router.get("/partials/trend", response_class=HTMLResponse)
def trend_partial(
    request: Request,
    data: Annotated[DataService, Depends(get_data_service)],
    country: Annotated[str, Query()],
    indicator: Annotated[str, Query()],
    start: Annotated[str, Query()],
    end: Annotated[str, Query()],
) -> HTMLResponse:
    """The trend of one series, its chart and a button to save it."""
    try:
        investigation = run_trend_investigation(data, country, indicator, start, end)
    except DataError as exc:
        return _message(request, str(exc), 422)
    return templates.TemplateResponse(
        request,
        "partials/trend.html",
        {
            "investigation": investigation,
            "lines": chart_points(investigation.series),
            "chart": {"width": CHART_WIDTH, "height": CHART_HEIGHT},
            "selection": {"country": country, "indicator": indicator, "start": start, "end": end},
        },
    )


@router.post("/partials/investigations", response_class=HTMLResponse)
async def save_partial(
    request: Request, data: Annotated[DataService, Depends(get_data_service)]
) -> HTMLResponse:
    """Save the trend investigation for a selection.

    The result is computed again here from the selection rather than taken
    from the page, so only numbers computed in Python are saved. The form
    is URL-encoded and parsed with the standard library.
    """
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    missing = [f for f in ("title", "country", "indicator", "start", "end") if not form.get(f)]
    if missing:
        return _message(request, f"Missing fields: {', '.join(missing)}.", 422)
    return await run_in_threadpool(_save, request, data, form)


def _save(request: Request, data: DataService, form: dict[str, str]) -> HTMLResponse:
    try:
        investigation = run_trend_investigation(
            data, form["country"], form["indicator"], form["start"], form["end"]
        )
        body = InvestigationCreate(
            title=form["title"][:200],
            status="succeeded",
            request=investigation.result.request,
            result=investigation.result,
        )
        saved = get_repository(request).create(body, data_mode=body.result.data_mode)
    except DataError as exc:
        return _message(request, str(exc), 422)
    except RepositoryError:
        message = "The investigation could not be saved: the database is unavailable."
        return _message(request, message, 503)
    return templates.TemplateResponse(request, "partials/saved.html", {"investigation": saved})


def _message(request: Request, message: str, status_code: int) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/message.html", {"message": message}, status_code=status_code
    )


# --- Starting a run and watching its progress (#30) --------------------------------


def _form_fields(body: bytes) -> tuple[str, SubmittedSelection]:
    form = parse_qs(body.decode(), keep_blank_values=True)
    question = form.get("question", [""])[0]
    return question, submitted_from_form(form)


def _run_form_response(
    request: Request, question: str, submitted: SubmittedSelection, hint: str
) -> HTMLResponse:
    """The run form again with a hint; HTMX swaps it in place of the form."""
    response = _render_panel(
        request,
        "partials/run_form.html",
        submitted,
        {"question": question, "hint": hint},
    )
    response.headers["HX-Retarget"] = "#run-form"
    response.headers["HX-Reswap"] = "outerHTML"
    return response


def _progress_page(request: Request, investigation_id: uuid.UUID) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/run_progress.html", {"investigation_id": investigation_id}
    )


def _start(request: Request, question: str, submitted: SubmittedSelection) -> HTMLResponse:
    panel = _panel(request, submitted)
    form = build_run_request(question, panel.selection if panel else None)
    if form.body is None:
        return _run_form_response(request, form.question, submitted, form.hint or "")
    try:
        created = get_investigation_service(request).create(form.body)
    except RepositoryError:
        hint = "The investigation could not be started: the database is unavailable."
        return _run_form_response(request, form.question, submitted, hint)
    return _progress_page(request, created.id)


@router.post("/partials/investigations/run", response_class=HTMLResponse)
async def run_partial(request: Request) -> HTMLResponse:
    """Create a pending investigation from the run form and return its progress partial.

    The form is URL-encoded and parsed with the standard library. The stream
    URL carries only the ID, never the question.
    """
    question, submitted = _form_fields(await request.body())
    return await run_in_threadpool(_start, request, question, submitted)


def _retry(request: Request, investigation_id: str) -> HTMLResponse:
    try:
        failed = get_repository(request).get(uuid.UUID(investigation_id))
    except (ValueError, InvestigationNotFoundError):
        return _message(request, "That investigation no longer exists.", 404)
    except RepositoryError:
        return _message(request, "The database is unavailable. Try again shortly.", 503)
    run = failed.run
    if run is None or (run.question is None and run.selection is None):
        return _message(request, "That investigation has no input to run again.", 422)
    body = rerun_request(run.question, run.selection)
    try:
        created = get_investigation_service(request).create(body)
    except RepositoryError:
        return _message(request, "The database is unavailable. Try again shortly.", 503)
    return _progress_page(request, created.id)


@router.post("/partials/investigations/{investigation_id}/retry", response_class=HTMLResponse)
async def retry_partial(request: Request, investigation_id: str) -> HTMLResponse:
    """Run a failed investigation's question and selection again as a new run."""
    return await run_in_threadpool(_retry, request, investigation_id)


def sse_frame(event: str, html: str = "") -> str:
    """One server-sent event whose data is ``html``, one ``data:`` line per line."""
    lines = html.strip().splitlines() or [""]
    return f"event: {event}\n" + "".join(f"data: {line}\n" for line in lines) + "\n"


def _render(name: str, **context: object) -> str:
    return templates.get_template(name).render(**context)


def _outcome(kind: str, **context: object) -> str:
    return sse_frame("outcome", _render("partials/run_outcome.html", kind=kind, **context))


async def progress_html(events: AsyncGenerator[ProgressEvent | Heartbeat]) -> AsyncIterator[str]:
    """The run's events as HTML fragments: steps, pings and one final outcome.

    The stream ends with a ``close`` event, which the HTMX SSE extension
    uses (``sse-close``) to close the connection. Closing this iterator
    closes the run's iterator, which cancels a run still going.
    """
    async with aclosing(events):
        async for event in events:
            if isinstance(event, Heartbeat):
                yield sse_frame("ping")
            elif isinstance(event, SavedEvent):
                yield _outcome("saved", investigation_id=event.investigation_id)
                yield sse_frame("close")
            elif isinstance(event, FailedEvent):
                yield _outcome(
                    "failed",
                    investigation_id=event.investigation_id,
                    code=event.code,
                    message=event.message,
                )
                yield sse_frame("close")
            elif isinstance(event, InProgressEvent):
                yield _outcome("in_progress", investigation_id=event.investigation_id)
                yield sse_frame("close")
            elif (step := describe_event(event)) is not None:
                yield sse_frame("step", _render("partials/run_step.html", step=step))


async def _only_outcome(kind: str) -> AsyncIterator[str]:
    yield _outcome(kind)
    yield sse_frame("close")


@router.get("/partials/investigations/{investigation_id}/progress")
async def progress_stream(request: Request, investigation_id: str) -> StreamingResponse:
    """Run a pending investigation and stream its progress as HTML fragments.

    A thin route over the same iterator as the JSON stream: it claims the
    run, sends keep-alive pings and, for a finished run, only its final event.
    An unknown ID or an unavailable database is answered inside the stream
    with ``200``, so the browser shows the message instead of reconnecting.
    """
    try:
        runs = get_investigation_service(request)
        investigation = await run_in_threadpool(runs.get, uuid.UUID(investigation_id))
    except (ValueError, InvestigationNotFoundError):
        return EventStreamResponse(_only_outcome("not_found"))
    except RepositoryError:
        return EventStreamResponse(_only_outcome("unavailable"))
    return EventStreamResponse(progress_html(runs.stream(investigation)))

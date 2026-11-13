"""JSON API routes described by ``api/openapi.yaml``.

Each route validates input, calls ``copilot_core`` and returns the result.
There is no SQL and no analysis here.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic.json_schema import SkipJsonSchema

from backend.dependencies import (
    enforce_run_limit,
    get_app_meta,
    get_data_service,
    get_investigation_service,
    get_repository,
)
from backend.errors import RunFailedError, json_responses, responses
from copilot_core.data import DataService
from copilot_core.events import Heartbeat, ProgressEvent
from copilot_core.models import CountryCode, IndicatorCode
from copilot_core.report import render_report_pdf, report_filename
from copilot_core.repository import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, InvestigationRepository
from copilot_core.runs import InvestigationService
from copilot_core.schemas import (
    CountryList,
    Coverage,
    IndicatorList,
    Investigation,
    InvestigationCreate,
    InvestigationList,
    InvestigationRunAccepted,
    InvestigationRunRequest,
    InvestigationUpdate,
    Meta,
)

DATA_MODE = "demo"  # Live mode on BigQuery arrives with #49.

router = APIRouter(prefix="/api")

Data = Annotated[DataService, Depends(get_data_service)]
Repository = Annotated[InvestigationRepository, Depends(get_repository)]


def service(request: Request) -> InvestigationService:
    """The run service, built after the body is validated so `422` comes before `503`."""
    return get_investigation_service(request)


class PdfResponse(Response):
    media_type = "application/pdf"


class EventStreamResponse(StreamingResponse):
    """A server-sent event stream that proxies must not buffer or cache."""

    media_type = "text/event-stream"

    def __init__(self, content: AsyncIterator[str], status_code: int = 200) -> None:
        super().__init__(
            content,
            status_code=status_code,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


async def server_sent_events(
    events: AsyncIterator[ProgressEvent | Heartbeat],
) -> AsyncIterator[str]:
    """Each event as ``id``, ``event`` and ``data`` lines; a heartbeat as ``: ping``."""
    number = 0
    async for event in events:
        if isinstance(event, Heartbeat):
            yield ": ping\n\n"
            continue
        number += 1
        yield f"id: {number}\nevent: {event.event}\ndata: {event.model_dump_json()}\n\n"


@router.get("/meta", tags=["health"], operation_id="getMeta")
def get_meta(request: Request) -> Meta:
    """The data mode, the demo snapshot date and whether Gemini is configured."""
    return get_app_meta(request)


@router.get(
    "/countries",
    tags=["reference"],
    operation_id="listCountries",
    responses=responses(500, 503),
)
def list_countries(data: Data) -> CountryList:
    """Lists the countries present in the active data source."""
    return CountryList(data_mode=DATA_MODE, countries=data.list_countries())


@router.get(
    "/indicators",
    tags=["reference"],
    operation_id="listIndicators",
    responses=responses(500, 503),
)
def list_indicators(data: Data) -> IndicatorList:
    """Lists the supported indicators with their units and frequency."""
    return IndicatorList(data_mode=DATA_MODE, indicators=data.list_indicators())


@router.get(
    "/coverage",
    tags=["reference"],
    operation_id="getCoverage",
    responses=responses(422, 500, 503),
)
def get_coverage(
    data: Data,
    country: Annotated[list[CountryCode] | SkipJsonSchema[None], Query()] = None,
    indicator: Annotated[list[IndicatorCode] | SkipJsonSchema[None], Query()] = None,
) -> Coverage:
    """Periods covered and missing per country and indicator."""
    return Coverage(data_mode=DATA_MODE, entries=data.list_coverage(country, indicator))


@router.get(
    "/investigations",
    tags=["investigations"],
    operation_id="listInvestigations",
    responses=responses(422, 500, 503),
)
def list_investigations(
    repository: Repository,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | SkipJsonSchema[None], Query()] = None,
) -> InvestigationList:
    """Saved investigations, newest first."""
    page = repository.list(limit=limit, cursor=cursor)
    return InvestigationList(
        data_mode=DATA_MODE, items=page.items, limit=page.limit, next_cursor=page.next_cursor
    )


@router.post(
    "/investigations",
    tags=["investigations"],
    operation_id="saveInvestigation",
    status_code=status.HTTP_201_CREATED,
    responses=responses(409, 422, 500, 503),
)
def save_investigation(
    body: InvestigationCreate, repository: Repository, response: Response
) -> Investigation:
    """Saves an investigation request and its result. Status defaults to `succeeded`."""
    saved = repository.create(body, data_mode=body.result.data_mode, status="succeeded")
    response.headers["Location"] = f"/api/investigations/{saved.id}"
    return saved


@router.post(
    "/investigations/run",
    tags=["investigations"],
    operation_id="runInvestigation",
    responses=responses(409, 422, 429, 500, 503),
)
async def run_investigation(body: InvestigationRunRequest, request: Request) -> Investigation:
    """Runs an investigation inside the request and returns it saved as `succeeded`."""
    runs = service(request)
    await run_in_threadpool(enforce_run_limit, request)
    investigation = await runs.run_new(body)
    if investigation.status != "succeeded":
        raise RunFailedError(investigation)
    return investigation


@router.post(
    "/investigations/runs",
    tags=["investigations"],
    operation_id="createInvestigationRun",
    status_code=status.HTTP_202_ACCEPTED,
    responses=responses(409, 422, 429, 500, 503),
)
def create_investigation_run(
    body: InvestigationRunRequest, request: Request, response: Response
) -> InvestigationRunAccepted:
    """Saves an investigation as `pending`; its event stream runs it."""
    runs = service(request)
    enforce_run_limit(request)
    investigation = runs.create(body)
    events_url = f"/api/investigations/{investigation.id}/events"
    response.headers["Location"] = events_url
    return InvestigationRunAccepted(id=investigation.id, status="pending", events_url=events_url)


@router.get(
    "/investigations/{investigation_id}/events",
    tags=["investigations"],
    operation_id="streamInvestigationEvents",
    response_class=EventStreamResponse,
    responses=json_responses(404, 422, 500, 503),
)
async def stream_investigation_events(
    investigation_id: uuid.UUID, request: Request
) -> EventStreamResponse:
    """Runs a pending investigation and streams its progress as server-sent events."""
    runs = service(request)
    investigation = await run_in_threadpool(runs.get, investigation_id)
    return EventStreamResponse(server_sent_events(runs.stream(investigation)))


@router.get(
    "/investigations/{investigation_id}",
    tags=["investigations"],
    operation_id="getInvestigation",
    responses=responses(404, 422, 500, 503),
)
def get_investigation(investigation_id: uuid.UUID, repository: Repository) -> Investigation:
    """Returns a saved investigation with its request and result."""
    return repository.get(investigation_id)


@router.get(
    "/investigations/{investigation_id}/report",
    tags=["investigations"],
    operation_id="exportInvestigationPdf",
    response_class=PdfResponse,
    responses={
        200: {
            "description": "The PDF report.",
            "content": {"application/pdf": {"schema": {"type": "string"}}},
            "headers": {
                "X-Data-Mode": {"schema": {"type": "string"}},
                "Content-Disposition": {"schema": {"type": "string"}},
            },
        },
        **json_responses(404, 409, 422, 500, 503),
    },
)
def export_investigation_pdf(
    investigation_id: uuid.UUID, request: Request, repository: Repository
) -> Response:
    """Renders a saved, succeeded investigation as PDF without calling Gemini."""
    investigation = repository.get(investigation_id)
    pdf = render_report_pdf(
        investigation,
        snapshot_date=get_app_meta(request).snapshot_date,
    )
    return PdfResponse(
        pdf,
        headers={
            "Content-Disposition": f'attachment; filename="{report_filename(investigation)}"',
            "X-Data-Mode": investigation.data_mode,
        },
    )


@router.patch(
    "/investigations/{investigation_id}",
    tags=["investigations"],
    operation_id="updateInvestigation",
    responses=responses(404, 422, 500, 503),
)
def update_investigation(
    investigation_id: uuid.UUID, body: InvestigationUpdate, repository: Repository
) -> Investigation:
    """Updates the fields given; fields left out keep their values."""
    return repository.update(investigation_id, body)

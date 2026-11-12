"""JSON API routes described by ``api/openapi.yaml``.

Each route validates input, calls ``copilot_core`` and returns the result.
There is no SQL and no analysis here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic.json_schema import SkipJsonSchema

from backend.dependencies import get_data_service, get_repository
from backend.errors import responses
from copilot_core.data import DataService
from copilot_core.models import CountryCode, IndicatorCode
from copilot_core.repository import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, InvestigationRepository
from copilot_core.schemas import (
    CountryList,
    Coverage,
    IndicatorList,
    Investigation,
    InvestigationCreate,
    InvestigationList,
    InvestigationUpdate,
)

DATA_MODE = "demo"  # Live mode on BigQuery arrives with #49.

router = APIRouter(prefix="/api")

Data = Annotated[DataService, Depends(get_data_service)]
Repository = Annotated[InvestigationRepository, Depends(get_repository)]


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
    responses=responses(422, 500, 503),
)
def save_investigation(
    body: InvestigationCreate, repository: Repository, response: Response
) -> Investigation:
    """Saves an investigation request and its result. Status defaults to `succeeded`."""
    saved = repository.create(body, data_mode=body.result.data_mode, status="succeeded")
    response.headers["Location"] = f"/api/investigations/{saved.id}"
    return saved


@router.get(
    "/investigations/{investigation_id}",
    tags=["investigations"],
    operation_id="getInvestigation",
    responses=responses(404, 422, 500, 503),
)
def get_investigation(investigation_id: uuid.UUID, repository: Repository) -> Investigation:
    """Returns a saved investigation with its request and result."""
    return repository.get(investigation_id)


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

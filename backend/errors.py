"""Turn errors into the contract's shared ``Error`` body.

Every 4xx and 5xx from the JSON API uses ``ErrorBody``. An unavailable data
service or database answers ``503`` and names the service; the process keeps
running.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from copilot_core.analysis import AnalysisError
from copilot_core.data import DataUnavailableError, InvalidRequestError
from copilot_core.repository import (
    DatabaseUnavailableError,
    InvalidCursorError,
    InvalidStatusTransitionError,
    InvestigationNotFoundError,
)
from copilot_core.schemas import ErrorBody, ErrorDetail

logger = logging.getLogger("backend.errors")

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorBody, "description": description}
    for code, description in {
        404: "No saved investigation has this identifier.",
        422: "The request is invalid.",
        500: "An unexpected server error.",
        503: "A service the operation depends on is unavailable.",
    }.items()
}


def responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """The contract's error responses for an operation."""
    return {code: ERROR_RESPONSES[code] for code in codes}


def error(
    status: int,
    code: str,
    message: str,
    service: str | None = None,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    body = ErrorBody(
        code=code,
        message=message,
        service=service,
        details=details or [],
    )
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _field(loc: tuple[Any, ...]) -> str:
    parts = list(loc)
    if parts and parts[0] in ("body", "query", "path"):
        parts = parts[1:]
    return ".".join(str(p) for p in parts) or "body"


def install(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [ErrorDetail(field=_field(e["loc"]), message=e["msg"]) for e in exc.errors()]
        return error(422, "validation_error", "The request is invalid.", details=details)

    @app.exception_handler(InvalidRequestError)
    async def invalid(request: Request, exc: InvalidRequestError) -> JSONResponse:
        detail = ErrorDetail(field=exc.field, message=str(exc))
        return error(422, "validation_error", str(exc), details=[detail])

    @app.exception_handler(AnalysisError)
    @app.exception_handler(InvalidStatusTransitionError)
    @app.exception_handler(InvalidCursorError)
    async def rejected(request: Request, exc: Exception) -> JSONResponse:
        return error(422, "validation_error", str(exc))

    @app.exception_handler(InvestigationNotFoundError)
    async def not_found(request: Request, exc: InvestigationNotFoundError) -> JSONResponse:
        return error(404, "not_found", str(exc))

    @app.exception_handler(DataUnavailableError)
    async def data_down(request: Request, exc: DataUnavailableError) -> JSONResponse:
        logger.error("data service unavailable: %s", exc)
        return error(503, "service_unavailable", "The data service is unavailable.", "data_service")

    @app.exception_handler(DatabaseUnavailableError)
    async def database_down(request: Request, exc: DatabaseUnavailableError) -> JSONResponse:
        logger.error("database unavailable: %s", exc)
        return error(
            503, "service_unavailable", "The investigation database is unavailable.", "database"
        )

    @app.exception_handler(Exception)
    async def internal(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected error")
        return error(500, "internal_error", "An unexpected error occurred.")

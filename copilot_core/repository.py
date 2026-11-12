"""Save, update, list and fetch investigations in Postgres.

``InvestigationRepository`` is the only code that reads or writes the
``investigations`` table. Every value is validated with the Pydantic models
on the way in and on the way out, so a row that no longer matches the
models is reported rather than served.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from sqlalchemy import Engine, select, tuple_, update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from copilot_core.db import DataMode, InvestigationRecord, InvestigationStatus
from copilot_core.models import Finding, SourceRef
from copilot_core.schemas import (
    Investigation,
    InvestigationCreate,
    InvestigationRequest,
    InvestigationResult,
    InvestigationSummary,
    InvestigationUpdate,
)

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "ChartConfig",
    "DatabaseUnavailableError",
    "InvalidCursorError",
    "InvalidStatusTransitionError",
    "InvestigationNotFoundError",
    "InvestigationPage",
    "InvestigationRepository",
    "RepositoryError",
]

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
"""Page size limits of ``listInvestigations`` in ``api/openapi.yaml``."""

TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "failed"},
    "running": {"succeeded", "failed"},
    "succeeded": set(),
    "failed": set(),
}


class RepositoryError(Exception):
    pass


class DatabaseUnavailableError(RepositoryError):
    """Postgres cannot be reached. The API answers ``503``."""


class InvestigationNotFoundError(RepositoryError):
    def __init__(self, investigation_id: uuid.UUID) -> None:
        self.investigation_id = investigation_id
        super().__init__(f"Investigation {investigation_id} was not found.")


class InvalidStatusTransitionError(RepositoryError, ValueError):
    def __init__(self, current: str, new: str) -> None:
        super().__init__(
            f"Status cannot move from {current!r} to {new!r}; allowed: pending -> running -> "
            "succeeded or failed, or pending -> failed"
        )


class InvalidCursorError(RepositoryError, ValueError):
    pass


class ChartConfig(BaseModel):
    """How the workspace draws an investigation's series."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["line"]
    series_ids: tuple[str, ...]


_findings = TypeAdapter(list[Finding])
_sources = TypeAdapter(list[SourceRef])


@dataclass(frozen=True)
class InvestigationPage:
    items: list[InvestigationSummary]
    limit: int
    next_cursor: str | None


def _encode_cursor(created_at: datetime, investigation_id: uuid.UUID) -> str:
    raw = json.dumps({"c": created_at.isoformat(), "i": str(investigation_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        return datetime.fromisoformat(data["c"]), uuid.UUID(data["i"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise InvalidCursorError("cursor is not a cursor from a previous page") from exc


def _chart_config(result: InvestigationResult) -> dict[str, Any] | None:
    if not result.series:
        return None
    config = ChartConfig(type="line", series_ids=tuple(s.id for s in result.series))
    return config.model_dump(mode="json")


class InvestigationRepository:
    """Investigations stored in the ``investigations`` table.

    Concurrent updates to the same investigation are serialized with a row
    lock: both finish, and the stored row is the later one (last write wins).
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def _session(self) -> Iterator[Session]:
        try:
            with Session(self.engine) as session, session.begin():
                yield session
        except OperationalError as exc:
            raise DatabaseUnavailableError("The investigation database is unavailable") from exc
        except DBAPIError as exc:
            if exc.connection_invalidated:
                raise DatabaseUnavailableError("The investigation database is unavailable") from exc
            raise

    @staticmethod
    def _apply_result(record: InvestigationRecord, result: InvestigationResult) -> None:
        dumped = result.model_dump(mode="json")
        record.result = dumped
        record.findings = _findings.dump_python(
            _findings.validate_python(result.findings), mode="json"
        )
        record.sources = _sources.dump_python(_sources.validate_python(result.sources), mode="json")
        record.chart_config = _chart_config(result)

    @staticmethod
    def _apply_request(record: InvestigationRecord, request: InvestigationRequest) -> None:
        dumped = request.model_dump(mode="json")
        record.request = dumped
        record.question = request.question
        record.selections = {
            "investigation_type": request.investigation_type,
            "countries": request.countries,
            "indicators": request.indicators,
            "period": dumped["period"],
        }
        record.parameters = dumped["parameters"]

    @staticmethod
    def _to_model(record: InvestigationRecord) -> Investigation:
        try:
            _findings.validate_python(record.findings)
            _sources.validate_python(record.sources)
            if record.chart_config is not None:
                ChartConfig.model_validate(record.chart_config)
            return Investigation(
                id=record.id,
                title=record.title,
                status=record.status,
                data_mode=record.data_mode,
                request=InvestigationRequest.model_validate(record.request),
                result=InvestigationResult.model_validate(record.result),
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        except ValidationError as exc:
            raise RepositoryError(f"Stored investigation {record.id} is invalid: {exc}") from exc

    def create(
        self,
        body: InvestigationCreate,
        data_mode: DataMode,
        status: InvestigationStatus = "pending",
    ) -> Investigation:
        """Save a new investigation. ``body.status``, if given, wins over ``status``."""
        body = InvestigationCreate.model_validate(body.model_dump(exclude_unset=True))
        record = InvestigationRecord(
            title=body.title, data_mode=data_mode, status=body.status or status
        )
        self._apply_request(record, body.request)
        self._apply_result(record, body.result)
        with self._session() as session:
            session.add(record)
            session.flush()
            session.refresh(record)
            return self._to_model(record)

    def get(self, investigation_id: uuid.UUID) -> Investigation:
        with self._session() as session:
            record = session.get(InvestigationRecord, investigation_id)
            if record is None:
                raise InvestigationNotFoundError(investigation_id)
            return self._to_model(record)

    def update(self, investigation_id: uuid.UUID, body: InvestigationUpdate) -> Investigation:
        """Change the fields set in ``body``; ``updated_at`` moves forward.

        The row is locked for the update, so two concurrent updates both
        finish and the later one is what is stored (last write wins). A
        status change must follow pending -> running -> succeeded or failed.
        """
        fields = body.model_fields_set
        with self._session() as session:
            record = session.get(InvestigationRecord, investigation_id, with_for_update=True)
            if record is None:
                raise InvestigationNotFoundError(investigation_id)
            if "status" in fields and body.status is not None and body.status != record.status:
                if body.status not in TRANSITIONS[record.status]:
                    raise InvalidStatusTransitionError(record.status, body.status)
                record.status = body.status
            if "title" in fields and body.title is not None:
                record.title = body.title
            if "request" in fields and body.request is not None:
                self._apply_request(record, body.request)
            if "result" in fields and body.result is not None:
                self._apply_result(record, body.result)
            # Touch the row even when nothing changed, so the trigger moves
            # updated_at forward.
            session.execute(
                update(InvestigationRecord)
                .where(InvestigationRecord.id == investigation_id)
                .values(title=record.title)
            )
            session.flush()
            session.refresh(record)
            return self._to_model(record)

    def list(self, limit: int = DEFAULT_PAGE_SIZE, cursor: str | None = None) -> InvestigationPage:
        """One page of investigations, newest first, then by id."""
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}, got {limit}")
        query = select(InvestigationRecord).order_by(
            InvestigationRecord.created_at.desc(), InvestigationRecord.id.desc()
        )
        if cursor:
            created_at, last_id = _decode_cursor(cursor)
            query = query.where(
                tuple_(InvestigationRecord.created_at, InvestigationRecord.id)
                < tuple_(created_at, last_id)
            )
        with self._session() as session:
            records = list(session.scalars(query.limit(limit + 1)))
            items = [self._summary(r) for r in records[:limit]]
            next_cursor = (
                _encode_cursor(records[limit - 1].created_at, records[limit - 1].id)
                if len(records) > limit
                else None
            )
        return InvestigationPage(items=items, limit=limit, next_cursor=next_cursor)

    def _summary(self, record: InvestigationRecord) -> InvestigationSummary:
        full = self._to_model(record)
        return InvestigationSummary(
            id=full.id,
            title=full.title,
            status=full.status,
            data_mode=full.data_mode,
            investigation_type=full.request.investigation_type,
            countries=full.request.countries,
            indicators=full.request.indicators,
            created_at=full.created_at,
            updated_at=full.updated_at,
        )

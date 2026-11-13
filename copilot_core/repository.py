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
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from sqlalchemy import Engine, delete, func, select, tuple_, update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from copilot_core.db import DataMode, InvestigationRecord, InvestigationStatus
from copilot_core.models import Finding, SourceRef
from copilot_core.schemas import (
    Investigation,
    InvestigationCreate,
    InvestigationError,
    InvestigationRequest,
    InvestigationResult,
    InvestigationRun,
    InvestigationSummary,
    InvestigationUpdate,
    LLMUsage,
    Selection,
)

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "ChartConfig",
    "Claim",
    "DatabaseUnavailableError",
    "InvalidCursorError",
    "InvalidStatusTransitionError",
    "InvestigationLimitError",
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


class InvestigationLimitError(RepositoryError):
    """The owner already has the most investigations the history may hold. The API answers ``409``."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(
            f"This browser has reached the limit of {limit} saved investigations. "
            "Investigations are removed after they are old enough; try again later."
        )


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


def _with_new_fields(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Results saved before runs existed lack ``tool_results`` and ``charts``."""
    if result is None:
        return None
    return {"tool_results": [], "charts": [], **result}


@dataclass(frozen=True)
class Claim:
    """The outcome of :meth:`InvestigationRepository.claim`."""

    claimed: bool
    investigation: Investigation


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

    def __init__(
        self, engine: Engine, owner: str | None = None, owner_limit: int | None = None
    ) -> None:
        self.engine = engine
        self._owner = owner
        self._owner_limit = owner_limit

    def for_owner(self, owner: str | None, limit: int | None = None) -> InvestigationRepository:
        """A repository on the same database that sees and saves only ``owner``'s rows.

        ``limit`` is the most investigations the owner may have saved. With no
        owner the repository is unscoped, as the startup sweep and tests use it.
        """
        return InvestigationRepository(self.engine, owner, limit)

    def _visible(self, record: InvestigationRecord | None) -> bool:
        return record is not None and (self._owner is None or record.owner == self._owner)

    def _check_limit(self, session: Session) -> None:
        if self._owner is None or self._owner_limit is None:
            return
        count = session.scalar(
            select(func.count())
            .select_from(InvestigationRecord)
            .where(InvestigationRecord.owner == self._owner)
        )
        if (count or 0) >= self._owner_limit:
            raise InvestigationLimitError(self._owner_limit)

    def delete_expired_anonymous(self, max_age_days: float) -> int:
        """Delete anonymous investigations older than ``max_age_days``; returns how many."""
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        with self._session() as session:
            result = session.execute(
                delete(InvestigationRecord).where(
                    InvestigationRecord.owner.like("anon:%"),
                    InvestigationRecord.created_at < cutoff,
                )
            )
            return result.rowcount or 0  # type: ignore[attr-defined]

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
            # For example a missing table: the page must say the history cannot be read,
            # not fail with a 500.
            raise RepositoryError("The investigation database could not be read") from exc

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
            result = _with_new_fields(record.result)
            error = (
                InvestigationError(
                    code=record.error_code,
                    message=record.error or "",
                    service=record.error_service,
                )
                if record.error_code
                else None
            )
            return Investigation(
                id=record.id,
                title=record.title,
                status=record.status,
                data_mode=record.data_mode,
                request=InvestigationRequest.model_validate(record.request)
                if record.request is not None
                else None,
                result=InvestigationResult.model_validate(result) if result is not None else None,
                error=error,
                run=InvestigationRun.model_validate(record.run) if record.run is not None else None,
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
            title=body.title,
            data_mode=data_mode,
            status=body.status or status,
            owner=self._owner,
        )
        self._apply_request(record, body.request)
        self._apply_result(record, body.result)
        with self._session() as session:
            self._check_limit(session)
            session.add(record)
            session.flush()
            session.refresh(record)
            return self._to_model(record)

    def create_run(
        self,
        question: str | None,
        selection: Selection | None,
        data_mode: DataMode,
        title: str,
    ) -> Investigation:
        """Save a run as ``pending``, with no request or result yet."""
        run = InvestigationRun(
            question=question,
            selection=selection,
            prompt_version=None,
            model=None,
            tool_calls=[],
            validation=None,
            usage=LLMUsage(calls=0, input_tokens=0, output_tokens=0, latency_ms=0),
        )
        record = InvestigationRecord(
            title=title,
            data_mode=data_mode,
            status="pending",
            question=question,
            selections=selection.model_dump(mode="json") if selection else {},
            run=run.model_dump(mode="json"),
            owner=self._owner,
        )
        with self._session() as session:
            self._check_limit(session)
            session.add(record)
            session.flush()
            session.refresh(record)
            return self._to_model(record)

    def claim(self, investigation_id: uuid.UUID, pending_timeout_seconds: float) -> Claim:
        """Move a ``pending`` investigation to ``running`` in one update.

        Only one caller can win: the update matches the row only while it is
        still ``pending``. A ``pending`` investigation older than
        ``pending_timeout_seconds`` is not claimed; it is saved as ``failed``
        with code ``not_started``. Otherwise the investigation is returned as
        it is.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=pending_timeout_seconds)
        with self._session() as session:
            claimed = session.execute(
                update(InvestigationRecord)
                .where(
                    InvestigationRecord.id == investigation_id,
                    InvestigationRecord.status == "pending",
                    InvestigationRecord.created_at > cutoff,
                )
                .values(status="running")
                .returning(InvestigationRecord.id)
            ).first()
        if claimed is None:
            self.mark_failed(
                investigation_id,
                InvestigationError(
                    code="not_started",
                    message="The investigation was not started in time.",
                    service=None,
                ),
                statuses=("pending",),
            )
        return Claim(claimed=claimed is not None, investigation=self.get(investigation_id))

    def save_success(
        self,
        investigation_id: uuid.UUID,
        result: InvestigationResult,
        run: InvestigationRun,
    ) -> Investigation | None:
        """Save a ``running`` investigation as ``succeeded``; ``None`` if it is not running."""
        with self._session() as session:
            record = session.get(InvestigationRecord, investigation_id, with_for_update=True)
            if record is None:
                raise InvestigationNotFoundError(investigation_id)
            if record.status != "running":
                return None
            record.status = "succeeded"
            if result.request is not None:
                self._apply_request(record, result.request)
                record.question = run.question
            self._apply_result(record, result)
            record.run = run.model_dump(mode="json")
            session.flush()
            session.refresh(record)
            return self._to_model(record)

    def mark_failed(
        self,
        investigation_id: uuid.UUID,
        error: InvestigationError,
        run: InvestigationRun | None = None,
        statuses: tuple[str, ...] = ("pending", "running"),
    ) -> bool:
        """Save the investigation as ``failed`` if its status is in ``statuses``.

        A failed investigation keeps no result, so nothing is presented as a
        success. Returns whether the row changed.
        """
        values: dict[str, Any] = {
            "status": "failed",
            "error": error.message,
            "error_code": error.code,
            "error_service": error.service,
            "result": None,
        }
        if run is not None:
            values["run"] = run.model_dump(mode="json")
        with self._session() as session:
            changed = session.execute(
                update(InvestigationRecord)
                .where(
                    InvestigationRecord.id == investigation_id,
                    InvestigationRecord.status.in_(statuses),
                )
                .values(**values)
                .returning(InvestigationRecord.id)
            ).first()
        return changed is not None

    def sweep(self, running_timeout_seconds: float, pending_timeout_seconds: float) -> int:
        """Fail runs a restart left behind; returns how many changed.

        ``running`` longer than ``running_timeout_seconds`` becomes ``failed``
        with code ``interrupted``; ``pending`` longer than
        ``pending_timeout_seconds`` becomes ``failed`` with code ``not_started``.
        """
        now = datetime.now(UTC)
        stale = (
            (
                InvestigationRecord.status == "running",
                InvestigationRecord.updated_at < now - timedelta(seconds=running_timeout_seconds),
                "interrupted",
                "The run was interrupted by a restart.",
            ),
            (
                InvestigationRecord.status == "pending",
                InvestigationRecord.created_at < now - timedelta(seconds=pending_timeout_seconds),
                "not_started",
                "The investigation was not started in time.",
            ),
        )
        changed = 0
        with self._session() as session:
            for status, older, code, message in stale:
                rows = session.execute(
                    update(InvestigationRecord)
                    .where(status, older)
                    .values(status="failed", error=message, error_code=code, result=None)
                    .returning(InvestigationRecord.id)
                ).all()
                changed += len(rows)
        return changed

    def get(self, investigation_id: uuid.UUID) -> Investigation:
        with self._session() as session:
            record = session.get(InvestigationRecord, investigation_id)
            if record is None or not self._visible(record):
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
            if record is None or not self._visible(record):
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
        if self._owner is not None:
            query = query.where(InvestigationRecord.owner == self._owner)
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
        request = full.request
        selection = full.run.selection if full.run else None
        countries = request.countries if request else selection.countries if selection else []
        indicators = request.indicators if request else [selection.indicator] if selection else []
        return InvestigationSummary(
            id=full.id,
            title=full.title,
            status=full.status,
            data_mode=full.data_mode,
            investigation_type=request.investigation_type if request else None,
            countries=countries,
            indicators=indicators,
            created_at=full.created_at,
            updated_at=full.updated_at,
        )

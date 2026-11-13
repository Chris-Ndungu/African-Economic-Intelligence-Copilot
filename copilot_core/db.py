"""Postgres tables and engine for saved investigations.

The tables are declared here in SQLAlchemy 2 style so the repository and the
Alembic migrations in ``migrations/`` share one definition. The schema only
changes through a migration: ``uv run alembic check`` fails when these
models and the migrations disagree.

Connection strings carry a password, so they never appear in an error
message or log line: :func:`create_db_engine` reports a malformed URL without
echoing it, and SQLAlchemy masks the password whenever a URL is printed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import SecretStr
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Engine,
    FetchedValue,
    Index,
    MetaData,
    Text,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "DATA_MODES",
    "STATUSES",
    "Base",
    "DataMode",
    "InvestigationRecord",
    "InvestigationStatus",
    "create_db_engine",
    "database_url",
]

DataMode = Literal["demo", "live"]
InvestigationStatus = Literal["pending", "running", "succeeded", "failed"]

DATA_MODES: tuple[str, ...] = get_args(DataMode)
STATUSES: tuple[str, ...] = get_args(InvestigationStatus)

# Deterministic constraint names, so migrations can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class InvestigationRecord(Base):
    """One investigation: what was asked, how it ran and what it found.

    ``question`` is ``None`` when the investigation starts from selections
    alone. ``request`` and ``result`` hold the contract's
    ``InvestigationRequest`` and ``InvestigationResult``; ``findings``,
    ``sources`` and ``chart_config`` repeat parts of them for querying. The JSONB columns hold the JSON form of the result models in
    :mod:`copilot_core.models`. ``updated_at`` is set by a database trigger
    on every update, whichever client makes it.
    """

    __tablename__ = "investigations"
    __table_args__ = (
        CheckConstraint(_in("data_mode", DATA_MODES), name="data_mode"),
        CheckConstraint(_in("status", STATUSES), name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    question: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, server_default="")
    request: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    selections: Mapped[dict[str, Any]] = mapped_column(JSONB)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    findings: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    chart_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sources: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    data_mode: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_service: Mapped[str | None] = mapped_column(Text)
    run: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    owner: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        server_onupdate=FetchedValue(),
    )


# Lists investigations newest first, with id breaking ties so pages are stable.
Index(
    "ix_investigations_created_at_id",
    InvestigationRecord.created_at.desc(),
    InvestigationRecord.id.desc(),
)


# Lists one visitor's investigations, and finds expired anonymous ones.
Index(
    "ix_investigations_owner_created_at", InvestigationRecord.owner, InvestigationRecord.created_at
)


def database_url(url: str | SecretStr) -> URL:
    """Parse a Postgres connection string for the psycopg 3 driver.

    ``postgres://`` and ``postgresql://`` URLs, as hosting providers give
    them, use psycopg 3. Raises ``ValueError`` without the URL in the
    message, because it may contain a password.
    """
    raw = url.get_secret_value() if isinstance(url, SecretStr) else url
    try:
        parsed = make_url(raw)
    except ArgumentError:
        raise ValueError("DATABASE_URL is not a valid database URL") from None
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.drivername != "postgresql+psycopg":
        raise ValueError(
            "DATABASE_URL must be a PostgreSQL URL, for example "
            "postgresql+psycopg://user:password@localhost:5432/copilot"
        )
    return parsed


def create_db_engine(url: str | SecretStr | URL, **kwargs: Any) -> Engine:
    """Create an engine whose sessions read and write timestamps in UTC."""
    parsed = url if isinstance(url, URL) else database_url(url)
    connect_args = {"options": "-c timezone=UTC", **kwargs.pop("connect_args", {})}
    return create_engine(parsed, connect_args=connect_args, **kwargs)

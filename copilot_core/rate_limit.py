"""Limits on how many investigations a visitor and all visitors may run.

Anonymous visitors to the public deployment must not run up Gemini costs, so
every run is counted: per client (for example 10 an hour) and in total (for
example 200 a day). A run over either limit is refused before Gemini is
called. Counts live in Postgres, so they hold across Cloud Run instances.

Clients are identified by a salted hash of their IP address; the address
itself is never stored, logged or put in telemetry, and a row is deleted
once it is older than the longest window. This module has no web-framework
imports.
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.orm import Session

from copilot_core.db import RunAttemptRecord
from copilot_core.telemetry import record_rate_limit_hit

__all__ = [
    "MemoryAttemptStore",
    "PostgresAttemptStore",
    "RateLimitedError",
    "RateLimits",
    "RunLimiter",
    "client_key",
]

Tier = Literal["anonymous", "authenticated"]
Kind = Literal["client", "daily"]

HOUR = 3600.0
DAY = 86400.0


@dataclass(frozen=True)
class RateLimits:
    per_client_limit: int = 10
    """Runs one anonymous client may start per ``per_client_window_seconds``."""

    per_client_window_seconds: float = HOUR

    authenticated_limit: int = 60
    """The higher per-client limit of an authenticated live-mode user."""

    daily_limit: int = 200
    """Runs all visitors together may start per ``daily_window_seconds``."""

    daily_window_seconds: float = DAY


class RateLimitedError(Exception):
    """A run was refused. ``retry_after`` is the seconds until one is allowed."""

    def __init__(self, kind: Kind, limit: int, window_seconds: float, retry_after: int) -> None:
        self.kind = kind
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after = retry_after
        super().__init__(self.message())

    def message(self) -> str:
        if self.kind == "daily":
            return (
                f"The copilot has reached its daily limit of {self.limit} investigations "
                f"across all visitors. Try again in {_wait(self.retry_after)}."
            )
        per = "hour" if self.window_seconds == HOUR else f"{self.window_seconds:g} seconds"
        return (
            f"You have reached the limit of {self.limit} investigations per {per}. "
            f"Try again in {_wait(self.retry_after)}."
        )


def _wait(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} seconds"
    if seconds < 5400:
        return f"{math.ceil(seconds / 60)} minutes"
    return f"{math.ceil(seconds / 3600)} hours"


def client_key(identity: str, salt: str = "") -> str:
    """The stored form of a client: a salted SHA-256, never the address itself."""
    return hashlib.sha256(f"{salt}|{identity}".encode()).hexdigest()


class AttemptTransaction(Protocol):
    def count(self, since: datetime, client: str | None = None) -> int: ...

    def oldest(self, since: datetime, client: str | None = None) -> datetime | None: ...

    def add(self, client: str, at: datetime) -> None: ...

    def purge(self, before: datetime) -> None: ...


class AttemptStore(Protocol):
    def transaction(self) -> AbstractContextManager[AttemptTransaction]:
        """One serialized unit of work: count, decide, record."""
        ...


class RunLimiter:
    def __init__(
        self,
        store: AttemptStore,
        limits: RateLimits | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.limits = limits or RateLimits()
        self.clock = clock

    def check(self, client: str, tier: Tier = "anonymous") -> None:
        """Count one run for ``client``, or raise :class:`RateLimitedError` and count nothing."""
        limits = self.limits
        per_client = (
            limits.authenticated_limit if tier == "authenticated" else limits.per_client_limit
        )
        now = self.clock()
        with self.store.transaction() as tx:
            tx.purge(
                now
                - timedelta(
                    seconds=max(limits.per_client_window_seconds, limits.daily_window_seconds)
                )
            )
            for kind, limit, window, who in (
                ("client", per_client, limits.per_client_window_seconds, client),
                ("daily", limits.daily_limit, limits.daily_window_seconds, None),
            ):
                since = now - timedelta(seconds=window)
                if tx.count(since, who) >= limit:
                    oldest = tx.oldest(since, who) or now
                    wait = max(
                        1, math.ceil((oldest + timedelta(seconds=window) - now).total_seconds())
                    )
                    record_rate_limit_hit(kind)
                    raise RateLimitedError(kind, limit, window, wait)  # type: ignore[arg-type]
            tx.add(client, now)


class PostgresAttemptStore:
    """Attempts in the ``run_attempts`` table, serialized with an advisory lock."""

    LOCK_ID = 60_001

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def transaction(self) -> Iterator[AttemptTransaction]:
        with Session(self.engine) as session, session.begin():
            session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": self.LOCK_ID})
            yield _PostgresTransaction(session)


class _PostgresTransaction:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _where(self, since: datetime, client: str | None) -> list:  # type: ignore[type-arg]
        conditions = [RunAttemptRecord.created_at > since]
        if client is not None:
            conditions.append(RunAttemptRecord.client_hash == client)
        return conditions

    def count(self, since: datetime, client: str | None = None) -> int:
        query = (
            select(func.count()).select_from(RunAttemptRecord).where(*self._where(since, client))
        )
        return self.session.scalar(query) or 0

    def oldest(self, since: datetime, client: str | None = None) -> datetime | None:
        query = select(func.min(RunAttemptRecord.created_at)).where(*self._where(since, client))
        return self.session.scalar(query)

    def add(self, client: str, at: datetime) -> None:
        self.session.add(RunAttemptRecord(client_hash=client, created_at=at))

    def purge(self, before: datetime) -> None:
        self.session.execute(delete(RunAttemptRecord).where(RunAttemptRecord.created_at <= before))


class MemoryAttemptStore:
    """Attempts in this process. For tests and runs without a database only."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, datetime]] = []
        self._lock = threading.Lock()

    @contextmanager
    def transaction(self) -> Iterator[AttemptTransaction]:
        with self._lock:
            yield self

    def _within(self, since: datetime, client: str | None) -> list[datetime]:
        return [t for c, t in self.rows if t > since and (client is None or c == client)]

    def count(self, since: datetime, client: str | None = None) -> int:
        return len(self._within(since, client))

    def oldest(self, since: datetime, client: str | None = None) -> datetime | None:
        times = self._within(since, client)
        return min(times) if times else None

    def add(self, client: str, at: datetime) -> None:
        self.rows.append((client, at))

    def purge(self, before: datetime) -> None:
        self.rows = [(c, t) for c, t in self.rows if t > before]

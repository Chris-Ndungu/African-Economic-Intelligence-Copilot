"""The investigation history list: titles, dates and statuses for the sidebar.

Everything the sidebar prints is decided here, so the template only renders
it. The list comes from :class:`~copilot_core.repository.InvestigationRepository`,
newest first. This module has no web-framework imports.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from copilot_core.repository import (
    InvestigationNotFoundError,
    InvestigationPage,
    RepositoryError,
)
from copilot_core.schemas import Investigation, Selection

__all__ = [
    "HISTORY_PAGE_SIZE",
    "STATUS_DISPLAY",
    "TITLE_LIMIT",
    "HistoryEntry",
    "HistoryPage",
    "clip",
    "history_title",
    "investigation_question",
    "investigation_selection",
    "iso_utc",
    "load_history",
    "selection_summary",
    "utc_date",
    "utc_text",
]

HISTORY_PAGE_SIZE = 20
TITLE_LIMIT = 60
"""Longest sidebar title in characters, including the ellipsis."""

STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "pending": ("Pending", "○"),
    "running": ("Running", "◔"),
    "succeeded": ("Succeeded", "✓"),
    "failed": ("Failed", "✕"),
}
"""Status to its text label and icon. The icon never stands alone."""


class _Listing(Protocol):
    def list(self, limit: int = ..., cursor: str | None = ...) -> InvestigationPage: ...

    def get(self, investigation_id: uuid.UUID) -> Investigation: ...


def clip(text: str, limit: int = TITLE_LIMIT) -> str:
    """``text`` on one line, cut to ``limit`` characters with ``…`` when longer."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def selection_summary(indicator: str, countries: list[str], start: str, end: str) -> str:
    return f"{indicator} · {', '.join(countries)} · {start}–{end}"


def investigation_question(investigation: Investigation) -> str | None:
    """The question the analyst asked, or ``None`` for a selection-only run."""
    for question in (
        investigation.request.question if investigation.request else None,
        investigation.run.question if investigation.run else None,
    ):
        if question and question.strip():
            return question
    return None


def investigation_selection(investigation: Investigation) -> Selection | None:
    """The countries, indicator and period the investigation was run on, if known."""
    if investigation.run and investigation.run.selection:
        return investigation.run.selection
    request = investigation.request
    if request is not None and request.indicators:
        return Selection(
            countries=request.countries,
            indicator=request.indicators[0],
            start=request.period.start,
            end=request.period.end,
        )
    return None


def history_title(investigation: Investigation) -> str:
    """The question cut to 60 characters, or a summary of the selections."""
    question = investigation_question(investigation)
    if question:
        return clip(question)
    selection = investigation_selection(investigation)
    if selection:
        return selection_summary(
            selection.indicator, list(selection.countries), selection.start, selection.end
        )
    return clip(investigation.title)


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def iso_utc(moment: datetime) -> str:
    """``2026-11-12T10:30:00Z``, for a ``<time datetime>`` attribute."""
    return _utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_date(moment: datetime) -> str:
    return _utc(moment).strftime("%Y-%m-%d")


def utc_text(moment: datetime) -> str:
    """``2026-11-12 10:30 UTC``: the time zone is always stated."""
    return _utc(moment).strftime("%Y-%m-%d %H:%M UTC")


@dataclass(frozen=True)
class HistoryEntry:
    id: uuid.UUID
    title: str
    status: str
    status_label: str
    status_icon: str
    created_iso: str
    created_date: str


@dataclass(frozen=True)
class HistoryPage:
    entries: list[HistoryEntry]
    next_cursor: str | None


def load_history(
    repository: _Listing, limit: int = HISTORY_PAGE_SIZE, cursor: str | None = None
) -> HistoryPage:
    """One page of saved investigations, newest first.

    Raises :class:`~copilot_core.repository.RepositoryError` (for example
    ``DatabaseUnavailableError``) when the list cannot be read. A single row
    that cannot be read keeps the title it was saved with.
    """
    page = repository.list(limit=limit, cursor=cursor)
    entries: list[HistoryEntry] = []
    for item in page.items:
        try:
            title = history_title(repository.get(item.id))
        except InvestigationNotFoundError:
            continue
        except RepositoryError:
            title = clip(item.title)
        label, icon = STATUS_DISPLAY[item.status]
        entries.append(
            HistoryEntry(
                id=item.id,
                title=title,
                status=item.status,
                status_label=label,
                status_icon=icon,
                created_iso=iso_utc(item.created_at),
                created_date=utc_date(item.created_at),
            )
        )
    return HistoryPage(entries=entries, next_cursor=page.next_cursor)

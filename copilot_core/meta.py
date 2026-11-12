"""What the app is serving: the data mode, the demo snapshot date and Gemini.

One function, :func:`get_meta`, answers for both the ``GET /api/meta`` route
and every page, so a page never calls the API over HTTP. When the mode cannot
be determined (for example the snapshot date cannot be read) the answer is
``unknown``; it is never assumed to be ``live``. This module has no
web-framework imports.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from copilot_core.db import DataMode
from copilot_core.schemas import Meta

__all__ = ["banner_text", "get_meta", "read_snapshot_date"]

SNAPSHOT_LINE = re.compile(r"^Snapshot date:\s*(\d{4}-\d{2}-\d{2})", re.M)


def read_snapshot_date(data_dir: Path) -> date | None:
    """The snapshot date in ``<data_dir>/README.md``, or ``None`` if it cannot be read."""
    try:
        match = SNAPSHOT_LINE.search((Path(data_dir) / "README.md").read_text(encoding="utf-8"))
        return date.fromisoformat(match.group(1)) if match else None
    except (OSError, ValueError):
        return None


def get_meta(
    data_dir: Path,
    gemini_configured: bool,
    data_mode: DataMode = "demo",
    snapshot_date: date | None = None,
) -> Meta:
    """The data mode, the demo snapshot date and whether Gemini is configured.

    ``snapshot_date`` is a setting that overrides the date in the README.
    A demo app whose date cannot be found reports ``unknown``.
    """
    if data_mode == "live":
        return Meta(data_mode="live", snapshot_date=None, gemini_configured=gemini_configured)
    found = snapshot_date or read_snapshot_date(data_dir)
    return Meta(
        data_mode="demo" if found else "unknown",
        snapshot_date=found,
        gemini_configured=gemini_configured,
    )


def banner_text(meta: Meta) -> str:
    """The banner's wording; the text, not only its colour, states the mode."""
    if meta.data_mode == "demo":
        return f"Sample data from {meta.snapshot_date}. Not live economic data."
    if meta.data_mode == "live":
        return "Live data"
    return "Data mode unknown. This page cannot tell whether the data is sample or live."

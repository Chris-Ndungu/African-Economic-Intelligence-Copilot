"""One number formatter, so the same value always prints the same way.

Tables, chart hover text and finding cards use :func:`format_number`, and
the PDF report (#32) uses it too. The backend registers it as the Jinja
filter ``number``.
"""

from __future__ import annotations

__all__ = ["MISSING", "decimals_for", "format_number"]

MISSING = "—"
"""What a missing value prints as. It is never ``0`` or blank."""

_ONE_DECIMAL = {"%", "PERCENT", "PP", "USD_BN", "MILLIONS", "BILLIONS", "INDEX"}
_NO_DECIMALS = {"USD", "LCU", "PERSONS"}


def decimals_for(unit: str | None) -> int:
    """Fixed decimals for a unit type: 1 for percentages and billions or
    millions, 0 for plain currency amounts, 2 for any other or no unit."""
    key = (unit or "").strip().upper()
    if key in _ONE_DECIMAL:
        return 1
    if key in _NO_DECIMALS:
        return 0
    return 2


def format_number(value: float | int | None, unit: str | None = None) -> str:
    """Format ``value`` with thousands separators and the unit's fixed decimals.

    Rules, in order:

    - ``None`` prints as ``—`` (:data:`MISSING`), never ``0``
    - decimals come from :func:`decimals_for`: ``%`` and ``USD_BN`` and
      ``MILLIONS`` give 1 (``1,234.5``), ``USD`` gives 0 (``1,234``), any other
      unit gives 2 (``1,234.50``)
    - thousands are separated by a comma and the decimal mark is a point
    - a value that rounds to zero prints without a minus sign (``0.0``)

    The unit itself is not appended: tables and axes name it in their header.
    """
    if value is None:
        return MISSING
    decimals = decimals_for(unit)
    text = f"{value:,.{decimals}f}"
    if text.startswith("-") and not any(ch in "123456789" for ch in text):
        text = text[1:]
    return text

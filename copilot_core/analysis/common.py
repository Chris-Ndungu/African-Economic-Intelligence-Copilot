"""Helpers shared by the analysis functions."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from copilot_core.models import Frequency, Period, SeriesResult, period_frequency

PER_PERIOD = {"annual": "year", "quarterly": "quarter", "monthly": "month", "daily": "day"}
PERCENT_UNITS = ("%", "percent")


class AnalysisError(ValueError):
    """The input cannot be analysed as asked, for example a mixed frequency."""


def frequency_of(series: SeriesResult) -> Frequency:
    """The series' frequency; raises if its points mix frequencies."""
    found = {period_frequency(p.period) for p in series.points} | {series.period.frequency}
    if len(found) > 1:
        names = ", ".join(sorted(str(f) for f in found))
        raise AnalysisError(f"Series {series.id} mixes frequencies: {names}")
    return series.period.frequency


def is_percent(unit: str) -> bool:
    """Whether the unit is a percentage, so differences are percentage points."""
    return unit.strip().startswith(PERCENT_UNITS) or "% " in unit


def change_unit(unit: str) -> str:
    """The unit of a difference between two values of ``unit``."""
    return "percentage points" if is_percent(unit) else unit


def single(label: str, frequency: Frequency) -> Period:
    return Period(start=label, end=label, frequency=frequency)


def span(labels: Sequence[str], frequency: Frequency) -> Period:
    return Period(start=labels[0], end=labels[-1], frequency=frequency)


def clean(value: float) -> float | None:
    """``None`` for NaN or infinity, which result models reject."""
    return value if math.isfinite(value) else None


def mean(values: Sequence[float]) -> float:
    # statistics.mean is exact for floats, so adding a constant to every
    # value shifts the mean by exactly that constant.
    return float(statistics.mean(values))


def stdev(values: Sequence[float]) -> float:
    """Sample standard deviation (n - 1)."""
    return float(statistics.stdev(values))

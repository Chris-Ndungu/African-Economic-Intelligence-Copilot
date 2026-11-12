"""Trend and growth of one country's indicator series."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from copilot_core.analysis.common import PER_PERIOD, change_unit, clean, frequency_of, span
from copilot_core.models import Method, NumericResult, SeriesResult

__all__ = ["TrendResult", "analyze_trend"]


@dataclass(frozen=True)
class TrendResult:
    """Level change, percentage change, growth and linear trend of a series.

    Every number is a :class:`NumericResult` carrying its unit, period,
    method, parameters and source. A number that cannot be computed is
    ``None`` with a caveat saying why.
    """

    series_id: str
    level: NumericResult | None
    level_change: NumericResult
    percent_change: NumericResult
    growth: tuple[NumericResult, ...]
    slope: NumericResult
    intercept: NumericResult
    r_squared: NumericResult
    points_used: int
    caveats: tuple[str, ...]


def analyze_trend(series: SeriesResult) -> TrendResult:
    """Compute level change, percentage change, growth and a linear trend.

    - Level and percentage change run from the first to the last non-missing
      value; the result's period names those two periods.
    - Growth is the percentage change between each consecutive pair of
      periods; a pair with a missing value on either side is missing.
    - The trend is an ordinary least-squares line through the non-missing
      values, with x the number of periods since the series start. The slope
      is in the series unit per period, the intercept is the fitted value at
      the first period, and R² is the share of variance explained.
    - Percentage change from a base of zero is missing, never infinite.

    Raises :class:`AnalysisError` if the series mixes frequencies.
    """
    frequency = frequency_of(series)
    unit = series.unit
    observed = [(i, p.period, p.value) for i, p in enumerate(series.points) if p.value is not None]
    caveats: list[str] = []
    per = PER_PERIOD[frequency]
    params = {"series_id": series.id, "start": series.period.start, "end": series.period.end}

    def result(
        value: float | None,
        result_unit: str,
        name: str,
        description: str,
        period_labels: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> NumericResult:
        notes = list(notes or [])
        if value is None and not notes:
            notes = list(caveats) or ["Not enough values to compute this."]
        period = span(period_labels, frequency) if period_labels else series.period
        return NumericResult(
            value=value,
            unit=result_unit,
            period=period,
            geography=series.geography,
            method=Method(name=name, description=description, parameters=params),
            source=series.source,
            caveats=tuple(notes),
        )

    missing = len(series.points) - len(observed)
    if missing * 2 > len(series.points):
        caveats.append(f"{missing} of {len(series.points)} periods are missing.")
    if not observed:
        caveats.append("The series has no values, so no change, growth or trend can be computed.")
    elif len(observed) == 1:
        caveats.append(
            f"The series has a single value ({observed[0][1]}), so change, growth and trend "
            "cannot be computed."
        )

    # Level and percentage change.
    level = None
    if observed:
        level = result(
            observed[-1][2],
            unit,
            "latest_level",
            "The last non-missing value in the range.",
            [observed[-1][1]],
        )
    change: float | None = None
    pct: float | None = None
    pct_notes: list[str] = []
    used: list[str] | None = None
    if len(observed) >= 2:
        (_, first_label, first), (_, last_label, last) = observed[0], observed[-1]
        assert first is not None and last is not None
        used = [first_label, last_label]
        change = clean(last - first)
        if first == 0:
            pct_notes.append(
                f"The base value in {first_label} is zero, so percentage change is undefined."
            )
        else:
            pct = clean((last - first) / abs(first) * 100)
            if first < 0:
                pct_notes.append(
                    f"The base value in {first_label} is negative ({first}); the sign of a "
                    "percentage change from a negative base is hard to read."
                )
    level_change = result(
        change,
        change_unit(unit),
        "level_change",
        "Last non-missing value minus the first, over the periods in this result.",
        used,
    )
    percent_change = result(
        pct,
        "%",
        "percent_change",
        "Change from the first to the last non-missing value as a percentage of the absolute "
        "first value.",
        used,
        pct_notes or None,
    )

    # Period-over-period growth.
    growth: list[NumericResult] = []
    for before, after in zip(series.points, series.points[1:], strict=False):
        notes: list[str] = []
        value: float | None = None
        if before.value is None or after.value is None:
            gone = [p.period for p in (before, after) if p.value is None]
            notes.append(f"No growth: the value for {' and '.join(gone)} is missing.")
        elif before.value == 0:
            notes.append(f"No growth: the base value in {before.period} is zero.")
        else:
            value = clean((after.value - before.value) / abs(before.value) * 100)
            if before.value < 0:
                notes.append(
                    f"The base value in {before.period} is negative; the sign of the growth "
                    "rate is hard to read."
                )
        growth.append(
            result(
                value,
                "%",
                "period_growth",
                "Percentage change from one period to the next, relative to the absolute "
                "earlier value.",
                [before.period, after.period],
                notes,
            )
        )

    # Linear trend.
    slope = intercept = r2 = None
    trend_notes: list[str] = []
    if len(observed) >= 2:
        xs = [float(i) for i, _, _ in observed]
        ys = [float(v) for _, _, v in observed if v is not None]
        fit = statistics.linear_regression(xs, ys)
        slope, intercept = clean(fit.slope), clean(fit.intercept)
        if len(set(ys)) == 1:
            trend_notes.append("All values are equal, so R² is undefined.")
        else:
            r2 = clean(statistics.correlation(xs, ys) ** 2)
        if len(observed) == 2:
            trend_notes.append("A trend through two points cannot show statistical significance.")
    trend_desc = (
        "Ordinary least-squares line through the non-missing values, x being periods since "
        f"{series.period.start}."
    )
    trend_labels = [observed[0][1], observed[-1][1]] if len(observed) >= 2 else None
    slope_unit = f"{change_unit(unit)} per {per}"
    return TrendResult(
        series_id=series.id,
        level=level,
        level_change=level_change,
        percent_change=percent_change,
        growth=tuple(growth),
        slope=result(
            slope, slope_unit, "linear_trend_slope", trend_desc, trend_labels, trend_notes
        ),
        intercept=result(
            intercept,
            unit,
            "linear_trend_intercept",
            trend_desc + f" The intercept is the fitted value at {series.period.start}.",
            trend_labels,
            trend_notes,
        ),
        r_squared=result(
            r2, "ratio", "linear_trend_r_squared", trend_desc, trend_labels, trend_notes
        ),
        points_used=len(observed) if len(observed) >= 2 else 0,
        caveats=tuple(caveats),
    )

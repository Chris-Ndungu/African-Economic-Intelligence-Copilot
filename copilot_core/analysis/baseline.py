"""Compare a value with its own history."""

from __future__ import annotations

import statistics

from copilot_core.analysis.common import (
    AnalysisError,
    change_unit,
    clean,
    frequency_of,
    mean,
    single,
    span,
    stdev,
)
from copilot_core.models import BaselineResult, Method, SeriesResult

__all__ = ["DEFAULT_WINDOW", "MIN_VALUES", "compare_with_baseline"]

DEFAULT_WINDOW = 10
MIN_VALUES = 3


def compare_with_baseline(
    series: SeriesResult, target_period: str, window: int = DEFAULT_WINDOW
) -> BaselineResult:
    """Compare the value at ``target_period`` with the ``window`` periods before it.

    The window never includes the target. Missing values in the window are
    left out and counted. With fewer than three values the statistics are
    missing, with a caveat. Percentile rank is the percent of window values
    less than or equal to the target. The standard deviation is the sample
    standard deviation.

    Raises :class:`AnalysisError` if ``window`` is below 1, the target period
    is not in the series, or the target value is missing.
    """
    if window < 1:
        raise AnalysisError(f"window must be at least 1, got {window}")
    frequency = frequency_of(series)
    labels = [p.period for p in series.points]
    if target_period not in labels:
        raise AnalysisError(f"Period {target_period} is not in series {series.id}")
    index = labels.index(target_period)
    target = series.points[index].value
    if target is None:
        raise AnalysisError(f"The value for {target_period} is missing, so it has no baseline")

    caveats: list[str] = []
    window_points = series.points[max(0, index - window) : index]
    if len(window_points) < window:
        caveats.append(
            f"Only {len(window_points)} of the requested {window} periods exist before "
            f"{target_period}; the window uses what exists."
        )
    values = [float(p.value) for p in window_points if p.value is not None]
    missing = len(window_points) - len(values)
    if missing:
        caveats.append(f"{missing} missing values in the window were left out.")

    base = med = sd = z = pct_rank = diff = pct_diff = None
    if len(values) < MIN_VALUES:
        caveats.append(
            f"The window has {len(values)} values; at least {MIN_VALUES} are needed, so the "
            "baseline statistics are missing."
        )
    else:
        base = mean(values)
        med = float(statistics.median(values))
        sd = stdev(values)
        pct_rank = 100 * sum(v <= target for v in values) / len(values)
        diff = clean(target - base)
        if sd == 0:
            caveats.append("Every value in the window is equal, so the z-score is undefined.")
        else:
            z = clean((target - base) / sd)
        if base == 0:
            caveats.append("The baseline mean is zero, so the percentage difference is undefined.")
        else:
            pct_diff = clean((target - base) / abs(base) * 100)

    return BaselineResult(
        id=f"baseline:{series.metric}:{series.geography.country_code}:{target_period}",
        metric=series.metric,
        value=target,
        unit=series.unit,
        period=single(target_period, frequency),
        geography=series.geography,
        method=Method(
            name="historical_baseline",
            description=(
                f"Compares the value with the {window} periods before it (trailing window, "
                "target excluded). Baseline is the mean; standard deviation is the sample "
                "standard deviation; percentile rank is the percent of window values less than "
                f"or equal to the target. Difference is in {change_unit(series.unit)}."
            ),
            parameters={"window": window, "min_values": MIN_VALUES, "series_id": series.id},
        ),
        source=series.source,
        caveats=tuple(caveats),
        baseline_value=base,
        baseline_period=(
            span([p.period for p in window_points], frequency)
            if window_points
            else single(target_period, frequency)
        ),
        difference=diff,
        percent_difference=pct_diff,
        median=med,
        standard_deviation=sd,
        z_score=z,
        percentile_rank=pct_rank,
        window_count=len(values),
        missing_count=missing,
    )

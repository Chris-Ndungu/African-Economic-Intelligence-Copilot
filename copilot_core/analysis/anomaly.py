"""Flag unusual values in a series with a rolling z-score or IQR test."""

from __future__ import annotations

import statistics
from typing import Literal

from copilot_core.analysis.common import (
    AnalysisError,
    clean,
    frequency_of,
    mean,
    single,
    span,
    stdev,
)
from copilot_core.models import AnomalyPoint, AnomalyResult, AnomalyStatus, Method, SeriesResult

__all__ = ["DEFAULTS", "METHODS", "MIN_VALUES", "detect_anomalies"]

AnomalyMethod = Literal["rolling_zscore", "iqr"]
METHODS: tuple[str, ...] = ("rolling_zscore", "iqr")
DEFAULTS: dict[str, dict[str, float]] = {
    "rolling_zscore": {"window": 10, "threshold": 3.0},
    "iqr": {"window": 10, "threshold": 1.5},
}
MIN_VALUES = 3

DESCRIPTIONS = {
    "rolling_zscore": (
        "Each value is compared with the trailing window of earlier values (never itself or "
        "later values): z = (value - window mean) / window sample standard deviation. A value "
        "is flagged when |z| is at or above the threshold."
    ),
    "iqr": (
        "Each value is compared with the trailing window of earlier values (never itself or "
        "later values): fences are Q1 - k x IQR and Q3 + k x IQR, with quartiles by the "
        "inclusive method and k the threshold. The score is the distance beyond the nearest "
        "fence (negative inside the fences); a value is flagged when the score is above zero."
    ),
}


def detect_anomalies(
    series: SeriesResult,
    method: str = "rolling_zscore",
    window: int | None = None,
    threshold: float | None = None,
) -> AnomalyResult:
    """Score every value of ``series`` against the trailing window before it.

    Defaults: ``rolling_zscore`` with window 10 and threshold 3.0; ``iqr``
    with window 10 and multiplier (threshold) 1.5.

    A point is ``not_scored``, with a reason, when its value is missing,
    when fewer than ``window`` periods precede it, when its window has fewer
    than three values, or when the window's standard deviation or IQR is
    zero. Raises :class:`AnalysisError` for an unknown method, a window
    below 3 or a threshold of zero or less.
    """
    if method not in METHODS:
        raise AnalysisError(f"Unknown method {method!r}; supported methods: {', '.join(METHODS)}")
    window = int(DEFAULTS[method]["window"]) if window is None else window
    threshold = DEFAULTS[method]["threshold"] if threshold is None else threshold
    if window < 3:
        raise AnalysisError(f"window must be at least 3, got {window}")
    if not threshold > 0:
        raise AnalysisError(f"threshold must be greater than zero, got {threshold}")
    frequency = frequency_of(series)

    method_model = Method(
        name=method,
        description=DESCRIPTIONS[method],
        parameters={"window": window, "threshold": float(threshold), "min_values": MIN_VALUES},
    )
    caveats: list[str] = []
    if len(series.points) < window + 1:
        caveats.append(
            f"The series has {len(series.points)} periods, too short for a window of {window}: "
            f"at least {window + 1} are needed, so nothing was scored."
        )
    zero_spread: list[str] = []
    points: list[AnomalyPoint] = []
    for index, point in enumerate(series.points):
        window_points = series.points[max(0, index - window) : index]
        values = [float(p.value) for p in window_points if p.value is not None]
        fields: dict[str, object] = {
            "window": span([p.period for p in window_points], frequency) if window_points else None,
            "baseline_mean": None,
            "baseline_standard_deviation": None,
            "q1": None,
            "q3": None,
            "iqr": None,
            "expected_value": None,
        }
        status: AnomalyStatus = "not_scored"
        reason: str | None = None
        score: float | None = None
        direction: Literal["up", "down"] | None = None
        if point.value is None:
            reason = "The value is missing."
        elif index < window:
            reason = f"Only {index} earlier periods; a full window needs {window}."
        elif len(values) < MIN_VALUES:
            reason = (
                f"The window has {len(values)} non-missing values; at least {MIN_VALUES} are "
                "needed."
            )
        elif method == "rolling_zscore":
            centre, spread = mean(values), stdev(values)
            fields |= {
                "baseline_mean": centre,
                "baseline_standard_deviation": spread,
                "expected_value": centre,
            }
            if spread == 0:
                reason = "The window's standard deviation is zero, so a z-score is undefined."
                zero_spread.append(point.period)
            else:
                score = clean((point.value - centre) / spread)
                flagged = score is not None and abs(score) >= threshold
                status = "flagged" if flagged else "normal"
                if flagged and score is not None:
                    direction = "up" if score > 0 else "down"
        else:
            q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
            iqr = q3 - q1
            centre = float(statistics.median(values))
            fields |= {"q1": q1, "q3": q3, "iqr": iqr, "expected_value": centre}
            if iqr == 0:
                reason = "The window's interquartile range is zero, so the fences are undefined."
                zero_spread.append(point.period)
            else:
                lower, upper = q1 - threshold * iqr, q3 + threshold * iqr
                if point.value > upper:
                    score, direction = point.value - upper, "up"
                elif point.value < lower:
                    score, direction = lower - point.value, "down"
                else:
                    score = -min(upper - point.value, point.value - lower)
                score = clean(score)
                status = "flagged" if score is not None and score > 0 else "normal"
                if status != "flagged":
                    direction = None
        if status == "not_scored":
            score = None
        points.append(
            AnomalyPoint(
                value=point.value,
                unit=series.unit,
                period=single(point.period, frequency),
                geography=series.geography,
                method=method_model,
                source=series.source,
                caveats=(reason,) if reason else (),
                status=status,
                reason=reason,
                is_anomaly=None if status == "not_scored" else status == "flagged",
                score=score,
                threshold=float(threshold),
                direction=direction,
                **fields,
            )
        )

    if zero_spread:
        caveats.append(f"Not scored because the window had no spread: {', '.join(zero_spread)}.")
    scored = sum(p.status != "not_scored" for p in points)
    flagged_total = sum(p.status == "flagged" for p in points)
    if scored and not flagged_total:
        caveats.append(f"No anomalies: {scored} values were scored and none was flagged.")
    elif not scored:
        caveats.append("No value could be scored, so the series could not be checked.")
    return AnomalyResult(
        id=f"anomaly:{series.metric}:{series.geography.country_code}:{method}",
        metric=series.metric,
        unit=series.unit,
        period=series.period,
        geography=series.geography,
        method=method_model,
        source=series.source,
        caveats=tuple(caveats),
        scored_count=scored,
        flagged_count=flagged_total,
        points=tuple(points),
    )

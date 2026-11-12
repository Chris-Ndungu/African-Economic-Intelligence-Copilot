"""Build an investigation result from selections, without Gemini.

Phase 3 wires one path: a country and an indicator give a series and its
trend, which become an ``InvestigationResult`` that can be charted and
saved. Gemini's interpretation is added in Phase 4; until then it is
``None``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from copilot_core.analysis import TrendResult, analyze_trend
from copilot_core.data import DataService
from copilot_core.db import DataMode
from copilot_core.models import Finding, SeriesResult
from copilot_core.schemas import InvestigationRequest, InvestigationResult, PeriodRange

__all__ = ["TrendInvestigation", "run_trend_investigation"]


class TrendInvestigation:
    """The series, its trend and the result built from them."""

    def __init__(self, series: SeriesResult, trend: TrendResult, result: InvestigationResult):
        self.series = series
        self.trend = trend
        self.result = result


def _number(value: float) -> str:
    return f"{value:,.2f}"


def _finding(series: SeriesResult, trend: TrendResult) -> Finding:
    slope = trend.slope
    name = series.geography.country_name
    if slope.value is None:
        statement = f"No trend could be computed for {name}: {slope.caveats[0]}"
    else:
        direction = "rose" if slope.value > 0 else "fell" if slope.value < 0 else "was flat"
        statement = (
            f"{name}'s {series.metric} {direction} by {_number(abs(slope.value))} {slope.unit} "
            f"on average between {slope.period.start} and {slope.period.end} "
            f"(linear trend over {trend.points_used} values)."
        )
    return Finding(
        id=f"finding:trend:{series.metric}:{series.geography.country_code}",
        kind="trend",
        metric=series.metric,
        statement=statement,
        result_ids=(series.id,),
        **slope.model_dump(),
    )


def run_trend_investigation(
    data: DataService,
    country: str,
    indicator: str,
    start: str,
    end: str,
    data_mode: DataMode = "demo",
) -> TrendInvestigation:
    """Load one series, analyse its trend and build the investigation result."""
    series = data.get_series([country], indicator, start, end)[0]
    trend = analyze_trend(series)
    caveats = list(dict.fromkeys([*series.caveats, *trend.caveats]))
    if data_mode == "demo":
        caveats.insert(0, "Demo mode uses a bundled sample snapshot, not live data.")
    result = InvestigationResult(
        data_mode=data_mode,
        request=InvestigationRequest(
            question=None,
            investigation_type="trend",
            countries=[country],
            indicators=[indicator],
            period=PeriodRange(start=start, end=end),
        ),
        findings=[_finding(series, trend)],
        series=[series],
        comparisons=[],
        baselines=[],
        anomalies=[],
        interpretation=None,
        sources=[series.source],
        caveats=tuple(caveats),
        generated_at=datetime.now(UTC),
    )
    return TrendInvestigation(series, trend, result)

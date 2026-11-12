"""The analysis functions Gemini may call, and nothing else.

Each tool has a Pydantic argument model, whose JSON Schema is the tool's
declaration, and two steps: ``fetch`` loads data through the
:class:`~copilot_core.data.DataService`, and ``analyse`` calls the matching
function in :mod:`copilot_core.analysis`. Tools hold no analysis logic of
their own. A tool's ``data`` is its result model serialized to JSON, with the
series it was computed from, so a claim can cite either.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from copilot_core.analysis import (
    TrendResult,
    analyze_trend,
    compare_countries,
    compare_with_baseline,
    detect_anomalies,
)
from copilot_core.data import DataService
from copilot_core.llm.types import ToolDeclaration
from copilot_core.models import CountryCode, IndicatorCode, PeriodLabel, SeriesResult
from copilot_core.schemas import CoverageEntry, Selection

__all__ = [
    "TOOLS",
    "AnomalyArgs",
    "BaselineArgs",
    "CompareArgs",
    "CoverageArgs",
    "OutOfScopeError",
    "Tool",
    "TrendArgs",
    "declarations",
    "tool_names",
]


class _Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


Countries = Annotated[
    list[CountryCode], Field(min_length=1, max_length=10, description="ISO3 codes, e.g. KEN.")
]
Indicator = Annotated[IndicatorCode, Field(description="Indicator code, e.g. PCPIPCH.")]
Start = Annotated[PeriodLabel, Field(description="First year, e.g. 2015.")]
End = Annotated[PeriodLabel, Field(description="Last year, e.g. 2023.")]
Country = Annotated[CountryCode, Field(description="ISO3 code, e.g. KEN.")]


class CoverageArgs(_Args):
    countries: Countries
    indicators: list[IndicatorCode] | None = Field(
        default=None, description="Indicator codes; leave out for every indicator."
    )


class TrendArgs(_Args):
    country: Country
    indicator: Indicator
    start: Start
    end: End


class CompareArgs(_Args):
    countries: Annotated[
        list[CountryCode], Field(min_length=2, max_length=10, description="Two or more ISO3 codes.")
    ]
    indicator: Indicator
    start: Start
    end: End


class BaselineArgs(_Args):
    country: Country
    indicator: Indicator
    start: Start
    end: End
    target_period: PeriodLabel = Field(description="The year compared with the years before it.")
    window: int = Field(default=10, ge=1, le=50, description="Years before the target to use.")


class AnomalyArgs(_Args):
    country: Country
    indicator: Indicator
    start: Start
    end: End
    method: Literal["rolling_zscore", "iqr"] = Field(
        default="rolling_zscore", description="rolling_zscore (default) or iqr."
    )
    window: int | None = Field(
        default=None, ge=2, le=50, description="Earlier years each value is compared with."
    )
    threshold: float | None = Field(
        default=None, ge=0.1, description="z-score (default 3) or IQR multiplier (default 1.5)."
    )


class OutOfScopeError(ValueError):
    """The arguments ask for data outside the run's selection."""


Loaded = list[SeriesResult] | list[CoverageEntry]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[_Args]
    fetch: Callable[[Any, DataService], Loaded]
    analyse: Callable[[Any, Any], Any]

    def declaration(self) -> ToolDeclaration:
        return ToolDeclaration(
            name=self.name, description=self.description, parameters=self.parameters()
        )

    def parameters(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return schema


def _series(args: Any, data: DataService) -> list[SeriesResult]:
    countries = getattr(args, "countries", None) or [args.country]
    return data.get_series(countries, args.indicator, args.start, args.end)


def _dump(value: Any) -> Any:
    return TypeAdapter(type(value)).dump_python(value, mode="json")


def _with_series(result: Any, series: Sequence[SeriesResult]) -> dict[str, Any]:
    return {"result": _dump(result), "series": [_dump(s) for s in series]}


def _trend(args: TrendArgs, series: list[SeriesResult]) -> dict[str, Any]:
    trend: TrendResult = analyze_trend(series[0])
    return _with_series(trend, series)


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            name="get_coverage",
            description=(
                "Lists, per country and indicator, the first and last year with data, how many "
                "values exist and how many are missing. Use it first to check what data exists "
                "before analysing, and to report data gaps."
            ),
            args_model=CoverageArgs,
            fetch=lambda a, d: d.list_coverage(a.countries, a.indicators),
            analyse=lambda a, entries: {"result": {"entries": [_dump(e) for e in entries]}},
        ),
        Tool(
            name="analyze_trend",
            description=(
                "Computes the level change, percentage change, year-on-year growth and linear "
                "trend (slope, r-squared) of one country's indicator between two years. Use it "
                "to describe how an indicator moved over a period."
            ),
            args_model=TrendArgs,
            fetch=_series,
            analyse=_trend,
        ),
        Tool(
            name="compare_countries",
            description=(
                "Compares one indicator across two or more countries over the years they all "
                "have values: mean, latest value, change and rank per country. Use it to compare "
                "countries."
            ),
            args_model=CompareArgs,
            fetch=_series,
            analyse=lambda a, s: _with_series(compare_countries(s), s),
        ),
        Tool(
            name="compare_with_baseline",
            description=(
                "Compares one year's value with the mean and spread of the years before it "
                "(difference, z-score, percentile rank). Use it to say whether a year was "
                "unusual for that country."
            ),
            args_model=BaselineArgs,
            fetch=_series,
            analyse=lambda a, s: _with_series(
                compare_with_baseline(s[0], a.target_period, a.window), s
            ),
        ),
        Tool(
            name="detect_anomalies",
            description=(
                "Scores every value of one country's indicator against the years before it "
                "with a rolling z-score or IQR test and flags outliers, with direction. Use it "
                "to find unusual years."
            ),
            args_model=AnomalyArgs,
            fetch=_series,
            analyse=lambda a, s: _with_series(
                detect_anomalies(s[0], a.method, a.window, a.threshold), s
            ),
        ),
    )
}


def tool_names() -> list[str]:
    return list(TOOLS)


def declarations() -> list[ToolDeclaration]:
    return [tool.declaration() for tool in TOOLS.values()]


def check_scope(args: _Args, scope: Selection | None) -> None:
    """Raise :class:`OutOfScopeError` if ``args`` ask for data outside ``scope``."""
    if scope is None:
        return
    countries = getattr(args, "countries", None) or [getattr(args, "country", None)]
    outside = [c for c in countries if c is not None and c not in scope.countries]
    if outside:
        raise OutOfScopeError(
            f"Countries {', '.join(outside)} are outside the selection "
            f"({', '.join(scope.countries)})"
        )
    indicators = getattr(args, "indicators", None) or [getattr(args, "indicator", None)]
    if any(i is not None and i != scope.indicator for i in indicators):
        raise OutOfScopeError(f"Only indicator {scope.indicator} is in the selection")
    for name in ("start", "end", "target_period"):
        label = getattr(args, name, None)
        if label is not None and not scope.start <= label <= scope.end:
            raise OutOfScopeError(
                f"{name} {label} is outside the selected period {scope.start} to {scope.end}"
            )


def count_points(loaded: Loaded) -> int:
    """Data points a fetch loaded: series values, or coverage rows."""
    return sum(len(item.points) if isinstance(item, SeriesResult) else 1 for item in loaded)

"""Turn a ``ChartSpec`` and the results it points to into a Plotly figure.

The figure is a plain ``dict`` (``data`` and ``layout``) that Plotly.js draws
in the browser; no Plotly Python package is needed, and the PDF export
(#33) uses the same function. Nothing here computes a number: values are
copied from the results, missing values stay ``None`` (``null`` in JSON, so
the line breaks), and hover text is formatted with
:func:`copilot_core.formatting.format_number`.

A spec's ``kind`` and the result's tool pick the chart:

- ``line`` draws the series of the result (``timeseries``), or, for a
  ``detect_anomalies`` result, the anomaly chart
- ``bar`` draws a comparison, one line per country on one axis
- ``table`` (coverage) has no figure
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from copilot_core.formatting import format_number
from copilot_core.models import AnomalyResult, SeriesResult
from copilot_core.schemas import ChartSpec, ToolResult

__all__ = [
    "ChartView",
    "FigureError",
    "MixedUnitsError",
    "TableCell",
    "TableRow",
    "TableView",
    "anomaly_figure",
    "build_chart",
    "build_figure",
    "line_figure",
]

ChartType = Literal["timeseries", "comparison", "anomaly"]

# Colours with at least 4.5:1 contrast against the white plot background.
COLOURS = ("#0b6e4f", "#1f5fbf", "#b3360f", "#7a3b9e", "#8a6100", "#0f6f8c", "#a31f6b", "#4d4d4d")
DASHES = ("solid", "dash", "dot", "dashdot", "longdash", "longdashdot")
SYMBOLS = ("circle", "square", "diamond", "cross", "x", "star")
TEXT_COLOUR = "#1f2328"
GAP_NOTE = "Gaps in a line are missing data, not zero."


class FigureError(ValueError):
    """The results cannot be drawn."""


class MixedUnitsError(FigureError):
    """The results use different units and cannot share one axis."""

    def __init__(self, units: Sequence[str]) -> None:
        self.units = tuple(units)
        super().__init__(
            "These results use different units and cannot share one axis: "
            + ", ".join(self.units)
            + "."
        )


# --- Views the templates render ---------------------------------------------


@dataclass(frozen=True)
class TableCell:
    value: float | None
    unit: str


@dataclass(frozen=True)
class TableRow:
    period: str
    cells: list[TableCell]


@dataclass(frozen=True)
class TableView:
    columns: list[tuple[str, str]]  # (label, unit)
    rows: list[TableRow]


@dataclass(frozen=True)
class ChartView:
    """Everything the chart and table partials print."""

    kind: ChartType | None
    title: str
    figure: dict[str, Any] | None = None
    error: str | None = None
    empty: bool = False
    caveats: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    table: TableView | None = None
    gap_note: str = GAP_NOTE


# --- Figure builders ---------------------------------------------------------


def _label(series: SeriesResult) -> str:
    return f"{series.geography.country_name} ({series.geography.country_code})"


def _single_unit(units: Sequence[str]) -> str:
    distinct = list(dict.fromkeys(units))
    if len(distinct) > 1:
        raise MixedUnitsError(distinct)
    return distinct[0] if distinct else ""


def _layout(title: str, unit: str, frequency: str) -> dict[str, Any]:
    return {
        "title": {"text": title, "font": {"size": 14, "color": TEXT_COLOUR}, "x": 0.01},
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#ffffff",
        "font": {"color": TEXT_COLOUR},
        "xaxis": {"title": {"text": f"Period ({frequency})"}, "type": "category"},
        "yaxis": {"title": {"text": unit}, "zeroline": False},
        "legend": {"orientation": "h", "y": -0.3},
        "margin": {"l": 64, "r": 16, "t": 48, "b": 40},
        "hovermode": "closest",
        "autosize": True,
    }


def _has_values(values: Sequence[float | None]) -> bool:
    return any(v is not None for v in values)


def line_figure(series: Sequence[SeriesResult], title: str) -> dict[str, Any]:
    """One line per country, on one axis titled with the unit.

    Raises :class:`MixedUnitsError` if the series use different units.
    """
    unit = _single_unit([s.unit for s in series])
    traces: list[dict[str, Any]] = []
    for index, s in enumerate(series):
        periods = [p.period for p in s.points]
        values = [p.value for p in s.points]
        traces.append(
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": _label(s),
                "x": periods,
                "y": values,
                "connectgaps": False,
                "line": {
                    "color": COLOURS[index % len(COLOURS)],
                    "dash": DASHES[index % len(DASHES)],
                    "width": 2,
                },
                "marker": {"symbol": SYMBOLS[index % len(SYMBOLS)], "size": 6},
                "text": [
                    f"{_label(s)}, {period}: {format_number(value, s.unit)} {s.unit}"
                    if value is not None
                    else f"{_label(s)}, {period}: missing"
                    for period, value in zip(periods, values, strict=True)
                ],
                "hovertemplate": "%{text}<extra></extra>",
            }
        )
    frequency = series[0].period.frequency if series else "annual"
    return {"data": traces, "layout": _layout(title, unit, frequency)}


def anomaly_figure(result: AnomalyResult, title: str) -> dict[str, Any]:
    """The series line, plus a marker on each flagged point.

    ``triangle-up`` marks a value above its baseline and ``triangle-down`` one
    below it, so direction is told by shape and not by colour alone.
    """
    periods = [p.period.start for p in result.points]
    values = [p.value for p in result.points]
    traces: list[dict[str, Any]] = [
        {
            "type": "scatter",
            "mode": "lines",
            "name": f"{result.geography.country_name} ({result.geography.country_code})",
            "x": periods,
            "y": values,
            "connectgaps": False,
            "line": {"color": COLOURS[0], "dash": "solid", "width": 2},
            "hoverinfo": "skip",
        }
    ]
    for direction, symbol, colour, name in (
        ("up", "triangle-up", COLOURS[2], "Flagged: above baseline"),
        ("down", "triangle-down", COLOURS[1], "Flagged: below baseline"),
    ):
        flagged = [p for p in result.points if p.status == "flagged" and p.direction == direction]
        if not flagged:
            continue
        traces.append(
            {
                "type": "scatter",
                "mode": "markers",
                "name": name,
                "x": [p.period.start for p in flagged],
                "y": [p.value for p in flagged],
                "marker": {"symbol": symbol, "size": 12, "color": colour},
                "text": [
                    f"Period: {p.period.start}<br>Value: {format_number(p.value, result.unit)} "
                    f"{result.unit}<br>Statistic: {format_number(p.score)}<br>"
                    f"Threshold: {format_number(p.threshold)}<br>Method: {result.method.name}"
                    for p in flagged
                ],
                "hovertemplate": "%{text}<extra></extra>",
            }
        )
    return {"data": traces, "layout": _layout(title, result.unit, result.period.frequency)}


# --- From a spec and its results ----------------------------------------------


def _find(spec: ChartSpec, results: Sequence[ToolResult]) -> ToolResult:
    for result in results:
        if result.result_id == spec.result_id:
            return result
    raise FigureError(f"The result {spec.result_id!r} that this chart draws is not available.")


def _series_of(spec: ChartSpec, result: ToolResult) -> list[SeriesResult]:
    wanted = set(spec.series_ids)
    return [
        SeriesResult.model_validate(raw)
        for raw in result.data.get("series", [])
        if not wanted or raw.get("id") in wanted
    ]


def chart_type(spec: ChartSpec, result: ToolResult) -> ChartType:
    if spec.kind == "table":
        raise FigureError("A coverage table has no figure.")
    if spec.kind == "bar":
        return "comparison"
    return "anomaly" if result.tool == "detect_anomalies" else "timeseries"


def build_figure(spec: ChartSpec, results: Sequence[ToolResult]) -> dict[str, Any]:
    """The Plotly figure (``data`` and ``layout``) for ``spec``.

    Raises :class:`FigureError`, or :class:`MixedUnitsError` when the series
    use different units, instead of returning a figure.
    """
    result = _find(spec, results)
    kind = chart_type(spec, result)
    if kind == "anomaly":
        return anomaly_figure(AnomalyResult.model_validate(result.data["result"]), spec.title)
    return line_figure(_series_of(spec, result), spec.title)


def _table(columns: list[tuple[str, str]], by_column: list[dict[str, float | None]]) -> TableView:
    periods = sorted({p for column in by_column for p in column})
    rows = [
        TableRow(
            period,
            [
                TableCell(column.get(period), unit)
                for column, (_, unit) in zip(by_column, columns, strict=True)
            ],
        )
        for period in periods
    ]
    return TableView(columns, rows)


def build_chart(spec: ChartSpec, results: Sequence[ToolResult]) -> ChartView:
    """Everything the chart and table partials need for ``spec``.

    A result with no values gives an empty view with the result's caveats; a
    result that cannot be drawn gives a view with ``error`` set.
    """
    try:
        result = _find(spec, results)
        kind = chart_type(spec, result)
        if kind == "anomaly":
            anomaly = AnomalyResult.model_validate(result.data["result"])
            names = [anomaly.source.name]
            caveats = list(anomaly.caveats)
            columns = [(anomaly.geography.country_name, anomaly.unit)]
            by_column = [{p.period.start: p.value for p in anomaly.points}]
            present = _has_values([p.value for p in anomaly.points])
        else:
            series = _series_of(spec, result)
            _single_unit([s.unit for s in series])
            names = [s.source.name for s in series]
            caveats = [c for s in series for c in s.caveats]
            columns = [(s.geography.country_name, s.unit) for s in series]
            by_column = [{p.period: p.value for p in s.points} for s in series]
            present = any(_has_values([p.value for p in s.points]) for s in series)
        figure = build_figure(spec, results) if present else None
    except FigureError as exc:  # includes MixedUnitsError
        return ChartView(kind=None, title=spec.title, error=str(exc))
    return ChartView(
        kind=kind,
        title=spec.title,
        figure=figure,
        empty=not present,
        caveats=list(dict.fromkeys(caveats)),
        sources=list(dict.fromkeys(names)),
        table=_table(columns, by_column) if present else None,
    )

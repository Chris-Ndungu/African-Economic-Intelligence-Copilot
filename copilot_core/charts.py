"""Chart specs for the tool results an interpretation cites.

One :class:`~copilot_core.schemas.ChartSpec` per cited result, in the order
findings cite them. The figure builder that draws a spec arrives with #21.
"""

from __future__ import annotations

from collections.abc import Sequence

from copilot_core.interpretation import VerifiedInterpretation
from copilot_core.schemas import ChartSpec, ToolResult

__all__ = ["chart_specs"]

TITLES = {
    "get_coverage": "Data coverage",
    "analyze_trend": "Trend",
    "compare_countries": "Comparison",
    "compare_with_baseline": "Against the historical baseline",
    "detect_anomalies": "Anomalies",
}


def _spec(result: ToolResult) -> ChartSpec:
    series = result.data.get("series", [])
    args = result.arguments
    countries = args.get("countries") or [args.get("country")]
    where = ", ".join(str(c) for c in countries if c)
    indicator = args.get("indicator")
    span = f"{args['start']} to {args['end']}" if "start" in args and "end" in args else ""
    title = " · ".join(
        part for part in (TITLES.get(result.tool, result.tool), indicator, where, span) if part
    )
    kind = (
        "table"
        if result.tool == "get_coverage"
        else "bar"
        if result.tool == "compare_countries"
        else "line"
    )
    return ChartSpec(
        id=f"chart:{result.result_id}",
        kind=kind,
        title=title,
        result_id=result.result_id,
        unit=series[0]["unit"] if series else None,
        series_ids=[s["id"] for s in series],
    )


def chart_specs(
    interpretation: VerifiedInterpretation, results: Sequence[ToolResult]
) -> list[ChartSpec]:
    by_id = {r.result_id: r for r in results}
    cited = dict.fromkeys(rid for f in interpretation.findings for rid in f.result_ids)
    return [_spec(by_id[rid]) for rid in cited if rid in by_id]

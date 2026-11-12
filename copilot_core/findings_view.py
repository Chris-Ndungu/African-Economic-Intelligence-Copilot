"""What the results view prints for one saved investigation.

:func:`build_results_view` turns a saved :class:`~copilot_core.schemas.Investigation`
into plain data the ``partials/results.html`` template renders. It computes no
numbers: every value, method, parameter and source comes from the stored
result, and the charts come from :func:`copilot_core.figures.build_chart`.

Cards are sorted by what they claim:

- ``facts``: findings computed in Python, and interpretation findings labelled
  ``fact`` whose numbers all checked out
- ``unverified``: interpretation findings the validator could not verify,
  never shown as plain facts
- ``hypotheses``: interpretation findings labelled ``hypothesis``
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from pydantic import ValidationError

from copilot_core.error_messages import error_message, unsupported_message
from copilot_core.figures import ChartView, build_chart
from copilot_core.history import (
    investigation_question,
    investigation_selection,
    iso_utc,
    selection_summary,
    utc_text,
)
from copilot_core.interpretation import VerifiedFinding
from copilot_core.models import Finding, SourceRef
from copilot_core.schemas import ChartSpec, Investigation, Selection, ToolResult

__all__ = [
    "ASSOCIATION_NOTE",
    "ChartBlock",
    "FindingCard",
    "MethodView",
    "NumberView",
    "ResultsView",
    "SourceView",
    "build_results_view",
]

ASSOCIATION_NOTE = "Association does not show cause"

UNTRACED_REASON = "A number in this claim could not be traced to a computed result."

DATA_MODE_LABELS = {
    "demo": "Demo data (bundled sample snapshot, not live data)",
    "live": "Live data",
}


@dataclass(frozen=True)
class NumberView:
    value: float | None
    unit: str
    label: str | None = None


@dataclass(frozen=True)
class SourceView:
    id: str
    name: str
    provider: str | None
    url: str | None
    last_updated: date | None


@dataclass(frozen=True)
class MethodView:
    name: str
    description: str
    parameters: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FindingCard:
    id: str
    kind: str
    statement: str
    hypothesis: bool = False
    unverified: bool = False
    unverified_reasons: list[str] = field(default_factory=list)
    relationship: bool = False
    numbers: list[NumberView] = field(default_factory=list)
    methods: list[MethodView] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    sources: list[SourceView] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    missing_notes: list[str] = field(default_factory=list)
    chart_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChartBlock:
    id: str
    view: ChartView


@dataclass(frozen=True)
class ResultsView:
    investigation_id: str
    status: str
    heading: str
    question: str | None
    countries: list[str]
    indicators: list[str]
    period: str | None
    data_mode: str
    data_mode_label: str
    run_iso: str
    run_text: str
    error: str | None = None
    unfinished: bool = False
    summary: str | None = None
    unsupported_reason: str | None = None
    unsupported_text: str | None = None
    facts: list[FindingCard] = field(default_factory=list)
    unverified: list[FindingCard] = field(default_factory=list)
    hypotheses: list[FindingCard] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    charts: list[ChartBlock] = field(default_factory=list)
    selection: Selection | None = None

    @property
    def has_findings(self) -> bool:
        return bool(self.facts or self.unverified or self.hypotheses)


def _unique(items: Iterable[Any]) -> list[Any]:
    return list(dict.fromkeys(items))


def _text(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value)
    return str(value)


def _method_view(name: str, description: str, parameters: Any) -> MethodView:
    items = parameters.items() if hasattr(parameters, "items") else []
    return MethodView(name, description, tuple((str(k), _text(v)) for k, v in items))


def _source_view(source: SourceRef) -> SourceView:
    return SourceView(
        id=source.id,
        name=source.name,
        provider=source.provider,
        url=str(source.url) if source.url else None,
        last_updated=source.last_updated,
    )


@dataclass
class _Evidence:
    """What the tool results a finding cites say about method, source and gaps."""

    methods: list[MethodView] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    sources: list[SourceView] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    missing_notes: list[str] = field(default_factory=list)
    metrics: set[str] = field(default_factory=set)


def _entries(result: ToolResult) -> list[dict[str, Any]]:
    entries = [raw for raw in result.data.get("series", []) or [] if isinstance(raw, dict)]
    single = result.data.get("result")
    if isinstance(single, dict):
        entries.append(single)
    return entries


def _has_missing(entry: dict[str, Any]) -> bool:
    points = entry.get("points")
    if isinstance(points, list) and any(
        isinstance(p, dict) and p.get("value") is None for p in points
    ):
        return True
    return "value" in entry and entry["value"] is None


def _evidence(result_ids: Sequence[str], by_id: dict[str, ToolResult]) -> _Evidence:
    evidence = _Evidence()
    methods: list[MethodView] = []
    sources: dict[str, SourceView] = {}
    for result_id in result_ids:
        result = by_id.get(result_id)
        if result is None:
            continue
        evidence.tools.append(result.tool)
        for key in ("indicator", "indicators"):
            value = result.arguments.get(key)
            evidence.metrics.update(value if isinstance(value, list) else [value] if value else [])
        for entry in _entries(result):
            if isinstance(entry.get("metric"), str):
                evidence.metrics.add(entry["metric"])
            method = entry.get("method")
            if isinstance(method, dict) and method.get("name"):
                methods.append(
                    _method_view(
                        str(method["name"]),
                        str(method.get("description", "")),
                        method.get("parameters") or {},
                    )
                )
            try:
                source = SourceRef.model_validate(entry["source"]) if "source" in entry else None
            except ValidationError:
                source = None
            if source is not None:
                sources.setdefault(source.id, _source_view(source))
            notes = [str(c) for c in entry.get("caveats") or []]
            (evidence.missing_notes if _has_missing(entry) else evidence.caveats).extend(notes)
    evidence.methods = _unique(methods)
    evidence.tools = _unique(evidence.tools)
    evidence.sources = list(sources.values())
    evidence.caveats = _unique(evidence.caveats)
    evidence.missing_notes = _unique(evidence.missing_notes)
    return evidence


def _is_relationship(evidence: _Evidence) -> bool:
    return len(evidence.metrics) > 1 or any(
        word in tool for tool in evidence.tools for word in ("correlat", "relationship", "lag")
    )


def _python_card(
    finding: Finding, by_id: dict[str, ToolResult], chart_ids: list[str]
) -> FindingCard:
    evidence = _evidence(finding.result_ids, by_id)
    evidence.metrics.add(finding.metric)
    own = _method_view(finding.method.name, finding.method.description, finding.method.parameters)
    own_missing = list(finding.caveats) if finding.value is None else []
    return FindingCard(
        id=finding.id,
        kind=finding.kind.replace("_", " "),
        statement=finding.statement,
        relationship=_is_relationship(evidence),
        numbers=[NumberView(finding.value, finding.unit)],
        methods=_unique([own, *evidence.methods]),
        tools=evidence.tools,
        sources=list(
            {s.id: s for s in [*evidence.sources[::-1], _source_view(finding.source)]}.values()
        )[::-1],
        caveats=[] if own_missing else _unique([*finding.caveats, *evidence.caveats]),
        missing_notes=_unique([*own_missing, *evidence.missing_notes]),
        chart_ids=chart_ids,
    )


def _interpretation_card(
    index: int, finding: VerifiedFinding, by_id: dict[str, ToolResult], chart_ids: list[str]
) -> FindingCard:
    evidence = _evidence(finding.result_ids, by_id)
    unverified = finding.verification == "unverified"
    reasons = _unique(
        [*finding.reasons, *(c.reason for c in finding.checks if not c.verified and c.reason)]
    )
    if unverified and not reasons:
        reasons = [UNTRACED_REASON]
    return FindingCard(
        id=f"interpretation-{index}",
        kind="hypothesis" if finding.label == "hypothesis" else "fact",
        statement=finding.statement,
        hypothesis=finding.label == "hypothesis",
        unverified=unverified,
        unverified_reasons=reasons if unverified else [],
        relationship=_is_relationship(evidence),
        numbers=[
            NumberView(n.value, n.unit, f"{n.result_id} · {n.field}") for n in finding.numbers
        ],
        methods=evidence.methods,
        tools=evidence.tools,
        sources=evidence.sources,
        caveats=evidence.caveats,
        missing_notes=evidence.missing_notes,
        chart_ids=chart_ids,
    )


def _countries(investigation: Investigation) -> list[str]:
    names: dict[str, str] = {}
    result = investigation.result
    if result is not None:
        geographies = [s.geography for s in result.series] + [f.geography for f in result.findings]
        for geography in geographies:
            names.setdefault(geography.country_code, geography.country_name)
        for tool_result in result.tool_results:
            for entry in _entries(tool_result):
                raw = entry.get("geography")
                if isinstance(raw, dict) and "country_code" in raw:
                    names.setdefault(raw["country_code"], raw.get("country_name", ""))
    selection = investigation_selection(investigation)
    codes = list(selection.countries) if selection else list(names)
    return [f"{names[c]} ({c})" if names.get(c) else c for c in codes]


def _chart_ids(result_ids: Sequence[str], specs: Sequence[ChartSpec]) -> list[str]:
    wanted = set(result_ids)
    return [spec.id for spec in specs if spec.result_id in wanted]


def build_results_view(investigation: Investigation) -> ResultsView:
    """The data the results partial renders for ``investigation``."""
    selection = investigation_selection(investigation)
    question = investigation_question(investigation)
    summary = (
        selection_summary(
            selection.indicator, list(selection.countries), selection.start, selection.end
        )
        if selection
        else None
    )
    view = ResultsView(
        investigation_id=str(investigation.id),
        status=investigation.status,
        heading=question or summary or investigation.title,
        question=question,
        countries=_countries(investigation),
        indicators=[selection.indicator] if selection else [],
        period=f"{selection.start}–{selection.end}" if selection else None,
        data_mode=investigation.data_mode,
        data_mode_label=DATA_MODE_LABELS.get(investigation.data_mode, investigation.data_mode),
        run_iso=iso_utc(investigation.created_at),
        run_text=utc_text(investigation.created_at),
        selection=selection,
    )
    if investigation.status == "failed":
        code = investigation.error.code if investigation.error else None
        return replace(view, error=error_message(code).text)
    result = investigation.result
    if result is None:
        return replace(view, unfinished=True)

    by_id = {r.result_id: r for r in result.tool_results}
    blocks = [ChartBlock(spec.id, build_chart(spec, result.tool_results)) for spec in result.charts]
    facts = [
        _python_card(f, by_id, _chart_ids(f.result_ids, result.charts)) for f in result.findings
    ]
    unverified: list[FindingCard] = []
    hypotheses: list[FindingCard] = []
    interpretation = result.interpretation
    if interpretation is not None:
        for index, finding in enumerate(interpretation.findings, start=1):
            card = _interpretation_card(
                index, finding, by_id, _chart_ids(finding.result_ids, result.charts)
            )
            if card.hypothesis:
                hypotheses.append(card)
            elif card.unverified:
                unverified.append(card)
            else:
                facts.append(card)
    return replace(
        view,
        summary=interpretation.summary if interpretation else None,
        unsupported_reason=interpretation.unsupported_reason if interpretation else None,
        unsupported_text=(
            unsupported_message(interpretation.unsupported_reason)
            if interpretation and interpretation.unsupported_reason
            else None
        ),
        facts=facts,
        unverified=unverified,
        hypotheses=hypotheses,
        caveats=_unique([*result.caveats, *(interpretation.caveats if interpretation else [])]),
        data_gaps=list(interpretation.data_gaps) if interpretation else [],
        charts=blocks,
    )

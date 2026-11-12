"""Compare one indicator across several countries."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from copilot_core.analysis.common import AnalysisError, frequency_of, mean, span, stdev
from copilot_core.models import ComparisonEntry, ComparisonResult, Method, SeriesResult

__all__ = ["compare_countries"]

METHOD = Method(
    name="compare_shared_periods",
    description=(
        "Series are aligned on the periods they all share. For each country the mean, median, "
        "minimum, maximum and sample standard deviation are computed over its non-missing "
        "values in those periods. Countries are ranked by their value at the latest shared "
        "period in which any country has a value, highest first; equal values share a rank. "
        "A rank is a position, not a judgement of better or worse."
    ),
    parameters={"order": "highest_first", "ties": "shared_rank"},
)


def compare_countries(series: Sequence[SeriesResult]) -> ComparisonResult:
    """Compare two or more series of the same indicator.

    Raises :class:`AnalysisError` when fewer than two series are given, when
    they are for different indicators, or when their units or frequencies
    differ; nothing is converted silently.
    """
    if len(series) < 2:
        raise AnalysisError(f"A comparison needs at least two series, got {len(series)}")
    metrics = {s.metric for s in series}
    if len(metrics) > 1:
        raise AnalysisError(f"Series are for different indicators: {', '.join(sorted(metrics))}")
    for attribute, read in (("unit", lambda s: s.unit), ("frequency", frequency_of)):
        if len({read(s) for s in series}) > 1:
            listed = ", ".join(f"{s.geography.country_code}: {read(s)}" for s in series)
            raise AnalysisError(f"Series have different {attribute}s ({listed})")

    frequency = frequency_of(series[0])
    shared = sorted(set.intersection(*({p.period for p in s.points} for s in series)))
    values = [{p.period: p.value for p in s.points} for s in series]
    with_value = [label for label in shared if any(v.get(label) is not None for v in values)]
    ranking_period = with_value[-1] if with_value else None
    caveats: list[str] = []
    if not shared:
        caveats.append("The series share no periods, so there is no comparison or ranking.")
    elif ranking_period is None:
        caveats.append("No country has a value in the shared periods, so there is no ranking.")

    # Competition ranking: equal values share a rank, the next rank skips.
    at_ranking: list[float] = []
    if ranking_period is not None:
        at_ranking = [v for by_period in values if (v := by_period.get(ranking_period)) is not None]
    ranked_values = sorted(at_ranking, reverse=True)
    ranks: dict[float, int] = {}
    for position, value in enumerate(ranked_values, start=1):
        ranks.setdefault(value, position)

    entries: list[ComparisonEntry] = []
    for s, by_period in zip(series, values, strict=True):
        observed = [p.period for p in s.points if p.value is not None]
        in_shared = [by_period[label] for label in shared if by_period.get(label) is not None]
        shared_values = [float(v) for v in in_shared if v is not None]
        excluded = [label for label in observed if label not in set(shared)]
        notes: list[str] = []
        current = by_period.get(ranking_period) if ranking_period else None
        if not shared_values:
            status = "no_data"
            notes.append(
                f"{s.geography.country_name} has no value in the shared periods, so it is "
                "not ranked."
            )
        elif current is None:
            status = "unranked"
            notes.append(
                f"{s.geography.country_name} has no value for {ranking_period}, so it is not "
                "ranked."
            )
        else:
            status = "ranked"
        if excluded:
            notes.append(f"Left out because not every country has them: {', '.join(excluded)}.")
        if len(shared_values) == 1:
            notes.append("One value in the shared periods, so the standard deviation is undefined.")
        entries.append(
            ComparisonEntry(
                value=current,
                unit=s.unit,
                period=span(shared, frequency) if shared else s.period,
                geography=s.geography,
                method=METHOD,
                source=s.source,
                caveats=tuple(notes),
                rank=ranks[current] if status == "ranked" and current is not None else None,
                status=status,
                first_period=observed[0] if observed else None,
                last_period=observed[-1] if observed else None,
                observation_count=len(observed),
                shared_count=len(shared_values),
                excluded_periods=tuple(excluded),
                mean=mean(shared_values) if shared_values else None,
                median=float(statistics.median(shared_values)) if shared_values else None,
                minimum=min(shared_values) if shared_values else None,
                maximum=max(shared_values) if shared_values else None,
                standard_deviation=stdev(shared_values) if len(shared_values) >= 2 else None,
            )
        )

    order = {"ranked": 0, "unranked": 1, "no_data": 2}
    entries.sort(key=lambda e: (order[e.status], e.rank or 0, e.geography.country_code))
    return ComparisonResult(
        id=f"comparison:{series[0].metric}:"
        + "-".join(sorted(s.geography.country_code for s in series)),
        metric=series[0].metric,
        method=METHOD,
        shared_periods=tuple(shared),
        ranking_period=ranking_period,
        caveats=tuple(caveats),
        entries=tuple(entries),
    )

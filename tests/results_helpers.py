"""Fixture investigations for the results view and history tests."""

import uuid
from datetime import UTC, date, datetime

from copilot_core.interpretation import (
    CitedNumber,
    NumberCheck,
    VerifiedFinding,
    VerifiedInterpretation,
)
from copilot_core.models import Finding, Geography, Method, Period, SourceRef
from copilot_core.schemas import (
    ChartSpec,
    Investigation,
    InvestigationError,
    InvestigationRequest,
    InvestigationResult,
    InvestigationRun,
    LLMUsage,
    PeriodRange,
    Selection,
    ToolResult,
)
from tests.helpers import make_series

WHEN = datetime(2026, 11, 12, 10, 30, tzinfo=UTC)
SOURCE = SourceRef(
    id="fact_macroeconomic_indicators",
    name="IMF DataMapper",
    provider="IMF",
    url=None,
    last_updated=date(2026, 1, 15),
)


def make_finding(statement="Inflation rose.", value=4.3, caveats=(), result_ids=("r1",)):
    return Finding(
        id="f1",
        kind="trend",
        metric="PCPIPCH",
        statement=statement,
        result_ids=result_ids,
        value=value,
        unit="%",
        period=Period(start="2018", end="2020", frequency="annual"),
        geography=Geography(country_code="KEN", country_name="Kenya"),
        method=Method(name="linear_trend", description="Least squares.", parameters={"k": 2}),
        source=SOURCE,
        caveats=caveats,
    )


def make_ifinding(statement, label="fact", verification="verified", reasons=(), result_ids=("r1",)):
    check = NumberCheck(
        text="4.3", value=4.3, result_id="r1", field="result.value", verified=False, reason="x"
    )
    return VerifiedFinding(
        statement=statement,
        label=label,
        result_ids=list(result_ids),
        numbers=[CitedNumber(value=4.3, unit="%", result_id="r1", field="result.value")],
        verification=verification,
        checks=[check] if verification == "unverified" and reasons else [],
        reasons=list(reasons),
    )


def make_interpretation(findings, summary="Summary text.", unsupported=None):
    return VerifiedInterpretation(
        summary=summary,
        findings=findings,
        caveats=[],
        data_gaps=[],
        unsupported_reason=unsupported,
        summary_checks=[],
        verified_count=1,
        unverified_count=0,
        model="stub",
        prompt_version="interpret_v1",
    )


def make_result(findings=(), interpretation=None, series=None, caveats=(), question="Why?"):
    series = series or make_series([1.0, None, 3.0])
    tool_result = ToolResult(
        result_id="r1",
        tool="analyze_trend",
        arguments={"indicator": "PCPIPCH"},
        data={"series": [series.model_dump(mode="json")]},
    )
    return InvestigationResult(
        data_mode="demo",
        request=InvestigationRequest(
            question=question,
            investigation_type="trend",
            countries=["KEN"],
            indicators=["PCPIPCH"],
            period=PeriodRange(start="2018", end="2020"),
        ),
        findings=list(findings),
        series=[series],
        comparisons=[],
        baselines=[],
        anomalies=[],
        interpretation=interpretation,
        tool_results=[tool_result],
        charts=[
            ChartSpec(
                id="c1",
                kind="line",
                title="Inflation",
                result_id="r1",
                unit="%",
                series_ids=[series.id],
            )
        ],
        sources=[SOURCE],
        caveats=tuple(caveats),
        generated_at=WHEN,
    )


def make_investigation(
    result=None, status="succeeded", question="Why?", error=None, created=WHEN, run=None, id=None
):
    return Investigation(
        id=id or uuid.uuid4(),
        title=question or "title",
        status=status,
        data_mode="demo",
        request=result.request if result else None,
        result=result,
        error=error,
        run=run,
        created_at=created,
        updated_at=created,
    )


def make_run(question=None, selection=None):
    return InvestigationRun(
        question=question,
        selection=selection
        or Selection(countries=["KEN", "NGA"], indicator="PCPIPCH", start="2018", end="2020"),
        prompt_version=None,
        model=None,
        tool_calls=[],
        validation=None,
        usage=LLMUsage(calls=0, input_tokens=0, output_tokens=0, latency_ms=0),
    )


def failed(message="The data service is unavailable."):
    return InvestigationError(code="data_unavailable", message=message, service="data_service")

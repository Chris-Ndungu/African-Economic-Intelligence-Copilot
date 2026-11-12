"""Request and response bodies of the JSON API in ``api/openapi.yaml``.

The result models they carry live in :mod:`copilot_core.models`. These are
plain Pydantic models with no web-framework imports, so the repository and
the routes share them. ``tests/test_contract.py`` checks that the schema
FastAPI generates from them matches the contract.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from copilot_core.db import DataMode, InvestigationStatus
from copilot_core.interpretation import VerifiedInterpretation
from copilot_core.models import (
    AnomalyResult,
    BaselineResult,
    Caveats,
    ComparisonResult,
    CountryCode,
    Finding,
    Frequency,
    IndicatorCode,
    PeriodLabel,
    SeriesResult,
    SourceRef,
)

__all__ = [
    "MAX_QUESTION_LENGTH",
    "AnalysisParameters",
    "ChartSpec",
    "Country",
    "CountryList",
    "Coverage",
    "CoverageEntry",
    "ErrorBody",
    "ErrorDetail",
    "Health",
    "Indicator",
    "IndicatorCategory",
    "IndicatorList",
    "Interpretation",
    "Investigation",
    "InvestigationCreate",
    "InvestigationError",
    "InvestigationErrorCode",
    "InvestigationList",
    "InvestigationRequest",
    "InvestigationResult",
    "InvestigationRun",
    "InvestigationRunAccepted",
    "InvestigationRunRequest",
    "InvestigationSummary",
    "InvestigationType",
    "InvestigationUpdate",
    "LLMUsage",
    "PeriodRange",
    "Selection",
    "ServiceName",
    "ToolCallRecord",
    "ToolResult",
    "ValidationSummary",
]

MAX_QUESTION_LENGTH = 1000
"""Longest question a run accepts, in characters."""


class _Body(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Health and errors --------------------------------------------------------


class Health(_Body):
    status: Literal["ok"]


ServiceName = Literal["gemini", "data_service", "database"]


class ErrorDetail(_Body):
    field: str
    message: str


class ErrorBody(_Body):
    """The shared error body for every 4xx and 5xx response."""

    model_config = ConfigDict(title="Error")

    code: Literal[
        "validation_error",
        "not_found",
        "step_limit_reached",
        "service_unavailable",
        "internal_error",
    ]
    message: str
    service: ServiceName | None
    details: list[ErrorDetail]


# --- Reference data -----------------------------------------------------------

IndicatorCategory = Literal[
    "gdp",
    "inflation",
    "trade",
    "debt",
    "fiscal",
    "labour",
    "demographics",
    "investment",
    "savings",
    "financial",
    "digital",
]


class Country(_Body):
    code: CountryCode
    name: str
    region: str | None


class CountryList(_Body):
    data_mode: DataMode
    countries: list[Country]


class Indicator(_Body):
    code: IndicatorCode
    name: str
    category: IndicatorCategory
    unit: str
    frequency: Frequency
    description: str | None
    source: SourceRef


class IndicatorList(_Body):
    data_mode: DataMode
    indicators: list[Indicator]


class CoverageEntry(_Body):
    country_code: CountryCode
    indicator_code: IndicatorCode
    frequency: Frequency
    first_period: PeriodLabel | None
    last_period: PeriodLabel | None
    observation_count: Annotated[int, Field(ge=0)]
    missing_count: Annotated[int, Field(ge=0)]
    last_updated: date | None


class Coverage(_Body):
    data_mode: DataMode
    entries: list[CoverageEntry]


# --- Investigations -----------------------------------------------------------

InvestigationType = Literal["trend", "comparison", "anomaly"]


class PeriodRange(_Body):
    start: PeriodLabel
    end: PeriodLabel

    @model_validator(mode="after")
    def _ordered(self) -> PeriodRange:
        if len(self.start) == len(self.end) and self.start > self.end:
            raise ValueError(f"start {self.start!r} is after end {self.end!r}")
        return self


class AnalysisParameters(_Body):
    baseline_periods: Annotated[int, Field(ge=2)] = 10
    anomaly_method: Literal["z_score"] = "z_score"
    anomaly_threshold: Annotated[float, Field(gt=0)] = 2


class InvestigationRequest(_Body):
    question: Annotated[str, Field(max_length=2000)] | None
    investigation_type: InvestigationType
    countries: Annotated[list[CountryCode], Field(min_length=1, max_length=10)]
    indicators: Annotated[list[IndicatorCode], Field(min_length=1, max_length=5)]
    period: PeriodRange
    parameters: AnalysisParameters = Field(default_factory=AnalysisParameters)


Interpretation = VerifiedInterpretation


class ToolResult(_Body):
    """One successful tool call's result, which findings cite by ``result_id``."""

    result_id: str
    tool: str
    arguments: dict[str, Any]
    data: dict[str, Any]


class ChartSpec(_Body):
    """What to draw for one cited tool result."""

    id: str
    kind: Literal["line", "bar", "table"]
    title: str
    result_id: str
    unit: str | None
    series_ids: list[str]


class InvestigationResult(_Body):
    data_mode: DataMode
    request: InvestigationRequest | None
    findings: list[Finding]
    series: list[SeriesResult]
    comparisons: list[ComparisonResult]
    baselines: list[BaselineResult]
    anomalies: list[AnomalyResult]
    interpretation: Interpretation | None = Field(
        description="Gemini's interpretation, or `null` when not interpreted yet."
    )
    tool_results: list[ToolResult]
    charts: list[ChartSpec]
    sources: list[SourceRef]
    caveats: Caveats
    generated_at: datetime


Title = Annotated[str, Field(min_length=1, max_length=200)]


def _no_nulls(model: BaseModel) -> None:
    """Optional fields may be left out, but not sent as ``null``."""
    nulls = [name for name in model.model_fields_set if getattr(model, name) is None]
    if nulls:
        raise ValueError(f"{', '.join(sorted(nulls))} may be left out but not null")


class InvestigationCreate(_Body):
    status: InvestigationStatus | SkipJsonSchema[None] = None
    title: Title
    request: InvestigationRequest
    result: InvestigationResult

    @model_validator(mode="after")
    def _status_not_null(self) -> InvestigationCreate:
        _no_nulls(self)
        return self


class InvestigationUpdate(_Body):
    status: InvestigationStatus | SkipJsonSchema[None] = None
    title: Title | SkipJsonSchema[None] = None
    request: InvestigationRequest | SkipJsonSchema[None] = None
    result: InvestigationResult | SkipJsonSchema[None] = None

    @model_validator(mode="after")
    def _not_empty(self) -> InvestigationUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        _no_nulls(self)
        return self


class Selection(_Body):
    """Countries, one indicator and a period that limit what a run may query."""

    countries: Annotated[list[CountryCode], Field(min_length=1, max_length=10)]
    indicator: IndicatorCode
    start: PeriodLabel
    end: PeriodLabel

    @model_validator(mode="after")
    def _ordered(self) -> Selection:
        if len(self.start) == len(self.end) and self.start > self.end:
            raise ValueError(f"start {self.start!r} is after end {self.end!r}")
        return self


class InvestigationRunRequest(_Body):
    """A question, a selection or both."""

    question: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_QUESTION_LENGTH,
                description=f"At most {MAX_QUESTION_LENGTH} characters.",
            ),
        ]
        | SkipJsonSchema[None]
    ) = None
    selection: Selection | SkipJsonSchema[None] = None

    @model_validator(mode="after")
    def _question_or_selection(self) -> InvestigationRunRequest:
        _no_nulls(self)
        if self.question is None and self.selection is None:
            raise ValueError("send a question, a selection or both")
        return self


class InvestigationRunAccepted(_Body):
    id: uuid.UUID
    status: Literal["pending"]
    events_url: str


InvestigationErrorCode = Literal[
    "gemini_not_configured",
    "gemini_unavailable",
    "gemini_timeout",
    "gemini_blocked",
    "gemini_truncated",
    "gemini_request_error",
    "interpretation_invalid",
    "data_unavailable",
    "timeout",
    "step_limit_reached",
    "interrupted",
    "not_started",
    "client_disconnected",
    "internal_error",
]


class InvestigationError(_Body):
    """Why a run failed."""

    code: InvestigationErrorCode
    message: str
    service: ServiceName | None


class ToolCallRecord(_Body):
    """One tool call Gemini asked for, run or refused."""

    step: Annotated[int, Field(ge=1)]
    tool: str
    arguments: dict[str, Any]
    result_id: str
    status: Literal["ok", "error"]
    error: str | None
    duration_ms: float


class LLMUsage(_Body):
    calls: Annotated[int, Field(ge=0)]
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    latency_ms: float


class ValidationSummary(_Body):
    verified_count: Annotated[int, Field(ge=0)]
    unverified_count: Annotated[int, Field(ge=0)]
    unverified_findings: Annotated[int, Field(ge=0)]


class InvestigationRun(_Body):
    """What a run was asked and what it did."""

    question: str | None
    selection: Selection | None
    prompt_version: str | None
    model: str | None
    tool_calls: list[ToolCallRecord]
    validation: ValidationSummary | None
    usage: LLMUsage


class Investigation(_Body):
    id: uuid.UUID
    title: str
    status: InvestigationStatus
    data_mode: DataMode
    request: InvestigationRequest | None
    result: InvestigationResult | None
    error: InvestigationError | None
    run: InvestigationRun | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class InvestigationSummary(_Body):
    id: uuid.UUID
    title: str
    status: InvestigationStatus
    data_mode: DataMode
    investigation_type: InvestigationType | None
    countries: list[CountryCode]
    indicators: list[IndicatorCode]
    created_at: AwareDatetime
    updated_at: AwareDatetime


class InvestigationList(_Body):
    data_mode: DataMode
    items: list[InvestigationSummary]
    limit: int
    next_cursor: str | None

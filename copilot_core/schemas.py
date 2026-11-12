"""Request and response bodies of the JSON API in ``api/openapi.yaml``.

The result models they carry live in :mod:`copilot_core.models`. These are
plain Pydantic models with no web-framework imports, so the repository and
the routes share them. ``tests/test_contract.py`` checks that the schema
FastAPI generates from them matches the contract.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from copilot_core.db import DataMode, InvestigationStatus
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
    "AnalysisParameters",
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
    "InterpretationStatement",
    "Investigation",
    "InvestigationCreate",
    "InvestigationList",
    "InvestigationRequest",
    "InvestigationResult",
    "InvestigationSummary",
    "InvestigationType",
    "InvestigationUpdate",
    "PeriodRange",
]


class _Body(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Health and errors --------------------------------------------------------


class Health(_Body):
    status: Literal["ok"]


class ErrorDetail(_Body):
    field: str
    message: str


class ErrorBody(_Body):
    """The shared error body for every 4xx and 5xx response."""

    model_config = ConfigDict(title="Error")

    code: Literal["validation_error", "not_found", "service_unavailable", "internal_error"]
    message: str
    service: Literal["gemini", "data_service", "database"] | None
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


class InterpretationStatement(_Body):
    text: str
    label: Literal["observation", "hypothesis"]
    finding_ids: list[str]


class Interpretation(_Body):
    summary: str
    statements: list[InterpretationStatement]
    caveats: Caveats
    model: str


class InvestigationResult(_Body):
    data_mode: DataMode
    request: InvestigationRequest
    findings: list[Finding]
    series: list[SeriesResult]
    comparisons: list[ComparisonResult]
    baselines: list[BaselineResult]
    anomalies: list[AnomalyResult]
    interpretation: Interpretation | None = Field(
        description="Gemini's interpretation, or `null` when not interpreted yet."
    )
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


class Investigation(_Body):
    id: uuid.UUID
    title: str
    status: InvestigationStatus
    data_mode: DataMode
    request: InvestigationRequest
    result: InvestigationResult
    created_at: AwareDatetime
    updated_at: AwareDatetime


class InvestigationSummary(_Body):
    id: uuid.UUID
    title: str
    status: InvestigationStatus
    data_mode: DataMode
    investigation_type: InvestigationType
    countries: list[CountryCode]
    indicators: list[IndicatorCode]
    created_at: AwareDatetime
    updated_at: AwareDatetime


class InvestigationList(_Body):
    data_mode: DataMode
    items: list[InvestigationSummary]
    limit: int
    next_cursor: str | None

"""Result models returned by analysis functions and served by the API.

These Pydantic models are the single source of truth for computed results:
analysis functions return them, the API serves them, Gemini sees them as tool
output, and Postgres and the PDF report store them. They match the schemas in
``api/openapi.yaml``; where the Python name differs, the model's JSON Schema
title carries the contract name:

- ``SourceRef`` is the contract's ``Source``
- ``SeriesResult`` is the contract's ``Series``

Every model is immutable and rejects results that cannot be cited: a missing
unit, method or source, a geography that is not an ISO 3166-1 alpha-3 code, a
malformed period, a NaN or infinite number, or a missing number without a
caveat explaining why it is missing.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from datetime import date
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    AfterValidator,
    AnyUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    Strict,
    StringConstraints,
    model_validator,
)
from pydantic.types import AllowInfNan

__all__ = [
    "AnomalyResult",
    "BaselineResult",
    "ComparisonEntry",
    "ComparisonResult",
    "Finding",
    "Frequency",
    "Geography",
    "Method",
    "NumericResult",
    "Parameters",
    "Period",
    "SeriesPoint",
    "SeriesResult",
    "SourceRef",
    "period_frequency",
]


# --- Constrained field types ------------------------------------------------


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonEmptyStr = Annotated[str, StringConstraints(min_length=1), AfterValidator(_not_blank)]
"""A string with at least one non-whitespace character."""

CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
"""ISO 3166-1 alpha-3 country code, for example ``KEN``."""

IndicatorCode = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]
"""Identifier of an indicator, for example ``inflation_cpi``."""

Frequency = Literal["annual", "quarterly", "monthly", "daily"]

_PERIOD_PATTERNS: dict[str, re.Pattern[str]] = {
    "annual": re.compile(r"^[0-9]{4}$"),
    "quarterly": re.compile(r"^[0-9]{4}-Q[1-4]$"),
    "monthly": re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
    "daily": re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$"),
}


def period_frequency(label: str) -> Frequency | None:
    """Return the frequency a period label is written in, or ``None``."""
    for frequency, pattern in _PERIOD_PATTERNS.items():
        if pattern.match(label):
            return frequency  # type: ignore[return-value]
    return None


def _real_calendar_date(label: str) -> str:
    if period_frequency(label) == "daily":
        try:
            date.fromisoformat(label)
        except ValueError:
            raise ValueError(f"{label!r} is not a real calendar date") from None
    return label


PeriodLabel = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9]{4}(-Q[1-4]|-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?$"
    ),
    AfterValidator(_real_calendar_date),
]
"""``2023``, ``2023-Q1``, ``2023-01`` or ``2023-01-31``."""

Number = Annotated[float, Strict(), AllowInfNan(False)]
"""A finite number. Booleans and numeric strings are not numbers."""

_StrictScalar = (
    Annotated[bool, Strict()]
    | Annotated[int, Strict()]
    | Annotated[float, Strict(), AllowInfNan(False)]
    | Annotated[str, Strict()]
)
ParameterValue = _StrictScalar | Annotated[list[_StrictScalar], Strict()]
"""A string, number or boolean, or a list of these, so it serializes to JSON."""

Caveats = tuple[NonEmptyStr, ...]


class Parameters(Mapping[str, Any]):
    """A read-only, hashable mapping of method parameters.

    List values are stored as tuples, so neither the mapping nor its values
    can be changed after a result is built. It compares equal to a plain
    ``dict`` with the same items and serializes to a JSON object with arrays.
    """

    __slots__ = ("_items",)

    def __init__(self, items: Mapping[str, Any]) -> None:
        frozen = {k: tuple(v) if isinstance(v, list) else v for k, v in items.items()}
        object.__setattr__(self, "_items", MappingProxyType(frozen))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Parameters is read-only")

    def __getitem__(self, key: str) -> Any:
        return self._items[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return hash(frozenset(self._items.items()))

    def __repr__(self) -> str:
        return f"Parameters({dict(self._items)!r})"

    def to_dict(self) -> dict[str, Any]:
        """A plain ``dict`` copy, with tuple values as lists."""
        return {k: list(v) if isinstance(v, tuple) else v for k, v in self._items.items()}


def _thaw_parameters(value: Any) -> Any:
    # Let an existing Parameters be validated again, for example when a
    # method is reused in another result.
    return value.to_dict() if isinstance(value, Parameters) else value


ParameterMap = Annotated[
    dict[str, ParameterValue],
    BeforeValidator(_thaw_parameters),
    AfterValidator(Parameters),
    PlainSerializer(
        lambda value: value.to_dict(), return_type=dict[str, ParameterValue]
    ),
]
"""Method parameters, validated as a ``dict`` and stored as ``Parameters``."""


# --- Models -----------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class SourceRef(_Model):
    """Lineage of the data behind a result (the contract's ``Source``)."""

    model_config = ConfigDict(title="Source")

    id: NonEmptyStr = Field(description="Identifier of the curated dataset or model.")
    name: NonEmptyStr
    provider: str | None = Field(
        description="Original publisher, for example `IMF`, or `null` if unknown."
    )
    url: AnyUrl | None = Field(
        description="Link to the original source, or `null` if there is none."
    )
    last_updated: date | None = Field(
        description="When the source last updated the data, or `null` if unknown."
    )


class Geography(_Model):
    country_code: CountryCode
    country_name: NonEmptyStr


class Period(_Model):
    """The period a result covers, from ``start`` to ``end`` inclusive."""

    start: PeriodLabel
    end: PeriodLabel
    frequency: Frequency

    @model_validator(mode="after")
    def _consistent(self) -> Period:
        for field in ("start", "end"):
            label = getattr(self, field)
            if period_frequency(label) != self.frequency:
                raise ValueError(
                    f"{field} {label!r} does not match frequency {self.frequency!r}"
                )
        # Labels of the same frequency sort in time order.
        if self.start > self.end:
            raise ValueError(f"start {self.start!r} is after end {self.end!r}")
        return self

    def contains(self, label: str) -> bool:
        """Whether a label of this period's frequency falls within it."""
        return period_frequency(label) == self.frequency and self.start <= label <= self.end


class Method(_Model):
    """The calculation that produced a result and the parameters it used."""

    name: NonEmptyStr = Field(
        description="Identifier of the method, for example `z_score` or `historical_mean`."
    )
    description: NonEmptyStr
    parameters: ParameterMap = Field(
        description="Parameter names and the values used."
    )


class NumericResult(_Model):
    """A computed number with everything needed to cite it.

    A missing number is ``None``, never ``0``, and ``caveats`` must then say
    why. Subclasses list their other nullable numbers in ``_nullable_numbers``.
    """

    _nullable_numbers: ClassVar[tuple[str, ...]] = ("value",)

    value: Number | None = Field(
        description="The computed value, or `null` when it is missing. A missing value is never `0`."
    )
    unit: NonEmptyStr
    period: Period
    geography: Geography
    method: Method
    source: SourceRef
    caveats: Caveats

    @model_validator(mode="after")
    def _missing_needs_caveat(self) -> NumericResult:
        missing = [name for name in self._nullable_numbers if getattr(self, name) is None]
        if missing and not self.caveats:
            raise ValueError(f"caveats must explain why {', '.join(missing)} is missing")
        return self


class Finding(NumericResult):
    """A statement of fact computed in Python, with the number it rests on."""

    id: NonEmptyStr
    kind: Literal["trend", "comparison", "baseline", "anomaly", "data_gap"]
    metric: IndicatorCode
    statement: NonEmptyStr
    result_ids: tuple[str, ...]


class SeriesPoint(_Model):
    period: PeriodLabel
    value: Number | None


class SeriesResult(_Model):
    """A time series of one indicator for one country (the contract's ``Series``)."""

    model_config = ConfigDict(title="Series")

    id: NonEmptyStr
    metric: IndicatorCode
    unit: NonEmptyStr
    period: Period
    geography: Geography
    method: Method
    source: SourceRef
    caveats: Caveats
    points: tuple[SeriesPoint, ...]

    @model_validator(mode="after")
    def _points_consistent(self) -> SeriesResult:
        for index, point in enumerate(self.points):
            if not self.period.contains(point.period):
                raise ValueError(
                    f"points.{index}.period {point.period!r} is not a "
                    f"period of frequency {self.period.frequency!r} within "
                    f"{self.period.start}..{self.period.end}"
                )
        missing = [p.period for p in self.points if p.value is None]
        if missing and not self.caveats:
            raise ValueError(
                f"caveats must explain why the values for {', '.join(missing)} are missing"
            )
        return self


class ComparisonEntry(NumericResult):
    """One country's value in a comparison."""

    rank: Annotated[int, Strict(), Field(ge=1)] | None = Field(
        description="Position by value, 1 being the highest, or `null` when the value is missing."
    )

    @model_validator(mode="after")
    def _rank_needs_value(self) -> ComparisonEntry:
        if self.value is None and self.rank is not None:
            raise ValueError("rank must be null when value is missing")
        return self


class ComparisonResult(_Model):
    """The same indicator compared across countries."""

    id: NonEmptyStr
    metric: IndicatorCode
    method: Method
    entries: tuple[ComparisonEntry, ...]


class BaselineResult(NumericResult):
    """A value compared with the indicator's historical baseline."""

    _nullable_numbers: ClassVar[tuple[str, ...]] = (
        "value",
        "baseline_value",
        "difference",
        "percent_difference",
    )

    id: NonEmptyStr
    metric: IndicatorCode
    baseline_value: Number | None
    baseline_period: Period
    difference: Number | None
    percent_difference: Number | None


class AnomalyResult(NumericResult):
    """The result of an anomaly test on one value."""

    _nullable_numbers: ClassVar[tuple[str, ...]] = (
        "value",
        "score",
        "expected_value",
    )

    id: NonEmptyStr
    metric: IndicatorCode
    is_anomaly: bool | None
    score: Number | None
    threshold: Number
    expected_value: Number | None
    direction: Literal["above", "below"] | None

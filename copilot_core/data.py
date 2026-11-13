"""Read economic data through one interface, ``DataService``.

``DuckDBDataService`` implements it over the demo Parquet files in
``data/demo/`` (one file per curated table, see ``_docs/data-contract.md``).
A BigQuery implementation for live mode follows in #49.

Rules every implementation keeps:

- Only the "Supported indicators" of the data contract are offered.
- Only actual values are returned: IMF forecast rows are left out.
- A missing value is ``None`` with a caveat, never ``0``, and a missing
  period is never dropped silently.
- User input reaches the database only as query parameters.
- The service never writes to the data files.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

import duckdb

from copilot_core.models import (
    Geography,
    Method,
    Period,
    SeriesPoint,
    SeriesResult,
    SourceRef,
    period_frequency,
)
from copilot_core.schemas import Country, CoverageEntry, Indicator
from copilot_core.telemetry import annotate, span

__all__ = [
    "DEFAULT_DATA_DIR",
    "SUPPORTED_INDICATORS",
    "TABLES",
    "DataError",
    "DataFileMissingError",
    "DataService",
    "DataUnavailableError",
    "DuckDBDataService",
    "InvalidPeriodError",
    "UnknownCountryError",
    "UnknownIndicatorError",
]

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"

TABLES = ("dim_country", "dim_indicator", "fact_macroeconomic_indicators")
"""The Parquet files the service reads, one per curated table."""

SUPPORTED_INDICATORS: tuple[str, ...] = (
    "NGDPD",
    "NGDP_RPCH",
    "NGDPDPC",
    "PCPIPCH",
    "PCPIEPCH",
    "BCA_NGDPD",
    "GGXWDG_NGDP",
    "GGXCNL_NGDP",
    "LP",
    "SL.UEM.TOTL.ZS",
    "NE.EXP.GNFS.CD",
    "NE.IMP.GNFS.CD",
    "DT.DOD.DECT.CD",
    "BX.KLT.DINV.CD.WD",
)
"""The annual series under "Supported indicators" in ``_docs/data-contract.md``.

The exchange rate is supported only as the latest rate with its date, not as
a series, so it is not offered here.
"""

FACT_TABLE = "fact_macroeconomic_indicators"
FREQUENCY = "annual"  # Every supported macro indicator is annual.
CURRENT_YEAR_ESTIMATE = 2026  # IMF values for the load year are estimates.


# --- Errors -------------------------------------------------------------------


class DataError(Exception):
    """Base class for data service errors."""


class DataUnavailableError(DataError):
    """The data files cannot be read. The API answers ``503``."""


class DataFileMissingError(DataUnavailableError):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"Data file not found: {path}")


class InvalidRequestError(DataError, ValueError):
    """A request the service cannot answer. ``field`` names the input."""

    def __init__(self, message: str, field: str) -> None:
        self.field = field
        super().__init__(message)


class UnknownCountryError(InvalidRequestError):
    def __init__(self, codes: Sequence[str]) -> None:
        self.codes = tuple(codes)
        listed = ", ".join(repr(c) for c in codes)
        super().__init__(f"Unknown country code: {listed}", "countries")


class UnknownIndicatorError(InvalidRequestError):
    def __init__(self, codes: Sequence[str]) -> None:
        self.codes = tuple(codes)
        listed = ", ".join(repr(c) for c in codes)
        super().__init__(f"Unknown or unsupported indicator: {listed}", "indicator")


class InvalidPeriodError(InvalidRequestError):
    pass


# --- Interface ----------------------------------------------------------------


class DataService(Protocol):
    """How analytics code and the API read economic data."""

    def get_series(
        self, countries: Sequence[str], indicator: str, start: str, end: str
    ) -> list[SeriesResult]:
        """One series per country, in the order given, for ``start..end``."""
        ...

    def list_countries(self) -> list[Country]: ...

    def list_indicators(self) -> list[Indicator]: ...

    def list_coverage(
        self, countries: Sequence[str] | None = None, indicators: Sequence[str] | None = None
    ) -> list[CoverageEntry]: ...


# --- DuckDB implementation ----------------------------------------------------


@dataclass(frozen=True)
class _IndicatorInfo:
    code: str
    name: str
    category: str
    unit: str
    data_source: str


def _year(label: str, field: str) -> int:
    if period_frequency(label) != FREQUENCY:
        raise InvalidPeriodError(
            f"{field} {label!r} is not an annual period (YYYY); every supported "
            "indicator is annual",
            field,
        )
    return int(label)


def _years_text(years: Sequence[int]) -> str:
    """``2001, 2003-2005`` for a sorted list of years."""
    runs: list[tuple[int, int]] = []
    for year in years:
        if runs and year == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], year)
        else:
            runs.append((year, year))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


class DuckDBDataService:
    """``DataService`` over the curated tables saved as Parquet files.

    One in-memory DuckDB database holds a read-only view per file. Each call
    runs on its own cursor, so concurrent requests never share one.
    """

    def __init__(self, data_dir: Path | str = DEFAULT_DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        for table in TABLES:
            path = self.data_dir / f"{table}.parquet"
            if not path.is_file():
                raise DataFileMissingError(path)
        self._lock = threading.Lock()
        try:
            self._connection = duckdb.connect(":memory:")
            for table in TABLES:
                file = str((self.data_dir / f"{table}.parquet").resolve()).replace("'", "''")
                self._connection.execute(
                    f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{file}')"
                )
            self._indicators = self._load_indicators()
        except duckdb.Error as exc:
            raise DataUnavailableError(f"Data files in {self.data_dir} cannot be read") from exc

    @contextmanager
    def _cursor(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._lock:
            cursor = self._connection.cursor()
        try:
            yield cursor
        except duckdb.Error as exc:
            raise DataUnavailableError(f"Data files in {self.data_dir} cannot be read") from exc
        finally:
            cursor.close()

    def _load_indicators(self) -> dict[str, _IndicatorInfo]:
        rows = self._connection.execute(
            "SELECT indicator_code, indicator_name, category, metric_unit, data_source "
            "FROM dim_indicator WHERE indicator_code IN (SELECT unnest(?::VARCHAR[]))",
            [list(SUPPORTED_INDICATORS)],
        ).fetchall()
        found = {row[0]: _IndicatorInfo(*row) for row in rows}
        # Keep the data contract's order.
        return {code: found[code] for code in SUPPORTED_INDICATORS if code in found}

    def _check_countries(self, cursor: duckdb.DuckDBPyConnection, codes: Sequence[str]) -> None:
        known = {
            row[0]
            for row in cursor.execute(
                "SELECT country_code FROM dim_country "
                "WHERE country_code IN (SELECT unnest(?::VARCHAR[]))",
                [list(codes)],
            ).fetchall()
        }
        unknown = [code for code in codes if code not in known]
        if unknown:
            raise UnknownCountryError(unknown)

    def _check_indicators(self, codes: Sequence[str]) -> None:
        unknown = [code for code in codes if code not in self._indicators]
        if unknown:
            raise UnknownIndicatorError(unknown)

    def _source(self, info: _IndicatorInfo, last_updated: date | None) -> SourceRef:
        return SourceRef(
            id=FACT_TABLE,
            name=info.data_source,
            provider=info.data_source,
            url=None,
            last_updated=last_updated,
        )

    # --- DataService ---

    def get_series(
        self, countries: Sequence[str], indicator: str, start: str, end: str
    ) -> list[SeriesResult]:
        with span("data.get_series", **{"indicator": indicator, "country.count": len(countries)}):
            series = self._get_series(countries, indicator, start, end)
            annotate(
                **{"series.count": len(series), "row.count": sum(len(x.points) for x in series)}
            )
            return series

    def _get_series(
        self, countries: Sequence[str], indicator: str, start: str, end: str
    ) -> list[SeriesResult]:
        first, last = _year(start, "start"), _year(end, "end")
        if first > last:
            raise InvalidPeriodError(f"start {start!r} is after end {end!r}", "start")
        if not countries:
            raise InvalidRequestError("At least one country is required", "countries")
        self._check_indicators([indicator])
        info = self._indicators[indicator]
        countries = list(dict.fromkeys(countries))
        with self._cursor() as cursor:
            self._check_countries(cursor, countries)
            names = dict(
                cursor.execute(
                    "SELECT country_code, country_name FROM dim_country "
                    "WHERE country_code IN (SELECT unnest(?::VARCHAR[]))",
                    [countries],
                ).fetchall()
            )
            statement = (
                f"SELECT country_code, report_year, indicator_value, is_forecast, ingestion_date "
                f"FROM {FACT_TABLE} WHERE indicator_code = ? "
                "AND country_code IN (SELECT unnest(?::VARCHAR[])) "
                "AND report_year BETWEEN ? AND ? ORDER BY country_code, report_year"
            )
            # The statement has placeholders only; the values are never recorded.
            with span(
                "duckdb.query", **{"db.system": "duckdb", "db.statement": statement}
            ) as query:
                rows = cursor.execute(statement, [indicator, countries, first, last]).fetchall()
                query.set_attribute("row.count", len(rows))
            extent = dict(
                (row[0], (row[1], row[2]))
                for row in cursor.execute(
                    f"SELECT country_code, min(report_year), max(report_year) FROM {FACT_TABLE} "
                    "WHERE indicator_code = ? AND NOT is_forecast "
                    "AND country_code IN (SELECT unnest(?::VARCHAR[])) GROUP BY country_code",
                    [indicator, countries],
                ).fetchall()
            )
        by_country: dict[str, list[tuple[int, float | None, bool, date | None]]] = {}
        for code, year, value, forecast, ingested in rows:
            by_country.setdefault(code, []).append((year, value, forecast, ingested))
        return [
            self._series(
                info, code, names[code], first, last, by_country.get(code, []), extent.get(code)
            )
            for code in countries
        ]

    def _series(
        self,
        info: _IndicatorInfo,
        country: str,
        country_name: str,
        first: int,
        last: int,
        rows: list[tuple[int, float | None, bool, date | None]],
        extent: tuple[int, int] | None,
    ) -> SeriesResult:
        actual = {year: value for year, value, forecast, _ in rows if not forecast}
        forecast_years = sorted(year for year, _, forecast, _ in rows if forecast)
        updated = [ingested for *_, ingested in rows if ingested is not None]
        caveats: list[str] = []
        no_row = [y for y in range(first, last + 1) if y not in actual]
        null_row = [y for y in range(first, last + 1) if y in actual and actual[y] is None]
        if extent is None:
            caveats.append(
                f"The source has no actual values of {info.code} for {country_name}; "
                "every period is missing."
            )
        else:
            if first < extent[0] or last > extent[1]:
                caveats.append(
                    f"The requested range {first}-{last} extends past the available data "
                    f"({extent[0]}-{extent[1]}); periods outside it are marked missing."
                )
            if no_row:
                caveats.append(f"No value for {_years_text(no_row)}: the source has no row.")
        if null_row:
            caveats.append(f"No value for {_years_text(null_row)}: the source row has no value.")
        if forecast_years:
            caveats.append(
                f"IMF forecasts for {_years_text(forecast_years)} are left out; "
                "only actual values are shown."
            )
        if (
            CURRENT_YEAR_ESTIMATE in actual
            and actual[CURRENT_YEAR_ESTIMATE] is not None
            and info.data_source.startswith("IMF")
        ):
            caveats.append(
                f"The {CURRENT_YEAR_ESTIMATE} value is an IMF estimate for the current year."
            )
        start, end = str(first), str(last)
        return SeriesResult(
            id=f"series:{info.code}:{country}:{start}-{end}",
            metric=info.code,
            unit=info.unit,
            period=Period(start=start, end=end, frequency=FREQUENCY),
            geography=Geography(country_code=country, country_name=country_name),
            method=Method(
                name="observed",
                description="Actual values as published in the curated data; forecasts left out.",
                parameters={"start": start, "end": end},
            ),
            source=self._source(info, max(updated) if updated else None),
            caveats=tuple(caveats),
            points=tuple(
                SeriesPoint(period=str(year), value=actual.get(year))
                for year in range(first, last + 1)
            ),
        )

    def list_countries(self) -> list[Country]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT country_code, country_name, sub_region FROM dim_country "
                "ORDER BY country_name"
            ).fetchall()
        return [Country(code=code, name=name, region=region) for code, name, region in rows]

    def list_indicators(self) -> list[Indicator]:
        with self._cursor() as cursor:
            updated = dict(
                cursor.execute(
                    f"SELECT indicator_code, max(ingestion_date) FROM {FACT_TABLE} "
                    "GROUP BY indicator_code"
                ).fetchall()
            )
        return [
            Indicator(
                code=info.code,
                name=info.name,
                category=info.category.lower(),
                unit=info.unit,
                frequency=FREQUENCY,
                description=None,
                source=self._source(info, updated.get(info.code)),
            )
            for info in self._indicators.values()
        ]

    def list_coverage(
        self, countries: Sequence[str] | None = None, indicators: Sequence[str] | None = None
    ) -> list[CoverageEntry]:
        indicators = list(indicators) if indicators else list(self._indicators)
        self._check_indicators(indicators)
        with self._cursor() as cursor:
            if countries:
                self._check_countries(cursor, countries)
            else:
                countries = [
                    r[0] for r in cursor.execute("SELECT country_code FROM dim_country").fetchall()
                ]
            rows = cursor.execute(
                "SELECT country_code, indicator_code, "
                "min(report_year) FILTER (WHERE indicator_value IS NOT NULL), "
                "max(report_year) FILTER (WHERE indicator_value IS NOT NULL), "
                "count(indicator_value), max(ingestion_date) "
                f"FROM {FACT_TABLE} WHERE NOT is_forecast "
                "AND country_code IN (SELECT unnest(?::VARCHAR[])) "
                "AND indicator_code IN (SELECT unnest(?::VARCHAR[])) "
                "GROUP BY country_code, indicator_code ORDER BY country_code, indicator_code",
                [list(countries), indicators],
            ).fetchall()
        return [
            CoverageEntry(
                country_code=country,
                indicator_code=indicator,
                frequency=FREQUENCY,
                first_period=None if first is None else str(first),
                last_period=None if last is None else str(last),
                observation_count=count,
                missing_count=0 if first is None else (last - first + 1) - count,
                last_updated=updated,
            )
            for country, indicator, first, last, count, updated in rows
        ]

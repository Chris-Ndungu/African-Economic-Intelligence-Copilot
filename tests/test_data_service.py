"""Unit tests of DuckDBDataService on the tiny fixture in tests/fixtures/tiny/ (#15)."""

import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

from copilot_core.data import (
    SUPPORTED_INDICATORS,
    DataFileMissingError,
    DataService,
    DuckDBDataService,
    InvalidPeriodError,
    UnknownCountryError,
    UnknownIndicatorError,
)

ROOT = Path(__file__).resolve().parent.parent
TINY = Path(__file__).resolve().parent / "fixtures" / "tiny"


@pytest.fixture(scope="module")
def service():
    return DuckDBDataService(TINY)


def values(series):
    return {p.period: p.value for p in series.points}


def test_implements_the_protocol(service):
    assert isinstance(service, DuckDBDataService)
    protocol: DataService = service  # type-checked by mypy in copilot_core
    for name in ("get_series", "list_countries", "list_indicators", "list_coverage"):
        assert callable(getattr(protocol, name))


def test_get_series_returns_one_series_per_country(service):
    kenya, nigeria = service.get_series(["KEN", "NGA"], "PCPIPCH", "2019", "2022")
    assert kenya.geography.country_code == "KEN"
    assert nigeria.geography.country_name == "Nigeria"
    assert values(kenya) == {"2019": 5.2, "2020": 5.4, "2021": 6.1, "2022": 7.7}
    assert kenya.period.start == "2019" and kenya.period.end == "2022"


def test_unit_frequency_and_source_come_from_the_data(service):
    kenya, unemployment = (
        service.get_series(["KEN"], "PCPIPCH", "2020", "2021")[0],
        service.get_series(["KEN"], "SL.UEM.TOTL.ZS", "2020", "2021")[0],
    )
    assert kenya.unit == "%"
    assert kenya.period.frequency == "annual"
    assert kenya.source.name == "IMF DataMapper"
    assert unemployment.source.name == "World Bank"
    assert kenya.source.last_updated == date(2026, 10, 29)


def test_null_value_and_missing_row_are_none_with_caveats(service):
    (kenya,) = service.get_series(["KEN"], "PCPIPCH", "2022", "2025")
    assert values(kenya) == {"2022": 7.7, "2023": None, "2024": None, "2025": 5.0}
    assert len(kenya.points) == 4  # nothing dropped
    text = " ".join(kenya.caveats)
    assert "2023: the source row has no value" in text
    assert "2024: the source has no row" in text


def test_missing_value_is_never_zero(service):
    (unemployment,) = service.get_series(["KEN"], "SL.UEM.TOTL.ZS", "2020", "2021")
    assert [p.value for p in unemployment.points] == [None, None]
    assert unemployment.caveats


def test_range_past_the_data_returns_what_exists_and_marks_the_rest(service):
    (kenya,) = service.get_series(["KEN"], "PCPIPCH", "2015", "2026")
    assert [p.period for p in kenya.points] == [str(y) for y in range(2015, 2027)]
    assert values(kenya)["2015"] is None and values(kenya)["2018"] == 4.7
    assert any("extends past the available data (2018-2025)" in c for c in kenya.caveats)


def test_forecasts_are_left_out(service):
    (kenya,) = service.get_series(["KEN"], "PCPIPCH", "2025", "2027")
    assert values(kenya)["2027"] is None
    assert any("forecasts for 2027 are left out" in c for c in kenya.caveats)


def test_country_with_no_data_gets_a_caveat(service):
    (tanzania,) = service.get_series(["TZA"], "PCPIPCH", "2020", "2021")
    assert [p.value for p in tanzania.points] == [None, None]
    assert "no actual values" in tanzania.caveats[0]


def test_unknown_country_names_the_code(service):
    with pytest.raises(UnknownCountryError, match="'XXX'"):
        service.get_series(["KEN", "XXX"], "PCPIPCH", "2020", "2021")


def test_unknown_indicator_names_the_code(service):
    with pytest.raises(UnknownIndicatorError, match="'NOPE'"):
        service.get_series(["KEN"], "NOPE", "2020", "2021")


def test_unsupported_indicator_is_unknown(service):
    with pytest.raises(UnknownIndicatorError, match="NY.GDP.MKTP.CD"):
        service.get_series(["KEN"], "NY.GDP.MKTP.CD", "2020", "2021")


def test_start_after_end_is_a_validation_error(service):
    with pytest.raises(InvalidPeriodError, match="after"):
        service.get_series(["KEN"], "PCPIPCH", "2022", "2020")
    assert issubclass(InvalidPeriodError, ValueError)


def test_non_annual_period_is_a_validation_error(service):
    with pytest.raises(InvalidPeriodError, match="annual"):
        service.get_series(["KEN"], "PCPIPCH", "2020-Q1", "2021")


def test_sql_injection_is_an_unknown_country(service):
    hostile = "KEN'; DROP TABLE x; --"
    with pytest.raises(UnknownCountryError, match=re.escape(repr(hostile))):
        service.get_series([hostile], "PCPIPCH", "2020", "2021")
    assert len(service.list_countries()) == 3


def test_list_countries_includes_countries_without_data(service):
    countries = {c.code: c for c in service.list_countries()}
    assert set(countries) == {"KEN", "NGA", "TZA"}
    assert countries["KEN"].region == "Eastern Africa"


def test_list_indicators_returns_only_supported_ones(service):
    indicators = service.list_indicators()
    assert [i.code for i in indicators] == ["PCPIPCH", "SL.UEM.TOTL.ZS"]
    assert all(i.frequency == "annual" and i.unit == "%" for i in indicators)
    assert indicators[1].category == "labour"


def test_supported_indicators_match_the_data_contract():
    contract = (ROOT / "_docs" / "data-contract.md").read_text(encoding="utf-8")
    section = contract.split("### Supported indicators", 1)[1].split("\n\n", 3)[2]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    codes = [line.split("`")[1] for line in rows if "fact_fx_rates" not in line]
    assert tuple(codes) == SUPPORTED_INDICATORS


def test_list_coverage_counts_first_last_and_missing(service):
    entries = {(e.country_code, e.indicator_code): e for e in service.list_coverage()}
    kenya = entries[("KEN", "PCPIPCH")]
    assert (kenya.first_period, kenya.last_period) == ("2018", "2025")
    assert (kenya.observation_count, kenya.missing_count) == (6, 2)  # 2023 NULL, 2024 no row
    nulls = entries[("KEN", "SL.UEM.TOTL.ZS")]
    assert (nulls.first_period, nulls.observation_count) == (None, 0)
    assert ("KEN", "NY.GDP.MKTP.CD") not in entries


def test_list_coverage_filters_and_rejects_unknown_codes(service):
    entries = service.list_coverage(countries=["NGA"], indicators=["PCPIPCH"])
    assert [(e.country_code, e.indicator_code) for e in entries] == [("NGA", "PCPIPCH")]
    with pytest.raises(UnknownCountryError):
        service.list_coverage(countries=["XXX"])


def test_missing_parquet_file_names_the_file(tmp_path):
    for name in ("dim_country", "dim_indicator"):
        shutil.copy(TINY / f"{name}.parquet", tmp_path)
    with pytest.raises(DataFileMissingError, match="fact_macroeconomic_indicators.parquet"):
        DuckDBDataService(tmp_path)


def test_concurrent_calls_do_not_share_a_cursor(service):
    def call(i):
        if i % 2:
            return values(service.get_series(["NGA"], "PCPIPCH", "2019", "2023")[0])
        return len(service.list_coverage())

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(call, range(10)))
    nigeria = {"2019": 11.4, "2020": 13.2, "2021": 17.0, "2022": 18.8, "2023": 24.7}
    assert results == [3 if i % 2 == 0 else nigeria for i in range(10)]


def test_service_never_writes_to_the_data_folder(service):
    before = {p.name: p.stat().st_mtime_ns for p in TINY.iterdir()}
    service.get_series(["KEN"], "PCPIPCH", "2018", "2025")
    service.list_coverage()
    assert {p.name: p.stat().st_mtime_ns for p in TINY.iterdir()} == before

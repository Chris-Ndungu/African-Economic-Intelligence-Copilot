"""Fixtures for the selection panel tests: a few countries and indicators."""

from datetime import date

from copilot_core.data import DataUnavailableError
from copilot_core.models import SourceRef
from copilot_core.schemas import Country, CoverageEntry, Indicator

SOURCE = SourceRef(id="imf", name="IMF WEO", provider="IMF", url=None, last_updated=None)

COUNTRIES = [
    Country(code="EGY", name="Egypt", region="Northern Africa"),
    Country(code="GHA", name="Ghana", region="Western Africa"),
    Country(code="KEN", name="Kenya", region="Eastern Africa"),
    Country(code="NGA", name="Nigeria", region="Western Africa"),
    Country(code="SSD", name="South Sudan", region="Eastern Africa"),
]
EXTRA = [Country(code=f"X{c}{d}", name=f"Extra {c}{d}", region=None) for c in "AB" for d in "ABCDE"]


def indicator(code: str, name: str, unit: str = "%") -> Indicator:
    return Indicator(
        code=code,
        name=name,
        category="gdp",
        unit=unit,
        frequency="annual",
        description=None,
        source=SOURCE,
    )


INDICATORS = [indicator("INF", "Inflation"), indicator("GDP", "GDP", "USD_BN")]


def entry(country: str, code: str, first: str, last: str) -> CoverageEntry:
    n = int(last) - int(first) + 1
    return CoverageEntry(
        country_code=country,
        indicator_code=code,
        frequency="annual",
        first_period=first,
        last_period=last,
        observation_count=n,
        missing_count=0,
        last_updated=date(2026, 1, 1),
    )


COVERAGE = [
    entry("EGY", "INF", "1990", "2024"),
    entry("GHA", "INF", "2000", "2022"),
    entry("KEN", "INF", "1995", "2024"),
    entry("NGA", "INF", "1990", "2024"),
    # South Sudan has no inflation data; it has GDP from 2008.
    entry("SSD", "GDP", "2008", "2024"),
    entry("KEN", "GDP", "1990", "2024"),
]


class FakeDataService:
    """Just enough of ``DataService`` for the panel."""

    def __init__(self, countries=None, coverage=None, indicators=None, fail=False):
        self.countries = COUNTRIES if countries is None else countries
        self.coverage = COVERAGE if coverage is None else coverage
        self.indicators = INDICATORS if indicators is None else indicators
        self.fail = fail

    def _check(self):
        if self.fail:
            raise DataUnavailableError("down")

    def list_countries(self):
        self._check()
        return self.countries

    def list_indicators(self):
        self._check()
        return self.indicators

    def list_coverage(self, countries=None, indicators=None):
        self._check()
        return self.coverage

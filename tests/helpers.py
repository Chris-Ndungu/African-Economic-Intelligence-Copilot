"""Builders shared by the analysis tests."""

from copilot_core.models import Geography, Method, Period, SeriesPoint, SeriesResult, SourceRef

NAMES = {"KEN": "Kenya", "NGA": "Nigeria", "GHA": "Ghana", "TZA": "Tanzania"}


def make_series(
    values, start=2018, unit="%", country="KEN", metric="PCPIPCH", labels=None
) -> SeriesResult:
    """An annual series from ``start`` with ``values`` (``None`` is missing)."""
    labels = labels or [str(start + i) for i in range(len(values))]
    frequency = "quarterly" if "-Q" in labels[0] else "annual"
    return SeriesResult(
        id=f"series:{metric}:{country}",
        metric=metric,
        unit=unit,
        period=Period(start=labels[0], end=labels[-1], frequency=frequency),
        geography=Geography(country_code=country, country_name=NAMES.get(country, country)),
        method=Method(name="observed", description="Test values.", parameters={}),
        source=SourceRef(
            id="fact_macroeconomic_indicators",
            name="IMF DataMapper",
            provider="IMF DataMapper",
            url=None,
            last_updated=None,
        ),
        caveats=("Some values are missing.",) if None in values else (),
        points=tuple(SeriesPoint(period=p, value=v) for p, v in zip(labels, values, strict=True)),
    )

"""Build the tiny Parquet fixture in ``tests/fixtures/tiny/``.

The data service unit tests read this instead of ``data/demo/``, so they do
not break when the snapshot changes. Run it after changing the rows:

    uv run python tests/fixtures/build_fixtures.py

Rows (all values are made up):

- Kenya (KEN), inflation PCPIPCH: 2018-2022 values, 2023 a row with NULL,
  2024 no row, 2025 a value, 2027 an IMF forecast.
- Nigeria (NGA), inflation PCPIPCH: 2019-2023 values.
- Kenya, unemployment SL.UEM.TOTL.ZS: 2020 and 2021 rows, both NULL.
- Kenya, NY.GDP.MKTP.CD (not a supported indicator): 2020.
- Tanzania (TZA): in dim_country, with no data at all.
"""

from pathlib import Path

import duckdb

OUT = Path(__file__).resolve().parent / "tiny"

COUNTRIES = [
    ("KEN", "Kenya", "Eastern Africa"),
    ("NGA", "Nigeria", "Western Africa"),
    ("TZA", "Tanzania", "Eastern Africa"),
]
INDICATORS = [
    ("PCPIPCH", "Inflation, average consumer prices", "INFLATION", "%", "IMF DataMapper"),
    ("SL.UEM.TOTL.ZS", "Unemployment, total", "LABOUR", "%", "World Bank"),
    ("NY.GDP.MKTP.CD", "GDP (current US$)", "GDP", "USD", "World Bank"),
]
IMF, WB = "IMF DataMapper", "World Bank"
FACTS = [
    ("KEN", "PCPIPCH", 2018, 4.7, False, IMF),
    ("KEN", "PCPIPCH", 2019, 5.2, False, IMF),
    ("KEN", "PCPIPCH", 2020, 5.4, False, IMF),
    ("KEN", "PCPIPCH", 2021, 6.1, False, IMF),
    ("KEN", "PCPIPCH", 2022, 7.7, False, IMF),
    ("KEN", "PCPIPCH", 2023, None, False, IMF),
    ("KEN", "PCPIPCH", 2025, 5.0, False, IMF),
    ("KEN", "PCPIPCH", 2027, 5.1, True, IMF),
    ("NGA", "PCPIPCH", 2019, 11.4, False, IMF),
    ("NGA", "PCPIPCH", 2020, 13.2, False, IMF),
    ("NGA", "PCPIPCH", 2021, 17.0, False, IMF),
    ("NGA", "PCPIPCH", 2022, 18.8, False, IMF),
    ("NGA", "PCPIPCH", 2023, 24.7, False, IMF),
    ("KEN", "SL.UEM.TOTL.ZS", 2020, None, False, WB),
    ("KEN", "SL.UEM.TOTL.ZS", 2021, None, False, WB),
    ("KEN", "NY.GDP.MKTP.CD", 2020, 100.0, False, WB),
]


def build(out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE dim_country (country_code VARCHAR, country_name VARCHAR, sub_region VARCHAR)"
    )
    con.executemany("INSERT INTO dim_country VALUES (?, ?, ?)", COUNTRIES)
    con.execute(
        "CREATE TABLE dim_indicator (indicator_code VARCHAR, indicator_name VARCHAR, "
        "category VARCHAR, metric_unit VARCHAR, data_source VARCHAR)"
    )
    con.executemany("INSERT INTO dim_indicator VALUES (?, ?, ?, ?, ?)", INDICATORS)
    con.execute(
        "CREATE TABLE fact_macroeconomic_indicators (country_code VARCHAR, "
        "indicator_code VARCHAR, report_year INTEGER, indicator_value DOUBLE, "
        "is_forecast BOOLEAN, data_source VARCHAR, ingestion_date DATE)"
    )
    con.executemany(
        "INSERT INTO fact_macroeconomic_indicators VALUES (?, ?, ?, ?, ?, ?, DATE '2026-10-29')",
        FACTS,
    )
    for table in ("dim_country", "dim_indicator", "fact_macroeconomic_indicators"):
        path = str(out / f"{table}.parquet").replace("'", "''")
        con.execute(f"COPY {table} TO '{path}' (FORMAT parquet)")


if __name__ == "__main__":
    build()

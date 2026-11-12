"""Build the demo Parquet snapshot from the CSV exports of the curated tables.

Usage:

    uv run --with duckdb==1.4.1 python data/demo/build_snapshot.py <csv-dir>

<csv-dir> holds the BigQuery console exports of dim_country, dim_indicator,
fact_fx_rates and fact_macroeconomic_indicators, named <table>.csv. The
script writes one Parquet file per table next to this file.

Rows are filtered, never edited: the dimension tables and fact_fx_rates are
copied in full, and fact_macroeconomic_indicators keeps every row whose
indicator_code is in SUPPORTED_INDICATORS (the "Supported indicators" list in
_docs/data-contract.md), including forecast rows and NULL values. Column
types are set here from the data contract, never inferred from the CSV.

This is a standalone tool; copilot_core and backend do not import it.
"""

import argparse
import sys
from pathlib import Path

import duckdb

OUTPUT_DIR = Path(__file__).resolve().parent

# The "Supported indicators" list in _docs/data-contract.md (#6).
SUPPORTED_INDICATORS = [
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
]


def timestamp(column: str) -> str:
    # BigQuery exports timestamps as '2026-09-24 00:00:02.000000 UTC'.
    return f"cast(replace({column}, ' UTC', '+00') as timestamptz) as {column}"


def text(column: str) -> str:
    # The console writes NULL as an empty field.
    return f"nullif({column}, '') as {column}"


# One SELECT per table: columns in contract order, types set explicitly.
TABLES = {
    "dim_country": (
        [
            text(c)
            for c in (
                "country_code",
                "iso2_code",
                "country_name",
                "region",
                "sub_region",
                "currency_code",
                "income_group",
                "capital",
            )
        ],
        None,
        "country_code",
    ),
    "dim_indicator": (
        [
            text(c)
            for c in ("indicator_code", "indicator_name", "category", "metric_unit", "data_source")
        ],
        None,
        "indicator_code",
    ),
    "fact_fx_rates": (
        [
            text("record_id"),
            text("country_code"),
            text("base_currency"),
            text("data_source"),
            "cast(nullif(fx_rate_usd, '') as double) as fx_rate_usd",
            timestamp("rate_timestamp"),
            timestamp("loaded_at"),
            "cast(nullif(ingestion_date, '') as date) as ingestion_date",
        ],
        None,
        "country_code, ingestion_date, record_id",
    ),
    "fact_macroeconomic_indicators": (
        [
            text("indicator_key"),
            text("record_id"),
            text("country_code"),
            text("indicator_code"),
            "cast(nullif(report_year, '') as integer) as report_year",
            "cast(nullif(report_date, '') as date) as report_date",
            "cast(nullif(indicator_value, '') as double) as indicator_value",
            text("data_source"),
            "cast(nullif(is_forecast, '') as boolean) as is_forecast",
            timestamp("loaded_at"),
            "cast(nullif(ingestion_date, '') as date) as ingestion_date",
        ],
        "indicator_code in (select unnest(?))",
        "country_code, indicator_code, report_year, data_source",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv_dir", type=Path, help="directory holding the four CSV exports")
    args = parser.parse_args()

    con = duckdb.connect()
    con.execute("set TimeZone = 'UTC'")
    for name, (columns, where, order) in TABLES.items():
        source = args.csv_dir / f"{name}.csv"
        if not source.is_file():
            sys.exit(f"missing export: {name}.csv in the given directory")
        target = OUTPUT_DIR / f"{name}.parquet"
        params = [source.as_posix()]
        sql = f"select {', '.join(columns)} from read_csv(?, header = true, all_varchar = true)"
        if where:
            sql += f" where {where}"
            params.append(SUPPORTED_INDICATORS)
        sql += f" order by {order}"
        con.execute(
            f"copy ({sql}) to '{target.as_posix()}' (format parquet, compression zstd)",
            params,
        )
        count = con.execute(f"select count(*) from '{target.as_posix()}'").fetchone()[0]
        print(f"{target.name}: {count} rows")


if __name__ == "__main__":
    main()

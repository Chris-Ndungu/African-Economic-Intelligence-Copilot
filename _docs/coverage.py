"""Measure data coverage of the curated tables from their CSV exports.

Usage:

    uv run --with duckdb==1.4.1 python _docs/coverage.py <csv-dir>

<csv-dir> holds the CSV exports of dim_country, dim_indicator, fact_fx_rates
and fact_macroeconomic_indicators, named <table>.csv. The script writes the
coverage matrix to _docs/coverage.csv (next to this file) and prints the
figures quoted in _docs/data-contract.md, as Markdown, to standard output.

Rules (see the Coverage section of _docs/data-contract.md):

- Actual values only: rows with is_forecast = true are left out of first
  year, last year, percent missing and staleness.
- Missing data is not zero: a row whose indicator_value is NULL and a year
  with no row both count as missing.
- Each indicator's window runs from its earliest actual year with a value in
  any country to its latest actual year with a value in any country.
- Percent missing = (years in the window without a value) / (years in the
  window) * 100, rounded to one decimal place.
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import duckdb

PROFILING_DATE = date(2026, 11, 11)
# An annual series is stale when its last actual value is older than this year.
ANNUAL_STALE_BEFORE = 2024
# FX is stale when the latest capture is more than this many days old.
FX_STALE_DAYS = 14
# Supported-indicator rule.
MIN_YEARS = 10
MIN_COUNTRIES = 40
# Concepts held by both sources: (concept, IMF code, World Bank code).
OVERLAPS = [
    ("GDP, current prices", "NGDPD", "NY.GDP.MKTP.CD"),
    ("Real GDP growth", "NGDP_RPCH", "NY.GDP.MKTP.KD.ZG"),
    ("GDP per capita", "NGDPDPC", "NY.GDP.PCAP.CD"),
    ("Inflation (annual average CPI)", "PCPIPCH", "FP.CPI.TOTL.ZG"),
    ("Current account balance", "BCA_NGDPD", "BN.CAB.XOKA.GD.ZS"),
    ("Unemployment rate", "LUR", "SL.UEM.TOTL.ZS"),
    ("Population", "LP", "SP.POP.TOTL"),
]
OUTPUT = Path(__file__).resolve().parent / "coverage.csv"


def load(con: duckdb.DuckDBPyConnection, csv_dir: Path) -> None:
    def path(name: str) -> str:
        file = csv_dir / f"{name}.csv"
        if not file.is_file():
            sys.exit(f"missing export: {file.name} in the given directory")
        return file.as_posix()

    con.execute(
        "create table dim_country as select * from read_csv(?, header = true, all_varchar = true)",
        [path("dim_country")],
    )
    con.execute(
        "create table dim_indicator as select * from read_csv(?, header = true, all_varchar = true)",
        [path("dim_indicator")],
    )
    con.execute(
        """
        create table macro as
        select
            country_code,
            indicator_code,
            cast(report_year as integer) as report_year,
            try_cast(nullif(indicator_value, '') as double) as indicator_value,
            data_source,
            cast(is_forecast as boolean) as is_forecast
        from read_csv(?, header = true, all_varchar = true)
        """,
        [path("fact_macroeconomic_indicators")],
    )
    con.execute(
        """
        create table fx as
        select
            country_code,
            cast(ingestion_date as date) as capture_date,
            fx_rate_usd
        from read_csv(?, header = true, all_varchar = true)
        """,
        [path("fact_fx_rates")],
    )
    con.execute(
        """
        create view actual as
        select * from macro where not is_forecast and indicator_value is not null
        """
    )
    con.execute(
        """
        create table windows as
        select indicator_code, min(report_year) as first_year, max(report_year) as last_year,
               max(report_year) - min(report_year) + 1 as window_years
        from actual group by indicator_code
        """
    )
    con.execute(
        """
        create table cells as
        select c.country_code, i.indicator_code,
               min(a.report_year) as first_year,
               max(a.report_year) as last_year,
               count(distinct a.report_year) as years_with_value,
               w.window_years
        from dim_country c
        cross join dim_indicator i
        left join windows w on w.indicator_code = i.indicator_code
        left join actual a
               on a.country_code = c.country_code and a.indicator_code = i.indicator_code
        group by all
        """
    )


def pct_missing(years_with_value: int, window_years: int | None) -> float | None:
    if not window_years:
        return None
    return round(100 * (window_years - years_with_value) / window_years, 1)


def rows(con, sql: str, params=None) -> list[tuple]:
    return con.execute(sql, params or []).fetchall()


def table(header: list[str], body: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in body:
        out.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(out)


def write_matrix(con, codes: list[str]) -> None:
    cells = {(c, i): (f, last, n, w) for c, i, f, last, n, w in rows(con, "select * from cells")}
    countries = rows(
        con, "select country_code, country_name from dim_country order by country_code"
    )
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["country_code", "country_name", *codes])
        for code, name in countries:
            line = [code, name]
            for indicator in codes:
                first, last, n, window = cells[(code, indicator)]
                if not n:
                    line.append("")
                else:
                    line.append(f"{first}-{last} ({pct_missing(n, window)}% missing)")
            writer.writerow(line)


def report(con, codes: list[str]) -> None:
    print(f"# Coverage figures, profiled against {PROFILING_DATE.isoformat()}\n")

    print("## Row counts\n")
    print(
        table(
            ["data_source", "rows", "NULL indicator_value", "is_forecast = true"],
            [
                list(r)
                for r in rows(
                    con,
                    """
            select data_source, count(*), count(*) filter (where indicator_value is null),
                   count(*) filter (where is_forecast)
            from macro group by data_source order by data_source""",
                )
            ],
        )
    )
    total = rows(con, "select count(*) from macro")[0][0]
    dupes = rows(
        con,
        """select count(*) from (select country_code, indicator_code, report_year
                         from macro group by all having count(*) > 1)""",
    )[0][0]
    unknown_codes = rows(
        con,
        """select distinct indicator_code from macro
                                 where indicator_code not in (select indicator_code from dim_indicator)""",
    )
    unknown_countries = rows(
        con,
        """select distinct country_code from macro
                                     where country_code not in (select country_code from dim_country)""",
    )
    print(f"\nTotal rows: {total}. Duplicate country-indicator-year keys: {dupes}.")
    print(
        f"Codes in dim_indicator: {len(codes)}. Codes in the fact: "
        f"{rows(con, 'select count(distinct indicator_code) from macro')[0][0]}."
    )
    print(
        f"Fact codes not in dim_indicator: {[r[0] for r in unknown_codes]}. "
        f"Fact countries not in dim_country: {[r[0] for r in unknown_countries]}."
    )
    print("Countries in dim_country:", rows(con, "select count(*) from dim_country")[0][0])

    print("\n## is_forecast by source and year\n")
    print(
        table(
            ["data_source", "is_forecast", "first year", "last year", "rows"],
            [
                list(r)
                for r in rows(
                    con,
                    """
            select data_source, is_forecast, min(report_year), max(report_year), count(*)
            from macro group by all order by 1, 2""",
                )
            ],
        )
    )

    print("\n## Indicator windows (actual values only)\n")
    body = []
    for r in rows(
        con,
        """
        select i.indicator_code, i.data_source, i.metric_unit, w.first_year, w.last_year,
               w.window_years,
               (select count(*) from macro m where m.indicator_code = i.indicator_code
                  and not m.is_forecast and m.indicator_value is null) as null_rows,
               (select count(distinct country_code) from actual a
                  where a.indicator_code = i.indicator_code) as countries,
               (select count(*) from cells c where c.indicator_code = i.indicator_code
                  and c.years_with_value >= ?) as countries_min_years,
               (select count(*) from cells c where c.indicator_code = i.indicator_code
                  and c.last_year >= ?) as countries_current,
               (select round(100.0 * sum(c.window_years - c.years_with_value)
                       / sum(c.window_years), 1)
                  from cells c where c.indicator_code = i.indicator_code) as pct_missing_all
        from dim_indicator i left join windows w using (indicator_code)
        order by i.data_source, i.indicator_code""",
        [MIN_YEARS, ANNUAL_STALE_BEFORE],
    ):
        body.append(list(r))
    print(
        table(
            [
                "code",
                "source",
                "unit",
                "window first",
                "window last",
                "window years",
                "NULL actual rows",
                "countries with a value",
                f"countries with >= {MIN_YEARS} years",
                f"countries with last year >= {ANNUAL_STALE_BEFORE}",
                "% missing, all 54 countries",
            ],
            body,
        )
    )
    stats = {r[0]: r for r in body}

    print("\n## IMF forecast years (excluded from the matrix)\n")
    print(
        table(
            ["code", "first forecast year", "last forecast year", "forecast rows", "countries"],
            [
                list(r)
                for r in rows(
                    con,
                    """
            select indicator_code, min(report_year), max(report_year), count(*),
                   count(distinct country_code)
            from macro where is_forecast group by 1 order by 1""",
                )
            ],
        )
    )

    print("\n## Supported-indicator rule\n")
    print(
        f"Rule: at least {MIN_COUNTRIES} of 54 countries have {MIN_YEARS} or more actual "
        f"years with a value, and at least {MIN_COUNTRIES} countries have a last actual "
        f"year of {ANNUAL_STALE_BEFORE} or later.\n"
    )
    passes = {code: s[8] >= MIN_COUNTRIES and s[9] >= MIN_COUNTRIES for code, s in stats.items()}
    print(
        table(
            ["code", f">= {MIN_YEARS} years", f"last >= {ANNUAL_STALE_BEFORE}", "rule met"],
            [[c, stats[c][8], stats[c][9], "yes" if passes[c] else "no"] for c in stats],
        )
    )

    print("\n## Overlapping concepts\n")
    body = []
    for concept, imf, wb in OVERLAPS:
        for code in (imf, wb):
            s = stats[code]
            body.append([concept, code, s[7], s[8], s[9], f"{s[3]}-{s[4]}", s[10]])
    print(
        table(
            [
                "concept",
                "code",
                "countries with a value",
                f">= {MIN_YEARS} years",
                f"last >= {ANNUAL_STALE_BEFORE}",
                "window",
                "% missing",
            ],
            body,
        )
    )

    print(f"\n## Stale annual series (last actual year before {ANNUAL_STALE_BEFORE})\n")
    print(
        table(
            ["code", "countries"],
            [
                list(r)
                for r in rows(
                    con,
                    """
        select indicator_code,
               string_agg(country_code || ' (' || last_year || ')', ', ' order by country_code)
        from cells where years_with_value > 0 and last_year < ?
        group by 1 order by 1""",
                    [ANNUAL_STALE_BEFORE],
                )
            ],
        )
    )

    print("\n## Entirely missing country-indicator pairs\n")
    print(
        table(
            ["code", "countries"],
            [
                list(r)
                for r in rows(
                    con,
                    """
        select indicator_code, string_agg(country_code, ', ' order by country_code)
        from cells where years_with_value = 0 group by 1 order by 1""",
                )
            ],
        )
    )

    print("\n## Countries with no macro data at all\n")
    print(
        [
            r[0]
            for r in rows(
                con,
                """
        select country_code from cells group by 1 having sum(years_with_value) = 0
        order by 1""",
            )
        ]
    )

    print("\n## FX capture dates\n")
    first, last, n = rows(
        con,
        """select min(capture_date), max(capture_date),
                                  count(distinct capture_date) from fx""",
    )[0]
    print(
        f"{n} capture dates from {first} to {last}; latest is "
        f"{(PROFILING_DATE - last).days} days before {PROFILING_DATE}."
    )
    print(
        "Dates:",
        ", ".join(str(r[0]) for r in rows(con, "select distinct capture_date from fx order by 1")),
    )
    print(
        "Rows per date:",
        ", ".join(
            f"{r[0]}: {r[1]}"
            for r in rows(con, "select capture_date, count(*) from fx group by 1 order by 1")
        ),
    )
    print(
        "NULL fx_rate_usd rows:",
        rows(con, "select count(*) from fx where fx_rate_usd is null or fx_rate_usd = ''")[0][0],
    )

    print("\n## FX per country\n")
    fx_rows = rows(
        con,
        """
        with d as (
            select country_code, capture_date, fx_rate_usd,
                   capture_date - lag(capture_date) over (
                       partition by country_code order by capture_date) as gap
            from fx
        ), s as (
            select country_code, count(distinct capture_date) as n,
                   min(capture_date) as first_date, max(capture_date) as last_date,
                   max(gap) as max_gap,
                   arg_max(fx_rate_usd, capture_date) as latest_rate
            from d group by 1
        )
        select c.country_code, c.currency_code, s.n, s.first_date, s.last_date, s.max_gap,
               s.latest_rate
        from dim_country c left join s using (country_code) order by c.country_code""",
    )
    body = []
    for code, currency, n, f, last, gap, rate in fx_rows:
        stale = (
            None
            if last is None
            else ("yes" if (PROFILING_DATE - last).days > FX_STALE_DAYS else "no")
        )
        body.append([code, currency, n, f, last, gap, rate, stale])
    print(
        table(
            [
                "country",
                "currency",
                "capture dates",
                "first",
                "last",
                "largest gap (days)",
                "latest fx_rate_usd",
                f"stale (> {FX_STALE_DAYS} days)",
            ],
            body,
        )
    )
    print("\nCountries with FX data:", sum(1 for r in fx_rows if r[2]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv_dir", type=Path, help="directory holding the four CSV exports")
    args = parser.parse_args()
    con = duckdb.connect()
    load(con, args.csv_dir)
    codes = [r[0] for r in rows(con, "select indicator_code from dim_indicator order by 1")]
    write_matrix(con, codes)
    report(con, codes)


if __name__ == "__main__":
    main()

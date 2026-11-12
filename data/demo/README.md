# Demo data snapshot

**This is sample data, not live data.** It is a fixed snapshot of the
curated BigQuery tables taken on 2026-11-11. Demo mode, local development,
tests and CI read it. Nothing here updates, and figures newer than the
snapshot date are not in it.

The tables, columns, units and coverage are described in the
[data contract](../../_docs/data-contract.md). This folder holds only the
four tables the copilot reads; the analytics marts are not included, because
the copilot does not read them.

## Files

| File | Rows | Countries | Indicators | Period |
| --- | --- | --- | --- | --- |
| `dim_country.parquet` | 54 | 54 | n/a | n/a |
| `dim_indicator.parquet` | 24 | n/a | 24 (all codes, including unsupported ones) | n/a |
| `fact_macroeconomic_indicators.parquet` | 29,057 | 54 | 14 (the supported indicators) | Actual years 1980–2026 (IMF) and 2000–2025 (World Bank); IMF forecast years 2027–2031 |
| `fact_fx_rates.parquet` | 736 | 53 | n/a (`fx_rate_usd`) | 14 capture dates, 2026-09-19 to 2026-10-29 |

`fact_macroeconomic_indicators.parquet` holds 22,303 IMF DataMapper rows
(9 indicators) and 6,754 World Bank rows (5 indicators). 2,340 rows are IMF
forecasts (`is_forecast = true`) and 559 rows have a NULL `indicator_value`.
Both are kept: forecasts must be shown labelled as forecasts, and a NULL is
missing data, never zero.

**FX is an irregular snapshot, not a daily series.** It has 14 capture dates
between 2026-09-19 and 2026-10-29, with gaps of up to 13 days. Botswana has
no rows and Burkina Faso starts on 2026-10-16. The copilot offers FX only as
the latest available rate, with its date.

## What was kept

Rows are filtered, never edited, and no values are added.

- `dim_country`, `dim_indicator` and `fact_fx_rates`: every row of the
  export.
- `fact_macroeconomic_indicators`: every row whose `indicator_code` is on
  the "Supported indicators" list in the data contract, for all countries
  and years, including forecast rows and NULL values. Rows for the ten
  unsupported codes are left out.

Examples for testing missing data (all from "Known gaps" in the data
contract):

- **Country-indicator pair with no rows:** Somalia (`SOM`) has no rows for
  general government gross debt (`GGXWDG_NGDP`).
- **Stale series:** Eritrea (`ERI`) has no actual IMF GDP (`NGDPD`) value
  after 2019.
- **Rows that exist with NULL values:** Seychelles (`SYC`) has 25 rows for
  unemployment (`SL.UEM.TOTL.ZS`), all with a NULL `indicator_value`.

## Types

The BigQuery types come from the data contract, where they are recorded as
**unverified**: they were read from the dbt SQL and the export headers, not
the live schema. The script sets every Parquet type explicitly; nothing is
inferred from the CSV.

| BigQuery type | Parquet type (DuckDB) | Columns | Note |
| --- | --- | --- | --- |
| STRING | string (`VARCHAR`) | codes, names, `record_id`, `indicator_key`, `data_source`, `base_currency` | same |
| INT64 | int32 (`INTEGER`) | `report_year` | narrower integer; every year fits |
| DATE | date (`DATE`) | `report_date`, `ingestion_date` | same |
| FLOAT64 | double (`DOUBLE`) | `indicator_value` | same |
| NUMERIC | double (`DOUBLE`) | `fx_rate_usd` | differs: BigQuery NUMERIC is exact decimal; the export has at most four decimals, so every value is represented as exported |
| BOOL | boolean (`BOOLEAN`) | `is_forecast` | same |
| TIMESTAMP | timestamp, UTC (`TIMESTAMP WITH TIME ZONE`) | `loaded_at`, `rate_timestamp` | same; parsed from values such as `2026-09-24 00:00:02.000000 UTC` |

## Sources, licences and attribution

Snapshot date: 2026-11-11, the date of the CSV exports. The tables were
built by the ingestion repository
[African-Market-Intelligence](https://github.com/Chris-Ndungu/African-Market-Intelligence)
at commit
[`e61e67a606e60e2631dc98a9e1a2949cee60087e`](https://github.com/Chris-Ndungu/African-Market-Intelligence/tree/e61e67a606e60e2631dc98a9e1a2949cee60087e).

| Source | Data | Licence and attribution |
| --- | --- | --- |
| International Monetary Fund, World Economic Outlook, via the [IMF DataMapper API](https://www.imf.org/external/datamapper/api/help) | IMF indicators and forecasts | Used under the [IMF Copyright and Usage terms](https://www.imf.org/external/terms.htm), which allow reuse with attribution. Attribution: "Source: International Monetary Fund, World Economic Outlook." |
| World Bank, [World Development Indicators](https://datacatalog.worldbank.org/search/dataset/0037712) | World Bank indicators | [Creative Commons Attribution 4.0 (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). Attribution: "Source: World Bank, World Development Indicators." |
| [ExchangeRate-API](https://www.exchangerate-api.com) | `fact_fx_rates` | Used under the ExchangeRate-API [terms of use](https://www.exchangerate-api.com/terms). Attribution: "Rates by Exchange Rate API" with a link to https://www.exchangerate-api.com. |

## Regenerating the snapshot

You need read access to the curated dataset in the BigQuery console.

1. In the BigQuery console, run each query below, replacing `<project>`
   with the project that holds the dataset:

   ```sql
   SELECT * FROM `<project>.dbt_african_macro.dim_country`;
   SELECT * FROM `<project>.dbt_african_macro.dim_indicator`;
   SELECT * FROM `<project>.dbt_african_macro.fact_fx_rates`;
   SELECT * FROM `<project>.dbt_african_macro.fact_macroeconomic_indicators`;
   ```

2. For each result, choose **Save results**, then **CSV (Google Drive)** or
   **CSV (local file)**, and name the file after the table, for example
   `fact_macroeconomic_indicators.csv`. A local download is capped at the
   first 10 MB of results, so check that the row count matches the query
   result; if it is cut off, save to Google Drive and download from there.
3. Put the four CSV files in one folder outside the repository and run, from
   the repository root:

   ```sh
   uv run --with duckdb==1.4.1 python data/demo/build_snapshot.py <csv-dir>
   ```

   The script writes the four Parquet files to `data/demo/` and prints each
   row count. Running it twice on the same exports produces identical
   files.
4. Update the snapshot date, row counts and commit in this README, and
   re-profile the data contract with `_docs/coverage.py`.

Do not commit the CSV exports.

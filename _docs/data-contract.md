# Data contract

The curated BigQuery models the copilot reads, their fields, types and units, and the measured coverage of countries, indicators and periods.

## Models

The curated models are built by dbt in the ingestion repository
[African-Market-Intelligence](https://github.com/Chris-Ndungu/African-Market-Intelligence),
inspected at commit
[`e61e67a606e60e2631dc98a9e1a2949cee60087e`](https://github.com/Chris-Ndungu/African-Market-Intelligence/tree/e61e67a606e60e2631dc98a9e1a2949cee60087e).
All of them live in the BigQuery dataset `dbt_african_macro`. This document
writes the GCP project as the placeholder `<project>`; the live project comes
from configuration, never from this file.

### Source of this contract

- Column names and types come from the dbt model SQL under `dbt/models/`,
  from `dbt/models/marts/marts.yml` and from the ingestion `README.md`, all
  at the commit above.
- The column lists of `dim_country`, `dim_indicator`, `fact_fx_rates` and
  `fact_macroeconomic_indicators` also come from the header row of CSV
  exports of those tables, taken from the BigQuery console on 2026-11-11.
  The three `mart_*` models were not exported.
- None of it was checked against the live BigQuery schema. Every type below
  is therefore marked "unverified". Where the mart SQL passes a column
  through from another model without casting it, the type column names the
  file it was inferred from. Checking the types against the live schema is
  #49.

### Summary

| Model | BigQuery name | Grain | Read by the copilot |
| --- | --- | --- | --- |
| `dim_country` | `<project>.dbt_african_macro.dim_country` | one row per country | read by the copilot |
| `dim_indicator` | `<project>.dbt_african_macro.dim_indicator` | one row per indicator code | read by the copilot |
| `fact_macroeconomic_indicators` | `<project>.dbt_african_macro.fact_macroeconomic_indicators` | one row per source, country, indicator and year | read by the copilot |
| `fact_fx_rates` | `<project>.dbt_african_macro.fact_fx_rates` | one row per country and capture date | read by the copilot |
| `mart_country_profile` | `<project>.dbt_african_macro.mart_country_profile` | one row per fact row (source, country, indicator and year) | documented only, not read by the copilot |
| `mart_fx_trends` | `<project>.dbt_african_macro.mart_fx_trends` | one row per country, base currency and capture date | documented only, not read by the copilot |
| `mart_inflation_gdp` | `<project>.dbt_african_macro.mart_inflation_gdp` | one row per country, indicator and year, for three World Bank codes | documented only, not read by the copilot |

All seven are materialized as tables (`dbt_project.yml`).

### `dim_country`

- BigQuery name: `<project>.dbt_african_macro.dim_country`
- Built from: the seed `dbt/seeds/dim_country_seed.csv`, selected unchanged
  by `dbt/models/marts/dimensions/dim_country.sql`
- Grain: one row per African country (54 rows)
- Primary key: `country_code`
- Read by the copilot: **read by the copilot**. It names countries and gives
  their region, income group and currency.

| Column | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `country_code` | STRING, unverified (inferred from the seed CSV; no `column_types` set) | n/a | ISO 3166-1 alpha-3 code, the canonical country key in every model |
| `iso2_code` | STRING, unverified (inferred from the seed CSV) | n/a | ISO 3166-1 alpha-2 code |
| `country_name` | STRING, unverified (inferred from the seed CSV) | n/a | English country name |
| `region` | STRING, unverified (inferred from the seed CSV) | n/a | Continent, always `Africa` |
| `sub_region` | STRING, unverified (inferred from the seed CSV) | n/a | UN sub-region, for example `Eastern Africa` |
| `currency_code` | STRING, unverified (inferred from the seed CSV) | n/a | ISO 4217 code of the national currency; the only link from `fact_fx_rates` to a currency |
| `income_group` | STRING, unverified (inferred from the seed CSV) | n/a | World Bank income group, for example `Low income` |
| `capital` | STRING, unverified (inferred from the seed CSV) | n/a | Capital city |

- SQL and export: the export header matches the SQL column list exactly.
- Source-metadata columns: none.
- dbt tests: `not_null` on every column; `unique` on `country_code` and
  `iso2_code`; singular test `dbt/tests/assert_dim_country_has_54_countries.sql`.

### `dim_indicator`

- BigQuery name: `<project>.dbt_african_macro.dim_indicator`
- Built from: `stg_world_bank__indicators` and `stg_imf__indicators`, unioned
  and grouped by `indicator_code` with `max()` on the other columns
  (`dbt/models/marts/dimensions/dim_indicator.sql`)
- Grain: one row per indicator code (24 rows in the export: 10 IMF
  DataMapper, 14 World Bank)
- Primary key: `indicator_code`
- Read by the copilot: **read by the copilot**. It gives each indicator its
  name, category and unit.

| Column | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `indicator_code` | STRING, unverified (inferred from `trim()` in the two `stg_*__indicators.sql` files) | n/a | Source indicator code, for example `NGDPD` (IMF) or `NY.GDP.MKTP.CD` (World Bank) |
| `indicator_name` | STRING, unverified (inferred from the staging files) | n/a | Indicator name as the source publishes it |
| `category` | STRING, unverified (inferred from the staging files) | n/a | Theme, one of `GDP`, `INFLATION`, `TRADE`, `DEBT`, `FISCAL`, `LABOUR`, `DEMOGRAPHICS`, `INVESTMENT`, `SAVINGS`, `FINANCIAL`, `DIGITAL` |
| `metric_unit` | STRING, unverified (inferred from the staging files, mapped from raw `unit`) | n/a | Unit of `indicator_value` for this code, for example `%`, `USD`, `USD_BN`, `MILLIONS`, `persons` |
| `data_source` | STRING, unverified (inferred from the staging files) | n/a | Source name, `IMF DataMapper` or `World Bank` |

- SQL and export: the export header matches the SQL column list exactly.
- Source-metadata columns: `data_source` (source name), `indicator_code`
  (source indicator code). No load or update time.
- dbt tests: `not_null` and `unique` on `indicator_code`; `not_null` and
  `accepted_values` (the eleven categories above) on `category`. No singular
  tests.

### `fact_macroeconomic_indicators`

- BigQuery name: `<project>.dbt_african_macro.fact_macroeconomic_indicators`
- Built from: `stg_world_bank__indicators` and `stg_imf__indicators`, joined
  with `union all` (`dbt/models/marts/facts/fact_macroeconomic_indicators.sql`).
  Each staging model keeps the latest load per country, indicator and year.
- Grain: one row per source, country, indicator and year. Indicator codes
  differ between sources, so in practice one row per country, indicator code
  and year
- Primary key: `indicator_key`
- Read by the copilot: **read by the copilot**. It holds every annual
  indicator value.

| Column | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `indicator_key` | STRING, unverified (`to_hex(md5(...))` in the fact SQL) | n/a | Hash of source prefix (`WB-` or `IMF-`), country, indicator and year |
| `record_id` | STRING, unverified (inferred from `trim(record_id)` in the staging files) | n/a | Record id assigned by the ingestion scripts |
| `country_code` | STRING, unverified (inferred from the staging files) | n/a | ISO3 country code, joins `dim_country.country_code` |
| `indicator_code` | STRING, unverified (inferred from the staging files) | n/a | Source indicator code, joins `dim_indicator.indicator_code` |
| `report_year` | INT64, unverified (`cast(year as int64)` in the staging files) | year | Calendar year of the observation |
| `report_date` | DATE, unverified (`parse_date` in the staging files) | n/a | 31 December of `report_year` |
| `indicator_value` | FLOAT64, unverified (inferred: `stg_world_bank__indicators.sql` casts to NUMERIC, `stg_imf__indicators.sql` to FLOAT64, and `union all` coerces to FLOAT64; the README says "NUMERIC/FLOAT64") | `dim_indicator.metric_unit` of the row's code | The observed or forecast value |
| `data_source` | STRING, unverified (inferred from the staging files) | n/a | `IMF DataMapper` or `World Bank` |
| `is_forecast` | BOOL, unverified (literal `false` for World Bank in the fact SQL; `coalesce(is_forecast, false)` in `stg_imf__indicators.sql`) | n/a | True for IMF projection years; always false for World Bank |
| `loaded_at` | TIMESTAMP, unverified (cast in the staging files) | UTC | When the ingestion script loaded the row |
| `ingestion_date` | DATE, unverified (cast in the staging files) | n/a | Raw partition date of the load |

- SQL and export: the export header matches the SQL column list exactly. The
  README's table of this model lists only a subset (no `record_id`,
  `report_date`, `is_forecast` or `ingestion_date`).
- Source-metadata columns: `data_source` (source name), `indicator_code`
  (source indicator code), `loaded_at` and `ingestion_date` (load time). No
  source publication or revision date.
- dbt tests: `not_null` and `unique` on `indicator_key`; `not_null` and
  `country_code_relationship` (custom generic test in
  `dbt/macros/test_country_code_relationship.sql`) on `country_code`;
  `not_null` on `indicator_code`. No singular tests.

### `fact_fx_rates`

- BigQuery name: `<project>.dbt_african_macro.fact_fx_rates`
- Built from: `stg_fx_rates__daily_rates`, selected unchanged
  (`dbt/models/marts/facts/fact_fx_rates.sql`). Partitioned by
  `ingestion_date`, clustered by `country_code`, rebuilt on every run.
- Grain: one row per country and capture date (`ingestion_date`). The base
  currency is always USD
- Primary key: `record_id`; `country_code` with `ingestion_date` is also
  tested unique
- Read by the copilot: **read by the copilot**. It is the only source of
  exchange rates.

| Column | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `record_id` | STRING, unverified (inferred from `to_hex(md5(...))` in `stg_fx_rates__daily_rates.sql`) | n/a | Hash of base currency, raw country id and ingestion date |
| `country_code` | STRING, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | n/a | ISO3 country code; the currency is `dim_country.currency_code` |
| `base_currency` | STRING, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | n/a | Currency the rate is quoted against, always `USD` |
| `data_source` | STRING, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | n/a | Provider, `ExchangeRate-API` |
| `fx_rate_usd` | NUMERIC, unverified (`cast(... as numeric)` in `stg_fx_rates__daily_rates.sql`; FLOAT64 in the raw table) | units of local currency per 1 USD | Exchange rate from the provider's `latest/USD` endpoint |
| `rate_timestamp` | TIMESTAMP, unverified (cast in `stg_fx_rates__daily_rates.sql`) | UTC | Provider's timestamp for the rate |
| `loaded_at` | TIMESTAMP, unverified (cast in `stg_fx_rates__daily_rates.sql`) | UTC | When the ingestion script loaded the row |
| `ingestion_date` | DATE, unverified (cast in `stg_fx_rates__daily_rates.sql`) | n/a | Capture date, the partition column |

- SQL and export: the export header matches the SQL column list exactly. The
  raw table also has `currency_code`, which staging drops.
- Source-metadata columns: `data_source` (source name), `rate_timestamp`
  (source update time), `loaded_at` and `ingestion_date` (load time). No
  source indicator code.
- dbt tests: `dbt_utils.unique_combination_of_columns` on `country_code` and
  `ingestion_date`; the same on `country_code` and `rate_timestamp` as a
  warning (`fact_fx_rates_stale_provider_rate`); `not_null` and `unique` on
  `record_id`; `not_null` and `country_code_relationship` on `country_code`;
  `not_null` on `fx_rate_usd` and `rate_timestamp`. No singular tests.

### `mart_country_profile`

- BigQuery name: `<project>.dbt_african_macro.mart_country_profile`
- Built from: `fact_macroeconomic_indicators`, `fact_fx_rates`,
  `dim_country` and `dim_indicator`
  (`dbt/models/marts/analytics/mart_country_profile.sql`)
- What it computes: each fact row with country and indicator names, the
  country's latest FX rate and a 0-100 risk score. The score is the mean of
  the available components: latest actual inflation (`PCPIPCH`, `PCPIEPCH`
  or `FP.CPI.TOTL.ZG`) clamped from 0-25%, public debt (`GGXWDG_NGDP`) from
  30-120% of GDP, unemployment (`LUR` or `SL.UEM.TOTL.ZS`) from 5-30%, and
  an FX score averaging year-on-year depreciation and annualized 30-day
  volatility, each clamped from 0-50%
- Grain: one row per fact row (source, country, indicator and year)
- Primary key: `indicator_key` (not tested in this model)
- Read by the copilot: **documented only, not read by the copilot**. See
  [Why the copilot does not read the marts](#why-the-copilot-does-not-read-the-marts).
  `indicator_value` and `latest_fx_rate_usd` repeat figures from the fact
  tables; the copilot reads those from `fact_macroeconomic_indicators` and
  `fact_fx_rates`.

| Column | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `indicator_key` | STRING, unverified (inferred from `fact_macroeconomic_indicators.sql`) | n/a | Fact key |
| `report_year` | INT64, unverified (inferred from the staging files) | year | Observation year |
| `country_name` | STRING, unverified (inferred from the seed CSV) | n/a | From `dim_country` |
| `country_code` | STRING, unverified (inferred from the seed CSV) | n/a | From `dim_country`, so null if the fact's code is not in it |
| `indicator_name` | STRING, unverified (inferred from the staging files) | n/a | From `dim_indicator` |
| `category` | STRING, unverified (inferred from the staging files) | n/a | From `dim_indicator` |
| `metric_unit` | STRING, unverified (inferred from the staging files) | n/a | From `dim_indicator` |
| `indicator_value` | FLOAT64, unverified (inferred as for the fact) | `metric_unit` | Fact value |
| `latest_fx_rate_usd` | NUMERIC, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | units of local currency per 1 USD | Rate on the country's latest capture date |
| `risk_score` | FLOAT64, unverified (`round(safe_divide(...), 1)` in the mart SQL) | score 0-100 | Composite risk score, null when no component is available |
| `risk_component_count` | INT64, unverified (sum of `if(..., 1, 0)` in the mart SQL) | count 0-4 | Number of components in `risk_score` |

- Source-metadata columns: none (no source name or load time; the source can
  only be inferred from the indicator code).
- dbt tests: `country_code_relationship` on `country_code`;
  `dbt_utils.accepted_range` 0-100 on `risk_score`; `not_null` and
  `dbt_utils.accepted_range` 0-4 on `risk_component_count`. No singular
  tests.

### `mart_fx_trends`

- BigQuery name: `<project>.dbt_african_macro.mart_fx_trends`
- Built from: `fact_fx_rates` (`dbt/models/marts/analytics/mart_fx_trends.sql`)
- What it computes: each FX row with a 30-day average rate, an annualized
  30-day volatility of day-on-day changes (`* sqrt(365) * 100`, assuming one
  rate per calendar day) and the change from the rate 365-372 days earlier
- Grain: one row per country, base currency and capture date
- Primary key: `record_id` (not tested in this model)
- Read by the copilot: **documented only, not read by the copilot**. See
  [Why the copilot does not read the marts](#why-the-copilot-does-not-read-the-marts).
  `fx_rate_usd` repeats `fact_fx_rates.fx_rate_usd`; the copilot reads the
  fact table.

| Column | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `record_id` | STRING, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | n/a | FX fact key |
| `country_code` | STRING, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | n/a | ISO3 country code |
| `base_currency` | STRING, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | n/a | Always `USD` |
| `ingestion_date` | DATE, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | n/a | Capture date |
| `fx_rate_usd` | NUMERIC, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | units of local currency per 1 USD | Rate on that date |
| `fx_30d_avg` | NUMERIC, unverified (inferred: `avg()` of NUMERIC) | units of local currency per 1 USD | Mean rate over the 30 calendar days ending on that date |
| `fx_yoy_change_pct` | NUMERIC, unverified (inferred: `safe_divide()` of NUMERIC) | % | Change from the latest rate 365-372 days earlier; null without one |
| `volatility_score` | FLOAT64, unverified (inferred: `stddev_pop()` times `sqrt()`) | % annualized | Volatility of day-on-day changes over 30 calendar days |
| `data_source` | STRING, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | n/a | `ExchangeRate-API` |
| `loaded_at` | TIMESTAMP, unverified (inferred from `stg_fx_rates__daily_rates.sql`) | UTC | Load time |

- Source-metadata columns: `data_source` (source name), `loaded_at` (load
  time). No source indicator code.
- dbt tests: `not_null` on `country_code` and `ingestion_date`. No singular
  tests.

### `mart_inflation_gdp`

- BigQuery name: `<project>.dbt_african_macro.mart_inflation_gdp`
- Built from: `fact_macroeconomic_indicators`, `dim_country` and
  `dim_indicator` (`dbt/models/marts/analytics/mart_inflation_gdp.sql`)
- What it computes: nothing new. It filters the fact to the World Bank codes
  `NY.GDP.MKTP.CD`, `NY.GDP.PCAP.CD` and `FP.CPI.TOTL.ZG` and adds country
  and indicator names
- Grain: one row per country, indicator and year, for those three codes
- Primary key: `indicator_key` (not tested in this model)
- Read by the copilot: **documented only, not read by the copilot**. See
  [Why the copilot does not read the marts](#why-the-copilot-does-not-read-the-marts).
  Every value repeats `fact_macroeconomic_indicators.indicator_value`; the
  copilot reads the fact table.

| Column | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `indicator_key` | STRING, unverified (inferred from `fact_macroeconomic_indicators.sql`) | n/a | Fact key |
| `report_year` | INT64, unverified (inferred from the staging files) | year | Observation year |
| `report_date` | DATE, unverified (inferred from the staging files) | n/a | 31 December of `report_year` |
| `country_name` | STRING, unverified (inferred from the seed CSV) | n/a | From `dim_country` |
| `country_code` | STRING, unverified (inferred from the seed CSV) | n/a | From `dim_country` |
| `indicator_name` | STRING, unverified (inferred from the staging files) | n/a | From `dim_indicator` |
| `category` | STRING, unverified (inferred from the staging files) | n/a | From `dim_indicator` |
| `metric_unit` | STRING, unverified (inferred from the staging files) | n/a | From `dim_indicator` |
| `indicator_value` | FLOAT64, unverified (inferred as for the fact) | `metric_unit` (`USD` or `%`) | Fact value |

- Source-metadata columns: none.
- dbt tests: none.

### Why the copilot does not read the marts

1. The marts are derived from the fact tables, and Python in `copilot_core`
   computes every number ([plan.md section 8](plan.md#8-technical-principles-and-implementation-guardrails)).
   The copilot computes trends, changes and comparisons from
   `fact_macroeconomic_indicators` and `fact_fx_rates` itself, so it can
   test the method and cite it.
2. The marts were not exported, so demo mode, which runs on a snapshot of
   the exports, could not serve them.
3. `mart_country_profile` and `mart_fx_trends` compute 30-day FX averages or
   volatility annualized with `sqrt(365)`, assuming one rate per calendar
   day. The FX capture does not support that: the export has 14 capture
   dates between 2026-09-19 and 2026-10-29, with gaps of up to 13 days.

### Indicator areas

Codes and units as listed in `dim_indicator`. Where an IMF and a World Bank
code measure the same figure, both are kept here; #6 picks the preferred
source.

| Area | Model | Indicator codes |
| --- | --- | --- |
| GDP | `fact_macroeconomic_indicators` | IMF: `NGDPD` (USD billions), `NGDPDPC` (USD), `NGDP_RPCH` (%); World Bank: `NY.GDP.MKTP.CD` (USD), `NY.GDP.PCAP.CD` (USD), `NY.GDP.MKTP.KD.ZG` (%) |
| Inflation | `fact_macroeconomic_indicators` | IMF: `PCPIPCH` (%), `PCPIEPCH` (%); World Bank: `FP.CPI.TOTL.ZG` (%) |
| Exchange rates | `fact_fx_rates` | no indicator code; column `fx_rate_usd` |
| Interest rates | not found | not found |
| Trade | `fact_macroeconomic_indicators` | IMF: `BCA_NGDPD` (%); World Bank: `BN.CAB.XOKA.GD.ZS` (%), `NE.EXP.GNFS.CD` (USD), `NE.IMP.GNFS.CD` (USD) |
| Other | `fact_macroeconomic_indicators` | IMF: `GGXWDG_NGDP` (debt), `GGXCNL_NGDP` (fiscal), `LP` (population), `LUR` (unemployment); World Bank: `DT.DOD.DECT.CD` (debt), `BX.KLT.DINV.CD.WD` (investment), `FS.AST.PRVT.GD.ZS` (financial), `NY.GNS.ICTR.ZS` (savings), `SP.POP.TOTL` (population), `SL.UEM.TOTL.ZS` (unemployment), `IT.CEL.SETS.P2` (mobile subscriptions) |

Pairs where IMF and World Bank hold the same figure (see #6 for the
preferred source):

- GDP, current prices: `NGDPD` (USD billions) and `NY.GDP.MKTP.CD` (USD)
- GDP per capita: `NGDPDPC` and `NY.GDP.PCAP.CD`
- Real GDP growth: `NGDP_RPCH` and `NY.GDP.MKTP.KD.ZG`
- CPI inflation: `PCPIPCH` or `PCPIEPCH` and `FP.CPI.TOTL.ZG`
- Current account balance: `BCA_NGDPD` and `BN.CAB.XOKA.GD.ZS`
- Unemployment rate: `LUR` and `SL.UEM.TOTL.ZS`
- Population: `LP` (millions) and `SP.POP.TOTL` (persons)

Where a mart repeats one of these figures, the copilot reads the fact table.

### Staging models

The copilot does not read the staging models. They are views that clean and
deduplicate the raw tables, and the fact and dimension tables above carry
their columns.

- `stg_world_bank__indicators`
- `stg_imf__indicators`
- `stg_fx_rates__daily_rates`

## Coverage

Profiled on 2026-11-11 from the CSV exports of `dim_country`,
`dim_indicator`, `fact_fx_rates` and `fact_macroeconomic_indicators` made
from the BigQuery console that day, built at ingestion commit
[`e61e67a`](https://github.com/Chris-Ndungu/African-Market-Intelligence/tree/e61e67a606e60e2631dc98a9e1a2949cee60087e).
Live BigQuery has not been profiled (#49).

### How to reproduce

[`coverage.py`](coverage.py) reads the four exports, writes the matrix to
[`coverage.csv`](coverage.csv) and prints every figure in this section as
Markdown:

```sh
uv run --with duckdb==1.4.1 python _docs/coverage.py <csv-dir>
```

`<csv-dir>` is the folder holding the exports, named `<table>.csv`. The
exports are not committed. Running the command on the 2026-11-11 exports
reproduces `coverage.csv` exactly.

### Rules

- **Actual values only.** Rows with `is_forecast = true` are left out of
  first year, last year, percent missing and staleness.
- **Missing data is not zero.** A row whose `indicator_value` is NULL and a
  year with no row both count as missing.
- **Window.** Each indicator's window runs from its earliest actual year with
  a value in any country to its latest actual year with a value in any
  country (table below).
- **Percent missing** = years in the indicator's window without a value,
  divided by the years in the window, times 100, rounded to one decimal. A
  country whose series starts later than the window (for example South
  Sudan, independent in 2011) therefore shows a high percent missing.
- **Frequency.** Every macro indicator is annual: one value per country and
  calendar year, dated 31 December. No indicator mixes frequencies. FX is an
  irregular snapshot (see [Exchange rates](#exchange-rates)).
- **Stale.** An annual series is stale when its last actual value is older
  than 2024, that is, more than two calendar years before the profiling year
  2026. An FX series is stale when its latest capture is more than 14 days
  before 2026-11-11.

### How `is_forecast` is set

The IMF ingestion script (`ingestion/imf.py`) sets
`is_forecast = year > CURRENT_YEAR`, using the year of the load (2026).
`stg_imf__indicators.sql` keeps the flag, defaulting NULL to false, and the
fact SQL sets it to `false` for every World Bank row. So IMF values for 2027
to 2031 are flagged as forecasts, but **IMF values for 2026 are flagged as
not forecast**, although the year is not over and the IMF publishes them as
estimates. The copilot treats them as actual, as the flag says, and labels
2026 IMF values "IMF estimate for the current year" when it shows them.

### Row counts

| Source | Rows | NULL `indicator_value` | `is_forecast = true` | Actual years |
| --- | --- | --- | --- | --- |
| IMF DataMapper | 22,741 | 0 | 2,370 (2027–2031) | 1980–2026 |
| World Bank | 18,912 | 1,623 | 0 | 2000–2025 |

41,653 rows in total, with no duplicate country, indicator and year. All 24
codes in `dim_indicator` (10 IMF, 14 World Bank) appear in the fact table,
and every country in the fact table is in `dim_country` (54 countries).
Every country has data for at least one indicator.

### Coverage by indicator

The full matrix, one row per country in `dim_country` and one column per
indicator code, is in [`coverage.csv`](coverage.csv). Each cell reads
`first-last (x% missing)`, for example `1980-2026 (0.0% missing)`. An empty
cell means the country has no actual value for that indicator. This table
summarizes it per indicator.

| Code | Source | Unit | Window | NULL actual rows | Countries with a value | Countries with 10+ years | Countries with last year 2024+ | % missing, all 54 countries |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `BCA_NGDPD` | IMF | % of GDP | 1980–2026 | 0 | 54 | 54 | 53 | 7.2 |
| `GGXCNL_NGDP` | IMF | % of GDP | 1980–2026 | 0 | 54 | 54 | 53 | 27.3 |
| `GGXWDG_NGDP` | IMF | % of GDP | 1980–2026 | 0 | 53 | 53 | 52 | 36.4 |
| `LP` | IMF | millions of persons | 1980–2026 | 0 | 54 | 54 | 53 | 4.8 |
| `LUR` | IMF | % of labour force | 1980–2026 | 0 | 11 | 10 | 8 | 83.9 |
| `NGDPD` | IMF | billions of USD | 1980–2026 | 0 | 54 | 54 | 53 | 5.9 |
| `NGDPDPC` | IMF | USD | 1980–2026 | 0 | 54 | 53 | 53 | 8.0 |
| `NGDP_RPCH` | IMF | annual % change | 1980–2026 | 0 | 54 | 54 | 53 | 6.7 |
| `PCPIEPCH` | IMF | annual % change | 1980–2026 | 0 | 54 | 54 | 53 | 10.6 |
| `PCPIPCH` | IMF | annual % change | 1980–2026 | 0 | 54 | 54 | 53 | 6.6 |
| `BN.CAB.XOKA.GD.ZS` | World Bank | % of GDP | 2000–2025 | 244 | 49 | 49 | 41 | 20.9 |
| `BX.KLT.DINV.CD.WD` | World Bank | USD | 2000–2025 | 22 | 54 | 54 | 54 | 5.1 |
| `DT.DOD.DECT.CD` | World Bank | USD | 2000–2024 | 125 | 49 | 49 | 49 | 9.3 |
| `FP.CPI.TOTL.ZG` | World Bank | annual % | 2001–2025 | 108 | 52 | 52 | 48 | 8.0 |
| `FS.AST.PRVT.GD.ZS` | World Bank | % of GDP | 2001–2025 | 180 | 54 | 52 | 39 | 13.3 |
| `IT.CEL.SETS.P2` | World Bank | per 100 people | 2000–2024 | 43 | 54 | 54 | 39 | 3.2 |
| `NE.EXP.GNFS.CD` | World Bank | USD | 2001–2025 | 191 | 51 | 49 | 48 | 14.1 |
| `NE.IMP.GNFS.CD` | World Bank | USD | 2001–2025 | 191 | 51 | 49 | 48 | 14.1 |
| `NY.GDP.MKTP.CD` | World Bank | USD | 2001–2025 | 31 | 54 | 53 | 52 | 2.3 |
| `NY.GDP.MKTP.KD.ZG` | World Bank | annual % | 2001–2025 | 45 | 54 | 53 | 52 | 3.3 |
| `NY.GDP.PCAP.CD` | World Bank | USD | 2001–2025 | 31 | 54 | 53 | 52 | 2.3 |
| `NY.GNS.ICTR.ZS` | World Bank | % of GDP | 2000–2025 | 382 | 47 | 45 | 39 | 30.8 |
| `SL.UEM.TOTL.ZS` | World Bank | % of labour force | 2001–2025 | 30 | 53 | 53 | 51 | 2.2 |
| `SP.POP.TOTL` | World Bank | persons | 2001–2025 | 0 | 54 | 54 | 54 | 0.0 |

### IMF forecast years

Excluded from the matrix and from every figure above. The copilot may show
them only labelled as IMF forecasts.

| Code | Forecast years | Forecast rows | Countries |
| --- | --- | --- | --- |
| `BCA_NGDPD` | 2027–2031 | 260 | 52 |
| `GGXCNL_NGDP` | 2027–2031 | 260 | 52 |
| `GGXWDG_NGDP` | 2027–2031 | 255 | 51 |
| `LP` | 2027–2031 | 265 | 53 |
| `LUR` | 2027–2031 | 30 | 6 |
| `NGDPD` | 2027–2031 | 260 | 52 |
| `NGDPDPC` | 2027–2031 | 260 | 52 |
| `NGDP_RPCH` | 2027–2031 | 260 | 52 |
| `PCPIEPCH` | 2027–2031 | 260 | 52 |
| `PCPIPCH` | 2027–2031 | 260 | 52 |

### Exchange rates

`fact_fx_rates` is an irregular snapshot, not a daily series. The export has
14 capture dates between 2026-09-19 and 2026-10-29 (09-19, 09-21, 09-23,
09-24, 10-02, 10-03, 10-16, 10-17, 10-18, 10-20, 10-21, 10-23, 10-27 and
10-29), with gaps of up to 13 days (10-03 to 10-16). The latest capture is
13 days before the profiling date. 52 countries are captured on each date
up to 10-03 and 53 from 10-16, when Burkina Faso starts. Botswana has no FX
rows. No `fx_rate_usd` is NULL. `fx_rate_usd` is units of local currency per
1 USD.

The copilot offers FX only as **the latest available rate, with its date**.
FX trends, moving averages, changes over a period and volatility are not
supported: they need a regular daily series, which the capture does not
provide.

| Country | Currency | Capture dates | First | Last | Largest gap (days) | Latest `fx_rate_usd` | Stale |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AGO | AOA | 14 | 2026-09-19 | 2026-10-29 | 13 | 926.186 | no |
| BDI | BIF | 14 | 2026-09-19 | 2026-10-29 | 13 | 3002.3529 | no |
| BEN | XOF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| BFA | XOF | 8 | 2026-10-16 | 2026-10-29 | 4 | 588.5278 | no |
| BWA | BWP |  |  |  |  |  |  |
| CAF | XAF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| CIV | XOF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| CMR | XAF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| COD | CDF | 14 | 2026-09-19 | 2026-10-29 | 13 | 2313.5322 | no |
| COG | XAF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| COM | KMF | 14 | 2026-09-19 | 2026-10-29 | 13 | 441.3959 | no |
| CPV | CVE | 14 | 2026-09-19 | 2026-10-29 | 13 | 98.9303 | no |
| DJI | DJF | 14 | 2026-09-19 | 2026-10-29 | 13 | 177.721 | no |
| DZA | DZD | 14 | 2026-09-19 | 2026-10-29 | 13 | 135.2523 | no |
| EGY | EGP | 14 | 2026-09-19 | 2026-10-29 | 13 | 56.119 | no |
| ERI | ERN | 14 | 2026-09-19 | 2026-10-29 | 13 | 15 | no |
| ETH | ETB | 14 | 2026-09-19 | 2026-10-29 | 13 | 161.7855 | no |
| GAB | XAF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| GHA | GHS | 14 | 2026-09-19 | 2026-10-29 | 13 | 11.6399 | no |
| GIN | GNF | 14 | 2026-09-19 | 2026-10-29 | 13 | 8836.5235 | no |
| GMB | GMD | 14 | 2026-09-19 | 2026-10-29 | 13 | 74.719 | no |
| GNB | XOF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| GNQ | XAF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| KEN | KES | 14 | 2026-09-19 | 2026-10-29 | 13 | 129.8324 | no |
| LBR | LRD | 14 | 2026-09-19 | 2026-10-29 | 13 | 170.044 | no |
| LBY | LYD | 14 | 2026-09-19 | 2026-10-29 | 13 | 6.4251 | no |
| LSO | LSL | 14 | 2026-09-19 | 2026-10-29 | 13 | 16.6339 | no |
| MAR | MAD | 14 | 2026-09-19 | 2026-10-29 | 13 | 9.8469 | no |
| MDG | MGA | 14 | 2026-09-19 | 2026-10-29 | 13 | 4569.7674 | no |
| MLI | XOF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| MOZ | MZN | 14 | 2026-09-19 | 2026-10-29 | 13 | 63.8274 | no |
| MRT | MRU | 14 | 2026-09-19 | 2026-10-29 | 13 | 40.1332 | no |
| MUS | MUR | 14 | 2026-09-19 | 2026-10-29 | 13 | 47.5308 | no |
| MWI | MWK | 14 | 2026-09-19 | 2026-10-29 | 13 | 1739.1327 | no |
| NAM | NAD | 14 | 2026-09-19 | 2026-10-29 | 13 | 16.6339 | no |
| NER | XOF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| NGA | NGN | 14 | 2026-09-19 | 2026-10-29 | 13 | 1346.2368 | no |
| RWA | RWF | 14 | 2026-09-19 | 2026-10-29 | 13 | 1478.0549 | no |
| SDN | SDG | 14 | 2026-09-19 | 2026-10-29 | 13 | 543.7237 | no |
| SEN | XOF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| SLE | SLE | 14 | 2026-09-19 | 2026-10-29 | 13 | 22.8696 | no |
| SOM | SOS | 14 | 2026-09-19 | 2026-10-29 | 13 | 571.2347 | no |
| SSD | SSP | 14 | 2026-09-19 | 2026-10-29 | 13 | 5744.1509 | no |
| STP | STN | 14 | 2026-09-19 | 2026-10-29 | 13 | 21.9815 | no |
| SWZ | SZL | 14 | 2026-09-19 | 2026-10-29 | 13 | 16.6339 | no |
| SYC | SCR | 14 | 2026-09-19 | 2026-10-29 | 13 | 14.412 | no |
| TCD | XAF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| TGO | XOF | 14 | 2026-09-19 | 2026-10-29 | 13 | 588.5278 | no |
| TUN | TND | 14 | 2026-09-19 | 2026-10-29 | 13 | 3.0131 | no |
| TZA | TZS | 14 | 2026-09-19 | 2026-10-29 | 13 | 2636.7735 | no |
| UGA | UGX | 14 | 2026-09-19 | 2026-10-29 | 13 | 4243.5858 | no |
| ZAF | ZAR | 14 | 2026-09-19 | 2026-10-29 | 13 | 16.6339 | no |
| ZMB | ZMW | 14 | 2026-09-19 | 2026-10-29 | 13 | 20.1736 | no |
| ZWE | ZWG | 14 | 2026-09-19 | 2026-10-29 | 13 | 26.5641 | no |

### Known gaps

Every country-indicator pair that has no actual value at all, or is stale
(last actual value before 2024). Years in brackets are the last actual year.

Entirely missing:

| Code | Countries |
| --- | --- |
| `BN.CAB.XOKA.GD.ZS` | CAF, ERI, GNQ, SOM, TCD |
| `DT.DOD.DECT.CD` | GNQ, LBY, NAM, SSD, SYC |
| `FP.CPI.TOTL.ZG` | ERI, SOM |
| `GGXWDG_NGDP` | SOM |
| `LUR` | 43 of 54 countries: all except CPV, DZA, EGY, MAR, MUS, NGA, SDN, STP, SYC, TUN and ZAF |
| `NE.EXP.GNFS.CD` | BDI, LBR, NGA |
| `NE.IMP.GNFS.CD` | BDI, LBR, NGA |
| `NY.GNS.ICTR.ZS` | CAF, ERI, GNQ, LBR, NGA, SOM, TCD |
| `SL.UEM.TOTL.ZS` | SYC |
| FX (`fact_fx_rates`) | BWA |

Stale:

| Code | Countries |
| --- | --- |
| `BCA_NGDPD`, `GGXCNL_NGDP`, `GGXWDG_NGDP`, `LP`, `NGDPD`, `NGDPDPC`, `NGDP_RPCH`, `PCPIEPCH`, `PCPIPCH` | ERI (2019) |
| `BN.CAB.XOKA.GD.ZS` | BEN (2023), COG (2021), COM (2023), GAB (2015), LBY (2023), SEN (2023), SSD (2023), TGO (2020) |
| `FP.CPI.TOTL.ZG` | COD (2016), SDN (2022), SWZ (2019), ZWE (2022) |
| `FS.AST.PRVT.GD.ZS` | CAF (2022), CMR (2019), COD (2023), COG (2023), ERI (2014), ETH (2008), GAB (2019), GNQ (2023), MRT (2019), NGA (2023), SDN (2022), STP (2023), SYC (2016), TCD (2021), ZWE (2023) |
| `IT.CEL.SETS.P2` | BDI (2023), CAF (2022), COM (2023), DJI (2023), ERI (2022), GIN (2023), GNQ (2022), LBR (2022), LBY (2022), MDG (2023), MLI (2022), SDN (2022), SLE (2022), SOM (2023), SSD (2023) |
| `LUR` | DZA (2019), NGA (2018), STP (2017) |
| `NE.EXP.GNFS.CD`, `NE.IMP.GNFS.CD` | ERI (2011), SSD (2015), TGO (2023) |
| `NY.GDP.MKTP.CD`, `NY.GDP.MKTP.KD.ZG`, `NY.GDP.PCAP.CD` | ERI (2011), SSD (2015) |
| `NY.GNS.ICTR.ZS` | BEN (2023), COG (2021), COM (2023), GAB (2015), LBY (2023), SEN (2023), SSD (2015), TGO (2020) |
| `SL.UEM.TOTL.ZS` | SDN (2022), SSD (2023) |

No FX series is stale: every captured country's latest rate is from
2026-10-29, 13 days before the profiling date.

### Inconsistencies

1. **IMF inflation codes are labelled the wrong way round in
   `dim_indicator`.** The IMF DataMapper indicator list
   (`https://www.imf.org/external/datamapper/api/v1/indicators`, checked
   2026-11-11) defines `PCPIPCH` as "Inflation rate, average consumer
   prices" and `PCPIEPCH` as "Inflation rate, end of period consumer
   prices", both in annual percent change. `dim_indicator` names `PCPIPCH`
   "end of period" and `PCPIEPCH` "average". The copilot uses the IMF
   meaning: **`PCPIPCH` is annual-average inflation and `PCPIEPCH` is
   end-of-period inflation.**
2. **`NY.GNS.ICTR.ZS` is mislabelled in `dim_indicator`.** The World Bank
   defines it as "Gross savings (% of GDP)": gross national income less
   total consumption, plus net transfers, as a percent of GDP. The
   denominator is GDP; the GNI-based ratio is a different code,
   `NY.GNS.ICTR.GN.ZS`. `dim_indicator` names it "Gross national
   expenditure (% of GDP)", which is a different World Bank series
   (`NE.DAB.TOTL.ZS`). The copilot uses the World Bank meaning, **gross
   savings as a percent of GDP**.
3. **Units differ between overlapping series.** `NGDPD` is in billions of
   USD and `NY.GDP.MKTP.CD` in USD; `LP` is in millions of persons and
   `SP.POP.TOTL` in persons. The copilot does not convert between them (#17
   refuses incompatible comparisons).
4. **Same concept, different definitions or coverage.**
   - GDP, GDP growth and GDP per capita: IMF WEO values for recent years
     include IMF staff estimates and are revised each WEO round; World Bank
     WDI values come from national accounts and can differ in base year and
     revision timing.
   - Inflation: `FP.CPI.TOTL.ZG` is the annual-average CPI change, like
     `PCPIPCH`, but has more gaps (COD, SDN, SWZ and ZWE stale; ERI and SOM
     missing).
   - Current account: both are percent of GDP, but the World Bank series
     covers 49 countries against the IMF's 54.
   - Unemployment: `LUR` is the national definition reported to the IMF,
     for 11 countries; `SL.UEM.TOTL.ZS` is the ILO modelled estimate, for 53.
   - Population: IMF estimates in millions against World Bank totals in
     persons, with different revision timing.
5. **Current-year IMF values are not flagged as forecasts.** See
   [How `is_forecast` is set](#how-is_forecast-is-set).
6. **FX coverage is 52 to 53 countries, not 54.** Botswana has no rows, and
   Burkina Faso starts on 2026-10-16.

Correcting the names in `dim_indicator` belongs to the ingestion
repository; this contract records the meaning the copilot uses.

### Source preference

Where both sources hold a concept, the copilot uses one code by default and
never mixes the other source's code into the same series. A comparison
between sources is shown as two labelled series.

| Concept | Default code | Other code | Reason |
| --- | --- | --- | --- |
| GDP, current prices | `NGDPD` (IMF, billions of USD) | `NY.GDP.MKTP.CD` | 54 countries over 1980–2026 against 2001–2025; 53 countries current to 2024+ against 52 |
| Real GDP growth | `NGDP_RPCH` (IMF) | `NY.GDP.MKTP.KD.ZG` | 54 countries with 10+ years over a 47-year window, against 53 over 25 years |
| GDP per capita | `NGDPDPC` (IMF) | `NY.GDP.PCAP.CD` | 53 countries current to 2024+ against 52, over a 47-year window |
| Inflation | `PCPIPCH` (IMF, annual average) | `FP.CPI.TOTL.ZG` | 54 countries against 52, 53 current against 48, 6.6% missing against 8.0% |
| Current account balance | `BCA_NGDPD` (IMF) | `BN.CAB.XOKA.GD.ZS` | 54 countries against 49, 53 current against 41, 7.2% missing against 20.9% |
| Unemployment rate | `SL.UEM.TOTL.ZS` (World Bank) | `LUR` | 53 countries against 11, 2.2% missing against 83.9% |
| Population | `LP` (IMF, millions) | `SP.POP.TOTL` | 54 countries over 1980–2026 against 2001–2025, and the same source as the IMF GDP defaults |

### Supported indicators

**Rule:** an indicator is offered when at least 40 of the 54 countries have
10 or more actual years with a value, and at least 40 countries have a last
actual year of 2024 or later. Where both sources hold a concept, only the
default code from [Source preference](#source-preference) is offered.

| Code | Display name | Unit | Frequency | Source |
| --- | --- | --- | --- | --- |
| `NGDPD` | GDP, current prices | billions of USD | annual | IMF WEO |
| `NGDP_RPCH` | Real GDP growth | annual % change | annual | IMF WEO |
| `NGDPDPC` | GDP per capita, current prices | USD | annual | IMF WEO |
| `PCPIPCH` | Inflation, average consumer prices | annual % change | annual | IMF WEO |
| `PCPIEPCH` | Inflation, end of period consumer prices | annual % change | annual | IMF WEO |
| `BCA_NGDPD` | Current account balance | % of GDP | annual | IMF WEO |
| `GGXWDG_NGDP` | General government gross debt | % of GDP | annual | IMF WEO |
| `GGXCNL_NGDP` | General government net lending/borrowing | % of GDP | annual | IMF WEO |
| `LP` | Population | millions of persons | annual | IMF WEO |
| `SL.UEM.TOTL.ZS` | Unemployment, total | % of labour force | annual | World Bank WDI |
| `NE.EXP.GNFS.CD` | Exports of goods and services | USD | annual | World Bank WDI |
| `NE.IMP.GNFS.CD` | Imports of goods and services | USD | annual | World Bank WDI |
| `DT.DOD.DECT.CD` | External debt stocks, total | USD | annual | World Bank WDI |
| `BX.KLT.DINV.CD.WD` | Foreign direct investment, net inflows | USD | annual | World Bank WDI |
| `fx_rate_usd` in `fact_fx_rates` | Exchange rate, latest available | local currency per USD | irregular snapshot; latest rate and date only | ExchangeRate-API |

Indicators in `dim_indicator` that are not offered:

| Code | Why |
| --- | --- |
| `NY.GDP.MKTP.CD` | `NGDPD` is preferred |
| `NY.GDP.MKTP.KD.ZG` | `NGDP_RPCH` is preferred |
| `NY.GDP.PCAP.CD` | `NGDPDPC` is preferred |
| `FP.CPI.TOTL.ZG` | `PCPIPCH` is preferred |
| `BN.CAB.XOKA.GD.ZS` | `BCA_NGDPD` is preferred |
| `SP.POP.TOTL` | `LP` is preferred |
| `LUR` | Rule not met (10 countries with 10+ years, 8 current); `SL.UEM.TOTL.ZS` is preferred |
| `FS.AST.PRVT.GD.ZS` | Rule not met: 39 countries current to 2024+ |
| `IT.CEL.SETS.P2` | Rule not met: 39 countries current to 2024+ |
| `NY.GNS.ICTR.ZS` | Rule not met: 39 countries current to 2024+ |

Indicator areas from [Indicator areas](#indicator-areas) that are not fully
supported:

- **Exchange rates:** supported in part, as the latest available rate with
  its date. Trends, changes and volatility are not supported because the FX
  capture is an irregular snapshot of 14 dates (see
  [Exchange rates](#exchange-rates)).
- **Interest rates:** not supported. No curated model holds an
  interest-rate series.
- GDP, inflation and trade are supported through the codes above.

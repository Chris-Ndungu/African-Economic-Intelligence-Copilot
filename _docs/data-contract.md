# Data contract

The curated BigQuery models the copilot reads, their fields, types and units, and the measured coverage of countries, indicators and periods.

Filled in by #5 and #6.

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

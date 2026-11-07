# API

Where the OpenAPI contract lives, how frontend types are generated from it, and the error and data-mode conventions.

## Where the contract lives

The contract is [`api/openapi.yaml`](../api/openapi.yaml), written in
OpenAPI 3.1. It is the hand-off between the frontend, the backend and the
tests: each side builds against it rather than against the other's code.

It defines:

- `GET /health`, the liveness check built in #8
- Reference data: `GET /api/countries`, `GET /api/indicators` and
  `GET /api/coverage`
- Investigations: `POST /api/investigations/run` to run one,
  `POST /api/investigations` to save one, `GET /api/investigations` to list
  them, `GET` and `PATCH /api/investigations/{investigation_id}` to fetch and
  update one, and `GET /api/investigations/{investigation_id}/report` to
  export one as a PDF
- Result schemas: `Finding`, `Series`, `ComparisonResult`, `BaselineResult`
  and `AnomalyResult`. Each number carries its value, unit, period,
  geography, method, source and caveats (`NumericResult`). The Pydantic
  models in `copilot_core/models.py` implement them; `SourceRef` and
  `SeriesResult` there are `Source` and `Series` here

Lint it from the repository root:

```sh
npx @redocly/cli lint api/openapi.yaml
```

The lint must report no errors. It reports four warnings that are expected:
the server URL is `localhost`, and `/health`, `/api/countries` and
`/api/indicators` take no input, so they have no 4xx response.

The data-related schemas (countries, indicators, coverage, units and result
fields) are based on [`plan.md`](plan.md), because
[`data-contract.md`](data-contract.md) has not been written yet (#5, #6).
When it is, the schemas are revised to match it, through a contract change.
Example values in the contract are illustrative, not real statistics.

## The contract changes first

The OpenAPI contract changes before API behavior does. To add or change an
endpoint, edit `api/openapi.yaml`, lint it, regenerate the frontend types,
and only then change the FastAPI route or the frontend code. The
`add-api-endpoint` skill in `.claude/skills/` walks through the steps.

## Regenerating frontend types

Frontend types are generated with `openapi-typescript`, never hand-written.
From `frontend/`:

- `npm run gen-types` writes `frontend/src/api/schema.d.ts` from
  `api/openapi.yaml`. Commit the regenerated file with the contract change
- `npm run check-types` exits non-zero when the committed file differs from
  a fresh generation, and zero when it matches

`frontend/src/api/.gitattributes` keeps `schema.d.ts` at LF line endings so
the check also passes on a Windows checkout.

## Conventions

### `data_mode`

Every response that returns data has a top-level `data_mode` field:

- `demo` - the bundled sample snapshot, which the UI must label as sample
  data
- `live` - curated BigQuery data for authorized users

A saved investigation also records the mode it was run in. The list of
saved investigations has a top-level `data_mode` for the mode the server is
running in, and a `data_mode` on each item. The PDF export returns the mode
in the `X-Data-Mode` header and prints it in the report. `GET /health`
returns no data and has no `data_mode`.

### Missing values

A missing value is `null`, never `0`. Every field that can be missing is
nullable and its description says so; a series point with no observation
has `"value": null`.

### Errors

Every 4xx and 5xx response uses the shared `Error` schema:

```json
{
  "code": "service_unavailable",
  "message": "Gemini is unavailable, so the results could not be interpreted.",
  "service": "gemini",
  "details": []
}
```

- `code` is machine-readable: `validation_error` (`422`), `not_found`
  (`404`), `service_unavailable` (`503`) or `internal_error` (`500`)
- `message` is for people
- `service` names the service that failed, `gemini`, `data_service` or
  `database`, and is `null` when no service failed. It is set on every
  `503`
- `details` lists per-field problems for `validation_error` and is empty
  otherwise

Each operation lists the error statuses it can return. Running an
investigation returns `503` when Gemini or the data service is unavailable,
rather than an uninterpreted or fabricated answer. FastAPI's default `422`
body differs from this schema, so the backend must install exception
handlers that return `Error`.

### Pagination

`GET /api/investigations` is cursor-paginated, most recently updated first.
`limit` defaults to 20 and is at most 100. Pass the response's
`next_cursor` as `cursor` to get the next page; it is `null` on the last
page.

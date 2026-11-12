# API

Where the OpenAPI contract for the JSON API lives, how it is validated, which routes are outside it, and the error and data-mode conventions.

## Where the contract lives

The contract is [`api/openapi.yaml`](../api/openapi.yaml), written in
OpenAPI 3.1. It describes the JSON API at `/api/...` and `/health`, and is
the hand-off between the API and its clients and tests: each side builds
against it rather than against the other's code.

It defines:

- `GET /health`, the liveness check built in #8
- `GET /api/meta`, the data mode, the demo snapshot date and whether Gemini is
  configured (#31)
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

The contract is validated by `uv run pytest`: a test in
`tests/test_web.py` checks `api/openapi.yaml` against the OpenAPI
specification with `openapi-spec-validator`, so no Node tool is needed.
Another test checks that every path FastAPI generates is `/health` or
starts with `/api/`.

The data-related schemas (countries, indicators, coverage, units and result
fields) are based on [`plan.md`](plan.md), because
[`data-contract.md`](data-contract.md) has not been written yet (#5, #6).
When it is, the schemas are revised to match it, through a contract change.
Example values in the contract are illustrative, not real statistics.

## The contract changes first

The OpenAPI contract changes before API behavior does. To add or change an
endpoint, edit `api/openapi.yaml`, check it validates with `uv run pytest`,
and only then change the FastAPI route. The `add-api-endpoint` skill in
`.claude/skills/` walks through the steps.

## HTML routes

The server-rendered pages (`GET /`, and `GET /investigations/{id}` from
#23), the HTMX partials under `/partials/...` and the static files under
`/static/...` are outside the contract. They return HTML for the app's own
pages, not data for other clients, and they render the same `copilot_core`
result models the JSON API returns, so they have no separate schema to keep
in sync. They are kept out of the contract by registering their router in
`backend/web.py` with `include_in_schema=False`, and the static files are a
mount, which FastAPI never adds to the schema. A test fails if any path
other than `/health` or `/api/...` appears in the generated schema.

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
  (`404`), `step_limit_reached` (`422`), `service_unavailable` (`503`) or
  `internal_error` (`500`)
- `message` is for people
- `service` names the service that failed, `gemini`, `data_service` or
  `database`, and is `null` when no service failed. It is set on every
  `503` except a run over its time limit, which no single service caused
- `details` lists per-field problems for `validation_error` and is empty
  otherwise

Each operation lists the error statuses it can return. Running an
investigation returns `503` when Gemini or the data service is unavailable,
rather than an uninterpreted or fabricated answer. FastAPI's default `422`
body differs from this schema, so the backend must install exception
handlers that return `Error`.

### Running an investigation

A run starts from a question, a selection (countries, one indicator, start
and end) or both; with both, the selection limits what the analysis tools may
query. A selection alone runs the question "Describe the trend in
`<indicator>` for `<countries>` from `<start>` to `<end>`". A request with
neither, or a question over 1,000 characters, is rejected with `422`.

Gemini calls the approved analysis tools, then writes a structured
interpretation whose every number is checked against the tool results (see
`Interpretation`). The investigation is saved with its tool calls, prompt
version, validation counts and token usage in `run`. A failed run is saved as
`failed` with `error` set and no result, so nothing is presented as a
success:

| Outcome | Saved as | Response |
| --- | --- | --- |
| Interpreted (unverified numbers are flagged, not fatal) | `succeeded` | `200` |
| Unsupported question | `succeeded`, `interpretation.unsupported_reason` set, no findings | `200` |
| Gemini not configured, unavailable, blocked, truncated or timed out, or its reply unreadable | `failed`, `gemini_...` or `interpretation_invalid` | `503`, `service: gemini` |
| Data service unavailable | `failed`, `data_unavailable` | `503`, `service: data_service` |
| Step limit reached | `failed`, `step_limit_reached` | `422`, `code: step_limit_reached` |
| Over the time limit (90 seconds by default) | `failed`, `timeout` | `503`, `service: null` |

When the API starts, runs left `running` longer than the time limit are
marked `failed` with code `interrupted`, and runs left `pending` longer than
the pending timeout with code `not_started`.

### Streaming a run

`POST /api/investigations/run` runs the investigation inside the request and
returns it saved. To show progress, a client uses two steps instead:

1. `POST /api/investigations/runs` with the same body saves the
   investigation as `pending` and returns `202` with its `id` and
   `events_url`. It does not start the run.
2. `GET /api/investigations/{investigation_id}/events` opens a
   server-sent event stream. It is a `GET` with no body, so a browser reads
   it with `EventSource` or the HTMX SSE extension, and the question never
   appears in a URL or an access log.

Opening the stream for a `pending` investigation claims it (`pending` to
`running` in one database update, so two connections can never run it twice)
and runs it inside the stream response. Nothing keeps running after the
response ends: Cloud Run throttles the CPU once a response is sent, so there
is no background work. If the client disconnects, the run is cancelled and
saved as `failed` with code `client_disconnected`.

Each event has an increasing `id`, an `event:` name and a JSON `data:`
payload whose schema is in the contract: `started`, then `fetching_data`,
`analysis_started` and `analysis_finished` for each tool call,
`interpreting`, `validating`, and exactly one final `saved` or `failed`,
after which the stream closes. A `: ping` comment is sent at least every 15
seconds while a step runs, and responses set `Cache-Control: no-cache` and
`X-Accel-Buffering: no` so proxies pass events through at once.

Opening the stream again for a finished investigation sends only its final
`saved` or `failed` event, which is what a reconnecting `EventSource` gets.
For an investigation another connection is running, it sends one
`in_progress` event and closes. A `pending` investigation not opened within
5 minutes fails with code `not_started`.

### Pagination

`GET /api/investigations` is cursor-paginated, newest (most recently created) first.
`limit` defaults to 20 and is at most 100. Pass the response's
`next_cursor` as `cursor` to get the next page; it is `null` on the last
page.

### Conformance

`tests/test_contract.py` compares the schema the FastAPI app generates with
`api/openapi.yaml`: every path and method, parameters, request bodies and
response schemas. It fails, naming the endpoint or field, when they
disagree. Its docstring lists the differences it ignores (descriptions,
ordering, schema names, FastAPI's default `422` when the contract has none).
Operations not implemented yet, `runInvestigation` (#28) and
`exportInvestigationPdf` (#32), are listed in the test and must be removed
from that list when they are added.

Phase 3 changed the contract before the code:

- Indicator codes are the source codes, for example `PCPIPCH` or
  `SL.UEM.TOTL.ZS`, and categories are the `dim_indicator` themes.
- `ComparisonResult`, `BaselineResult` and the new `AnomalyPoint` carry the
  statistics the analysis functions compute; `AnomalyResult` covers a whole
  series, with `scored_count` and `flagged_count`.
- `InvestigationResult.interpretation` is `null` until Gemini interprets the
  results (Phase 4).
- Saved investigations have a `status`.

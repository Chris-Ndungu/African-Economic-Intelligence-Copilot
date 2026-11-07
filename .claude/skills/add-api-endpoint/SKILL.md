---
name: add-api-endpoint
description: Use when adding or changing a FastAPI endpoint, which starts with the OpenAPI contract and ends with a TestClient integration test.
---

# Add an API endpoint

The OpenAPI contract is the hand-off between the API and its clients and
tests, so it changes before the code does. The reasons are in
[`_docs/plan.md` section 4.1](../../../_docs/plan.md#41-application-architecture-fastapi-jinja-and-htmx)
and the conventions in [`_docs/api.md`](../../../_docs/api.md).

## Steps

1. Read the GitHub issue and its acceptance criteria. Implement against them;
   do not change them.
2. Edit the OpenAPI contract first. It lives in `api/openapi.yaml`, created by
   #10. Add the path with an `operationId`, request and response schemas, at
   least one example response, and every error status it can return. If the
   contract does not exist yet, stop: the task is blocked by #10.
3. Validate the contract with `uv run pytest tests/test_web.py`, which checks
   `api/openapi.yaml` with `openapi-spec-validator` (#74).
4. Put the logic in `copilot_core`. If the endpoint needs a new analysis, use
   the `add-analysis-function` skill.
5. Add the route in `backend/`. The FastAPI app is `backend.main:app`, created
   by #8. The route validates input, calls `copilot_core`, and returns the
   result models from #11.
6. Write the tests listed under "Tests to add", then run `uv run pytest`.
7. Commit, and comment on the issue with what you did.

## Conventions

- The contract changes before API behavior does
  ([`_docs/AGENTS.md`](../../../_docs/AGENTS.md))
- JSON routes live under `/api/...` and are in the contract. HTML pages and
  partials are not: they are registered with `include_in_schema=False`
  ([`_docs/api.md`](../../../_docs/api.md))
- Routes stay thin: validate input, call `copilot_core`, return the result.
  No business logic in `backend/`
- Use the shared error schema from the contract for every 4xx and 5xx, with
  `503` when Gemini or the data service is unavailable (#10)
- Every response that returns data includes `data_mode` (`demo` or `live`)
  (#10)
- A missing value is `null`, never `0`
- Follow the guardrails in
  [`_docs/plan.md` section 8](../../../_docs/plan.md#8-technical-principles-and-implementation-guardrails)
- Tests never call the real Gemini API or BigQuery
  ([`_docs/plan.md` section 4.10](../../../_docs/plan.md#410-testing))

## Tests to add

Put the tests in `tests/`, for example `tests/test_api_<name>.py`, using
FastAPI `TestClient` (set up by #8, see `tests/test_health.py`).

- An integration test for the success case: status code, body shape and
  `data_mode`
- At least one integration test for an error case, for example invalid input
  (`422` or `400`) or an unavailable service (`503`), checking the body
  matches the shared error schema
- Unit tests in `copilot_core` for any new logic the route calls

## Done when

- [ ] `api/openapi.yaml` was edited before the route, and it validates
- [ ] The route is thin and the logic is in `copilot_core`
- [ ] A `TestClient` integration test covers the success case and at least one
      error case
- [ ] `uv run pytest` passes

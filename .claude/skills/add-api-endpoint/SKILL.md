---
name: add-api-endpoint
description: Use when adding or changing a FastAPI endpoint, which starts with the OpenAPI contract and ends with a TestClient integration test.
---

# Add an API endpoint

The OpenAPI contract is the hand-off between backend and frontend, so it
changes before the code does. The reasons are in
[`_docs/plan.md` section 4.1](../../../_docs/plan.md#41-application-architecture-fastapi--react-contract-first)
and the conventions in [`_docs/api.md`](../../../_docs/api.md).

## Steps

1. Read the GitHub issue and its acceptance criteria. Implement against them;
   do not change them.
2. Edit the OpenAPI contract first. It lives in `api/openapi.yaml`, created by
   #10. Add the path with an `operationId`, request and response schemas, at
   least one example response, and every error status it can return. If the
   contract does not exist yet, stop: the task is blocked by #10.
3. Lint the contract with `npx @redocly/cli lint api/openapi.yaml` (#10).
4. Regenerate the frontend types from `frontend/` with `npm run gen-types`,
   and commit the regenerated `frontend/src/api/schema.d.ts`.
   `npm run check-types` must pass. Both scripts are created by #10.
5. Put the logic in `copilot_core`. If the endpoint needs a new analysis, use
   the `add-analysis-function` skill.
6. Add the route in `backend/`. The FastAPI app is `backend.main:app`, created
   by #8. The route validates input, calls `copilot_core`, and returns the
   result models from #11.
7. Write the tests listed under "Tests to add", then run `uv run pytest`.
8. Commit, and comment on the issue with what you did.

## Conventions

- The contract changes before API behavior does
  ([`_docs/AGENTS.md`](../../../_docs/AGENTS.md))
- Frontend types are generated from the contract with `openapi-typescript`,
  never hand-written
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

- [ ] `api/openapi.yaml` was edited before the route, and the lint passes
- [ ] The frontend types were regenerated and `npm run check-types` passes
- [ ] The route is thin and the logic is in `copilot_core`
- [ ] A `TestClient` integration test covers the success case and at least one
      error case
- [ ] `uv run pytest` passes

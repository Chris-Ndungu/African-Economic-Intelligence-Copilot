---
name: add-playwright-journey
description: Use when adding an end-to-end Playwright test for a user journey that runs against demo data and the stubbed Gemini client.
---

# Add a Playwright journey

End-to-end tests drive a real browser through the local stack. They run on
demo data with a stubbed Gemini client, so they are repeatable and never
cost money or touch real data. The reasons are in
[`_docs/plan.md` section 4.10](../../../_docs/plan.md#410-testing).

## Steps

1. Read the GitHub issue and its acceptance criteria. Write the journey from
   the criteria, not from the implementation.
2. Check that the Playwright setup exists. It is created by #34: tests in
   `tests/e2e/` marked `e2e`, a session fixture that starts the stack or uses
   `E2E_BASE_URL`, and `docker-compose.e2e.yml`. If it does not exist yet,
   stop: the task is blocked by #34.
3. Install the browser once with `uv run playwright install chromium` (#34).
4. Add the test in `tests/e2e/`, for example `tests/e2e/test_<journey>.py`,
   marked `e2e`, using the fixtures from #34.
5. Make sure the stack runs with `LLM_CLIENT=stub` and demo data, and pick the
   recorded stub scenario the journey needs (#34).
6. Run it with `uv run pytest -m e2e`, then run the whole suite with
   `uv run pytest`.
7. Commit, and comment on the issue with what you did.

## Conventions

- The journey runs against demo data with the stubbed Gemini client
- It never calls the real Gemini API or BigQuery
- It runs under `uv run pytest`, through pytest-playwright, not a separate
  runner
- Selectors use roles, labels or text, not CSS classes
- Waits use Playwright's auto-waiting; no fixed sleeps
- Check the demo banner wherever results are shown, so demo data stays
  identifiable
  ([`_docs/plan.md` section 8](../../../_docs/plan.md#8-technical-principles-and-implementation-guardrails))
- Without Docker and without `E2E_BASE_URL`, e2e tests are skipped with a
  message, never counted as passed (#34)

## Tests to add

- One test per journey in `tests/e2e/`, marked `e2e`, following the steps a
  user takes and asserting what they see
- An assertion for each error or empty state the acceptance criteria mention
- Run the journey 10 times in a row locally to check it is not flaky

## Done when

- [ ] The journey is in `tests/e2e/` and marked `e2e`
- [ ] It runs against demo data with the stubbed Gemini client
- [ ] It never calls the real Gemini API or BigQuery
- [ ] It passes 10 runs in a row locally
- [ ] `uv run pytest` passes

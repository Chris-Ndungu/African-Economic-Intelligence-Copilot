# Backlog

Tasks are ordered by dependency and delivery tier (see `_docs/plan.md`, section 3). Tasks 1–47 make up the core MVP (Tier 1), tasks 48–52 add live data and deeper analysis (Tier 2), and tasks 53–54 are final validation and documentation.

## 1. Set up an empty project with a passing test
Goal: Complete the repository skeleton so that `uv run pytest` runs and passes.
Description: Starting from the existing uv project (Python 3.13, `pyproject.toml`, `main.py`), add pytest as a dev dependency, an empty `copilot_core` package, a `backend/` folder, and a single trivial test in `tests/`. Add a `.gitignore` and fill in the README with how to install (`uv sync`) and run the tests (`uv run pytest`).

## 2. Expand AGENTS.md and the documentation skeleton
Goal: Give coding agents durable project context from a single entry point.
Description: `_docs/AGENTS.md` already lists the commands, the dependency rule, and `_docs/process.md`; add a short product summary, the repository layout, and the coding conventions. Create placeholder files in `_docs/` (`agent-team.md`, `architecture.md`, `data-contract.md`, `api.md`) and link each one from the Documents section of `_docs/AGENTS.md`.

## 3. Document the process and agent team, and set up the task tracker
Goal: Make the development workflow, agent roles, and backlog explicit and public.
Description: Extend `_docs/process.md` (which already says: one GitHub issue at a time, read the acceptance criteria before starting and before closing, commit regularly) with the branch → PR → review → merge steps, and write `_docs/agent-team.md` (PM, backend, frontend, QA, and ops agents, with responsibilities, inputs, and outputs; the OpenAPI contract as the backend/frontend hand-off; a human merges every PR). Create a public GitHub Project board, an issue template with an "Acceptance criteria" section, and a PR template that links back to the issue.

## 4. Add project skills and subagent definitions
Goal: Package repeatable development tasks as reusable agent capabilities.
Description: Create `SKILL.md` files for recurring tasks such as "add an analysis function", "add an API endpoint", and "add a Playwright journey", each describing steps, conventions, and the tests to add. Add subagent definitions for the roles in `_docs/agent-team.md` and reference both from `_docs/AGENTS.md`.

## 5. Inventory the existing data platform
Goal: List which curated BigQuery models exist and what fields they expose.
Description: Review the existing ingestion repository and its dbt project to identify the datasets, marts, and models relevant to GDP, inflation, exchange rates, interest rates, and trade. Record each model's name, grain, fields, types, units, and source metadata columns in the "Models" section of `_docs/data-contract.md`.

## 6. Profile data coverage and complete the data contract
Goal: Know exactly which countries, indicators, and periods the data supports.
Description: Query the curated models listed in `_docs/data-contract.md` to measure country coverage, time ranges, frequencies, missing values, and stale series per indicator. Add a coverage matrix, known gaps, and unit or definition inconsistencies to `_docs/data-contract.md`, and state which indicators the application will support.

## 7. Create the bundled demo dataset
Goal: Provide a credential-free dataset that mirrors the curated marts.
Description: Export a representative snapshot of the curated marts described in `_docs/data-contract.md` to Parquet files under `data/demo/`. Write `data/demo/README.md` documenting the source, snapshot date, coverage, and the fact that this is sample data, not live data.

## 8. Scaffold the FastAPI backend with a health endpoint
Goal: Have a running API service with a tested health check.
Description: Create a FastAPI application in `backend/` with a `GET /health` endpoint and settings loaded from environment variables via pydantic-settings. Add a test in `tests/` using FastAPI's TestClient, and add the command to run the API to the Commands section of `_docs/AGENTS.md`.

## 9. Scaffold the React frontend
Goal: Have a running React app with a passing component test.
Description: Create a Vite + React + TypeScript app in `frontend/` with Tailwind CSS and shadcn/ui configured, and a basic layout shell (header, sidebar, main panel). Add Vitest with one component test, ESLint, and `npm run dev` and `npm test` scripts, and list both in the Commands section of `_docs/AGENTS.md`.

## 10. Write the OpenAPI contract and generate frontend types
Goal: Define the API between frontend and backend before implementing it, and keep both sides in sync.
Description: Write `api/openapi.yaml` covering metadata (countries, indicators, coverage), running an investigation, saving, listing, and fetching investigations, and exporting a PDF, with schemas for findings, series, and anomaly results (value, unit, period, geography, method, source, caveats). Add `openapi-typescript` and an `npm run gen-types` script in `frontend/`, a check that fails if committed types differ from a fresh generation, and a short description of the contract in `_docs/api.md`.

## 11. Define the core Pydantic result models
Goal: Create one typed source of truth for analytical results.
Description: In `copilot_core`, define Pydantic models such as `Finding`, `SeriesResult`, `ComparisonResult`, `AnomalyResult`, and `SourceRef` that match the schemas in `api/openapi.yaml`. Every numerical result must carry value, unit, period, geography, method, parameters, and source; add unit tests for validation rules.

## 12. Set up PostgreSQL persistence with migrations
Goal: Store investigations durably with versioned schema changes.
Description: Add SQLAlchemy 2 and Alembic to the backend, with a connection configured via an environment variable. Create an `investigations` table holding the question, selections, parameters, findings JSON, chart configuration, sources, data mode, status, and timestamps, and write an integration test that runs migrations against a Postgres container.

## 13. Run the full system with Docker Compose
Goal: Start the frontend, API, and Postgres locally with one command.
Description: Write development Dockerfiles for `backend/` and `frontend/` and a `docker-compose.yml` with services for both plus Postgres. The API should apply Alembic migrations on startup, and `docker compose up` alone must produce a working stack; document this in the README.

## 14. Add the CI workflow for pull requests
Goal: Run lint, type checks, and tests automatically on every PR.
Description: Add ruff and mypy as dev dependencies and create a GitHub Actions workflow that runs `uv sync`, ruff, mypy, `uv run pytest` (with a Postgres service container), ESLint, tsc, Vitest, and the generated-types drift check. Make the workflow a required status check on the `main` branch.

## 15. Implement the data service and metadata endpoints
Goal: Give analytics and the frontend a storage-agnostic way to read economic data.
Description: Define a `DataService` interface in `copilot_core` (`get_series(countries, indicator, start, end)`, `list_countries()`, `list_indicators()`, `list_coverage()`) and implement it with DuckDB over the Parquet files in `data/demo/`, returning units, frequency, and source metadata and treating missing values as missing rather than zero. Expose `GET /countries`, `/indicators`, and `/coverage` as defined in `api/openapi.yaml`, with unit and integration tests.

## 16. Implement trend and growth analysis
Goal: Compute trends and growth rates deterministically for an indicator series.
Description: Add a function in `copilot_core` that, for a country, indicator, and period, computes level change, percentage change, period-over-period growth, and a linear trend, returning the Pydantic result models. Handle mixed frequencies and missing periods explicitly, and cover edge cases with pytest and hypothesis.

## 17. Implement country comparison and historical baseline analysis
Goal: Compare an indicator across countries and against its own history.
Description: Add a comparison function that aligns series for several countries, refuses comparisons across incompatible units or frequencies, and returns summary statistics, rankings, and per-country coverage. Add a baseline function that compares a value or period with a configurable historical window (mean, median, standard deviation, percentile rank), returning the window, method, and parameters; unit-test both.

## 18. Implement configurable anomaly detection
Goal: Flag unusual movements in a series with transparent methods.
Description: Add anomaly detection in `copilot_core` supporting at least rolling z-score and IQR methods, with configurable window and threshold. Each flagged point must include the statistic, threshold, baseline, and method, and tests must cover sparse data and short series.

## 19. Implement investigation persistence endpoints
Goal: Save, list, and reopen investigations through the API.
Description: Implement a repository class in `copilot_core` for creating, updating, listing, and fetching rows in the `investigations` Postgres table. Expose it via the investigation endpoints in `api/openapi.yaml` and add integration tests against a real Postgres database.

## 20. Build the selection panel in the frontend
Goal: Let analysts choose countries, indicators, and periods interactively.
Description: Build a panel with multi-select countries, an indicator select, and a date range, populated from the `/countries`, `/indicators`, and `/coverage` endpoints via TanStack Query. Disable unavailable combinations based on coverage data and add component tests.

## 21. Build the chart and table components
Goal: Render analytical results as interactive charts and data tables.
Description: Build reusable Plotly chart components (time series, multi-country comparison, anomaly markers) and a data table component that consume the generated API types for series and results. Show units, periods, and gaps in the data visibly, and add component tests with fixture data.

## 22. Build the findings and evidence view
Goal: Show each finding with its method, parameters, sources, and caveats.
Description: Build the investigation results page that lays out narrative finding cards next to the chart and table components, all driven by the same result objects. Each card shows its method, parameters, source references, caveats, and missing-data notes, and labels hypotheses separately from observed facts.

## 23. Build the investigation history sidebar
Goal: Let analysts revisit and continue previous investigations.
Description: Build a sidebar that lists saved investigations from the API with title, date, and status, and opens one in the results page when clicked. Give each investigation a URL (`/investigations/:id`) so it can be bookmarked and reloaded, with component tests.

## 24. Create the Gemini client wrapper
Goal: Call Gemini safely, with timeouts, errors, and a test stub.
Description: Wrap the `google-genai` SDK (or Pydantic AI) in `copilot_core` with configurable model, timeout, retries, and token limits, and map failures to clear typed errors. Provide a stub implementation with recorded responses so that tests and CI never call the real API.

## 25. Expose analysis functions as Gemini tools
Goal: Let Gemini investigate by calling only approved analysis functions.
Description: Register the trend, comparison, baseline, and anomaly functions in `copilot_core` as Gemini function-calling tools, with schemas derived from their Pydantic models. Implement a single tool-calling loop with a step limit that records every tool call and result, and test it with the stub client.

## 26. Write the interpretation prompt and grounding rules
Goal: Make Gemini interpret computed evidence without inventing facts.
Description: Write the system prompt instructing Gemini to use only tool outputs, label facts versus hypotheses, distinguish correlation from causation, and disclose gaps. Request structured output that references tool-result IDs for each claim, and add tests with stubbed responses.

## 27. Validate numerical claims against tool outputs
Goal: Reject or flag narrative numbers that did not come from executed analysis.
Description: Implement a validator that extracts numbers from Gemini's structured interpretation and checks each one against the referenced tool results within a tolerance. Unverified claims must be removed or clearly flagged, and the behavior must be covered by unit tests.

## 28. Implement the investigation service and endpoint
Goal: Run a complete investigation from a question or a selection and save it.
Description: Build an investigation service in `copilot_core` that accepts a natural-language question or explicit selections, runs the Gemini tool loop, validates claims, and saves the result with its data mode. Expose it as the run-investigation endpoint in `api/openapi.yaml`, returning a clear error state rather than a partial "success" when Gemini or data is unavailable, with integration tests using the stub client.

## 29. Stream investigation progress over server-sent events
Goal: Let clients follow an investigation step by step while it runs.
Description: Add a server-sent events endpoint that emits progress events (fetching data, running each analysis, interpreting, validating, saved, or failed) from the investigation service. Define the event schema in `api/openapi.yaml` and test the event sequence for both success and failure.

## 30. Add natural-language input and live progress to the frontend
Goal: Let analysts ask a question and watch the investigation run.
Description: Add a question input alongside the selection panel that starts an investigation and subscribes to the server-sent progress events. Show each step as it happens, open the results page when the investigation is saved, and show clear messages when the service reports an error.

## 31. Label demo mode and handle unavailable services
Goal: Make the data mode obvious and never fake success.
Description: Add a persistent banner, driven by an API metadata field, that shows when demo data is in use. Add explicit UI states for unavailable data, unsupported questions, and Gemini outages, with tests for each.

## 32. Render investigation reports as PDF
Goal: Produce a PDF from a stored investigation without re-running the AI.
Description: Create a Jinja2 HTML report template and render it to PDF with WeasyPrint, including the summary, findings, tables, methodology, parameters, sources, caveats, data mode, and generation timestamp. Expose it through the export endpoint in `api/openapi.yaml` and test that the numbers in the report match the stored investigation.

## 33. Add charts to PDF reports and an export button
Goal: Make exported reports visual and downloadable from the UI.
Description: Render the investigation's Plotly charts as static images with Kaleido and embed them in the PDF report template. Add an "Export PDF" action to the results page that downloads the file, with loading and error states and a component test.

## 34. Set up Playwright with the first end-to-end journey
Goal: Run real-browser tests against the full local stack.
Description: Set up Playwright for Python (pytest-playwright) in `tests/` to run against the Docker Compose stack configured with the stubbed Gemini client and demo data. Implement the "run an investigation from selections and see results" journey so that it runs with `uv run pytest` and in CI.

## 35. Complete the end-to-end test suite
Goal: Cover all key user journeys in a real browser.
Description: Using the existing Playwright setup, add journeys for running an investigation from a question, saving and reopening an investigation, exporting a PDF, seeing the demo-mode banner, and seeing the error state when the AI is unavailable. Keep tests independent of each other and stable in CI.

## 36. Build the production container image
Goal: Ship the frontend and API as a single deployable image.
Description: Write a multi-stage Dockerfile that builds the React app to static files and serves them from FastAPI alongside the API. Keep the image small, run it as a non-root user, and verify it starts locally against the Compose Postgres.

## 37. Set up Google Cloud foundations
Goal: Prepare a secure Google Cloud project for automated deployments.
Description: Create or configure the Google Cloud project, an Artifact Registry repository, Secret Manager entries for the Gemini API key and database URLs, and a deployer service account. Configure Workload Identity Federation so GitHub Actions can authenticate without JSON keys, and document every step in `_docs/deployment.md`.

## 38. Deploy the dev environment manually
Goal: Have the application running at a public dev URL.
Description: Create a Neon Postgres database for dev and a Cloud Run dev service that uses the production image, the Secret Manager secrets, and a least-privilege runtime service account. Deploy once by hand, run migrations, confirm `/health` and demo mode work at the public URL, and add the steps to `_docs/deployment.md`.

## 39. Deploy to dev automatically on merge
Goal: Every merge to `main` produces a running dev deployment.
Description: Add a GitHub Actions workflow that builds and pushes the production image to Artifact Registry, runs migrations, and deploys to the dev Cloud Run service. Finish with a smoke test against `/health` and publish the dev URL in the README.

## 40. Add a manually approved production deployment
Goal: Promote tested releases to prod with explicit approval.
Description: Provision a prod Cloud Run service and Neon database mirroring the dev setup in `_docs/deployment.md`. Add a workflow, triggered by a version tag and protected by a GitHub Environment approval rule, that deploys the already-built image to prod.

## 41. Add the local observability stack
Goal: See backend traces locally in Grafana.
Description: Add the `grafana/otel-lgtm` image (Grafana, Prometheus, Loki, Tempo) to `docker-compose.yml`. Bootstrap the OpenTelemetry SDK in the FastAPI app with automatic FastAPI instrumentation exporting via OTLP, and confirm that a request trace appears in Grafana.

## 42. Add detailed backend tracing and structured logs
Goal: Trace the "run investigation" journey through every backend step.
Description: Add OpenTelemetry spans for SQLAlchemy, the data service, each analysis function, and the investigation service. Emit structured JSON logs that include the trace ID, and add a test or check that no secrets or raw user questions appear in telemetry.

## 43. Add metrics, Gemini telemetry, and the investigation dashboard
Goal: Measure investigation health, latency, and AI usage in one dashboard.
Description: Record metrics for investigation count, success/failure rate, end-to-end latency, Gemini latency, and token usage, and add spans for each Gemini call following the OpenTelemetry GenAI semantic conventions. Build a Grafana dashboard for the investigation journey and commit it as JSON in the repository.

## 44. Add frontend tracing
Goal: See one trace from the browser click through to the database write.
Description: Add OpenTelemetry browser instrumentation to the React app and propagate trace context on API requests. Confirm in the local Grafana that a single trace covers the browser, API, analysis, Gemini, and database spans for an investigation.

## 45. Connect deployed environments to Grafana Cloud and add an alert
Goal: Get notified when users are affected in dev or prod.
Description: Configure the Cloud Run services to export telemetry to Grafana Cloud and import the committed investigation dashboard. Create an alert on user impact, for example investigation failure rate above 10% over 10 minutes, and document how to trigger it deliberately.

## 46. Build the alert-triggered diagnosis agent
Goal: Have an agent investigate automatically when an alert fires.
Description: Connect the Grafana alert webhook to a GitHub Actions workflow that starts a coding agent with the alert context and read-only access to Grafana Cloud logs and traces. The agent writes its diagnosis (symptom, evidence, likely cause, affected code) to a new GitHub Issue.

## 47. Let the on-call agent propose fixes and demonstrate it
Goal: Close the loop from alert to reviewed fix.
Description: Extend the alert-triggered agent workflow so that, after diagnosing, the agent opens a fix PR linked to the diagnosis issue, which goes through normal CI and approval. Stage a realistic failure in dev, record the full alert → diagnosis → PR run, and document it in `_docs/on-call.md`.

## 48. Implement correlation and lagged-relationship analysis
Goal: Measure whether two indicators move together, including with a delay.
Description: Add a function in `copilot_core` that aligns two series, computes correlation and cross-correlation over a configurable range of lags, and reports sample sizes and significance. Label results as associations rather than causes, register the function as a Gemini tool, and add unit tests.

## 49. Implement the BigQuery data service
Goal: Read live curated data from BigQuery with strict cost and access controls.
Description: Implement the `DataService` interface in `copilot_core` against the curated BigQuery marts listed in `_docs/data-contract.md`, using a read-only service account and a dataset allowlist. Enforce `maximum_bytes_billed`, dry-run cost checks, and timeouts, and add tests that run against BigQuery only behind an explicit flag.

## 50. Add live mode with authentication
Goal: Let authorized users switch to live BigQuery data safely.
Description: Add OIDC login (or Cloud Run IAP) that unlocks live mode for allowlisted users, while anonymous visitors stay in demo mode. Grant the Cloud Run runtime service account read-only BigQuery access, and add tests that unauthenticated requests cannot reach live data.

## 51. Implement the SQL fallback validator
Goal: Ensure any AI-generated SQL is read-only and limited to approved tables.
Description: Use sqlglot to parse candidate SQL, accept only `SELECT` statements, check every table against an allowlist, and enforce a row limit. Support transpiling BigQuery SQL to DuckDB for demo mode, and test with a broad set of malicious and malformed queries.

## 52. Add the SQL fallback as a Gemini tool
Goal: Let Gemini answer questions the approved functions cannot, under strict controls.
Description: Expose a `run_validated_query` tool that passes Gemini-generated SQL through the sqlglot validator, runs it with timeouts, and logs the query. Rejected or failed queries must return a clear error to the model and the user, and results must go through the same numerical claim validation as other tools.

## 53. Validate failure paths and numerical consistency
Goal: Prove the application behaves honestly under bad inputs and outages.
Description: Write tests for missing data, unsupported questions, invalid SQL, BigQuery and Gemini outages, and timeouts. Add a check that the same investigation produces identical numbers in the narrative, charts, tables, and PDF.

## 54. Finalize the README and documentation
Goal: Let a new visitor understand, run, and evaluate the project quickly.
Description: Complete the README with the problem description, features, screenshots, architecture diagram, demo URL, and one-command setup. Finish `_docs/architecture.md`, the security notes, data limitations, and a short guide to the agent-driven development workflow, and check everything against the acceptance criteria in `_docs/plan.md`.

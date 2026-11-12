# African Economic Intelligence Copilot

## MVP Product Scope and Technical Decisions

**Status:** MVP scope agreed; tech stack selected (FastAPI with Jinja and HTMX)  
**Primary audience:** Economic and data analysts  
**Primary objective:** Investigate economic developments across African economies using reproducible statistical analysis and AI-assisted interpretation grounded in available data.

---

## 1. Product vision

The African Economic Intelligence Copilot is an AI-powered economic investigation workspace for analysts studying African economies.

Analysts can ask questions such as:

- Why has inflation increased in Kenya?
- How does GDP growth in Kenya compare with Nigeria and South Africa?
- Are exchange-rate movements associated with changes in inflation, including with a time lag?
- Which countries have experienced unusual movements in interest rates?
- What changed in a country's key economic indicators over the past five years?

The copilot retrieves economic data, performs statistical analysis, presents interactive charts and tables, explains findings with evidence, and identifies gaps in the available data.

### Product principles

1. **Evidence first:** Claims must be grounded in available data and cited sources.
2. **Calculate first, interpret second:** Statistical calculations are performed by application code, not improvised by the language model.
3. **Transparent uncertainty:** Distinguish observed facts, statistical relationships, plausible explanations, and unsupported hypotheses.
4. **Reproducibility:** Preserve the inputs, parameters, methods, and source references for each investigation.
5. **Pan-African ambition, honest coverage:** Support all African countries available in the source datasets, without implying every indicator is available for every country or period.
6. **Safe data access:** The AI must not have unrestricted access to the warehouse.
7. **Useful without private credentials:** Reviewers can test core functionality in demo mode.

### Project goals

1. **Product:** A working, deployed economic investigation workspace.
2. **AI engineering:** A grounded Gemini tool-calling workflow with validated outputs, traced and observable in production.
3. **AI-assisted development:** A visible, documented agent-driven development process (specs, task tracker, agent team, `AGENTS.md`, skills/subagents).

---

## 2. Agreed product scope

| Area | Decision |
| --- | --- |
| Primary audience | Economic and data analysts |
| Primary job | Investigate economic developments |
| Investigation types | Explain changes, compare countries, investigate relationships, detect anomalies |
| Geographic coverage | Pan-African, limited to countries present in the available datasets |
| Initial indicator scope | GDP, inflation, exchange rates, interest rates, and trade |
| Analytical approach | Statistical analysis plus AI-assisted interpretation grounded in data |
| Data source | Existing ingestion project and curated BigQuery/dbt models and marts |
| Data access | Direct, read-only BigQuery access through an application-controlled data layer |
| AI analysis control | Approved analysis tools by default; validated read-only SQL as a fallback |
| User experience | Hybrid workspace: natural-language questions or interactive selection of countries, indicators, and periods |
| Results | Interactive workspace with narrative findings, charts, tables, and explorable sources |
| Uncertainty handling | Answer only what the evidence supports; cite sources and disclose gaps and uncertainty |
| Investigation continuity | Saved investigation history; users can revisit and continue previous investigations |
| Anomaly handling | Automatically compare historical patterns and relevant countries, then suggest data-grounded possible explanations |
| Explanation strategy | Start with available economic data; distinguish correlation from causation |
| AI provider | Google Gemini API |
| Application stack | FastAPI serving Jinja pages and HTMX partials + a JSON API defined contract-first in OpenAPI + PostgreSQL |
| Deployment | Public web demo on Google Cloud Run with separate dev and prod environments, plus authorized live-data mode |
| Reviewer access | Both bundled demo data and live BigQuery mode for authorized users |
| Analytical depth | Analyst-grade: historical baselines, lagged relationships, configurable anomaly methods, and drill-down analysis |
| Export | PDF reports with findings, charts, methodology, sources, and limitations |
| Operations | OpenTelemetry tracing, metrics, and structured logs; user-impact alerting; AI on-call agent |

### Anomaly investigation behavior

When an anomaly is detected, the copilot should:

1. Identify the unusual movement and show the supporting statistic.
2. Compare it with the indicator's historical baseline.
3. Compare relevant countries or related indicators where appropriate.
4. Show the period, method, and parameters used.
5. Suggest plausible explanations only when supported by the available evidence.
6. Clearly label hypotheses and avoid implying that statistical association proves causation.

### Progressive explanation behavior

For example, when investigating rising inflation, the system should:

1. Confirm the inflation trend and calculate the magnitude of change.
2. Inspect related indicators, historical periods, and relevant country comparisons.
3. Calculate correlations or lagged relationships where appropriate.
4. Ask Gemini to interpret the returned evidence.
5. Present plausible explanations, caveats, and alternative interpretations.

The first version will not automatically conduct external web research. Explanations will be based on the available economic data and its metadata.

---

## 3. Delivery priorities

Delivery is ordered so that a complete, deployed, observable end-to-end system exists before analytical depth is added.

### Tier 1: core MVP (must ship)

- Demo mode end to end on bundled data (DuckDB over Parquet)
- Trend/comparison and anomaly investigations via approved analysis tools
- Gemini interpretation of computed results, with numerical claims traceable to tool outputs
- Saved investigation history and PDF export
- Engineering foundations: specs and public task tracker, `AGENTS.md` with modular docs, unit/integration/end-to-end tests, one-command Docker Compose setup, public deployment, CI/CD with dev and prod, observability, user-impact alerting, and an on-call agent

### Tier 2: product completeness (after Tier 1)

- Correlation and lagged-relationship investigations
- Live BigQuery mode for authorized users
- Constrained SQL fallback with sqlglot validation

### Tier 3: depth (if time permits)

- Configurable anomaly methods and drill-down analysis
- Richer workspace interactions (linked charts, source explorer)

---

## 4. Technical decisions

These are implementation decisions. They can be revisited if repository inspection reveals a strong reason.

### 4.1 Application architecture: FastAPI, Jinja and HTMX

**Decision:** FastAPI serves server-rendered Jinja pages and HTMX partials, and a JSON API defined contract-first in `api/openapi.yaml`. Both are thin routes over `copilot_core`, a standalone Python package that holds all data access, analytics, and AI orchestration and has no web-framework dependencies.

```text
Browser
  - Jinja-rendered HTML pages and HTMX partials
  - HTMX with the SSE extension (investigation progress)
  - Plotly.js charts drawn from figure JSON built in Python
  - all vendored static files from /static/, nothing from a CDN
              |
              |  HTML over HTTP + server-sent events
              v
FastAPI (one process)
  - HTML routes: pages, /partials/..., /static/... (outside the contract)
  - JSON API routes: /api/... and /health (in the OpenAPI contract)
              |
              v
copilot_core
  - Economic Data Service (DuckDB demo | BigQuery live)
  - Analytics functions (pandas, statsmodels, scipy)
  - Gemini orchestrator (tool calling)
  - Investigation repository (SQLAlchemy + Postgres)
  - Report renderer (Jinja2 + WeasyPrint)
```

**Why:**

- One language the owner can review end to end: every file is Python, HTML, CSS, plain JavaScript, or Markdown.
- No Node toolchain and no frontend build step.
- Pages render the same Pydantic results the API returns, so there are no separate frontend types to keep in sync.
- The screen and the PDF share Jinja templates, the Python number formatter, and the Python chart builder, so the same value prints the same way everywhere.
- One process serves the pages, the static files, and the API, which keeps local runs, tests, and deployment simple.
- One trace can span browser → API → data layer → Gemini, which supports the observability criterion.

**Alternatives considered:**

- **React + TypeScript SPA (Vite, Tailwind, shadcn/ui, TanStack Query):** Rejected. The owner does not know React and must be able to review and own all the code, and it adds a second language and toolchain. This was the original choice, scaffolded in #9 and #10, and replaced by #74.
- **Streamlit monolith:** Fastest to build, but it has no real frontend/backend split and it limits the multi-panel workspace.
- **Python full-stack frameworks (Reflex, Dash, NiceGUI):** More control than Streamlit, but smaller ecosystems and framework lock-in.

**Rules:**

- Write the OpenAPI spec first and commit it. The JSON API changes only after the contract does.
- HTML routes are outside the OpenAPI contract and are registered with `include_in_schema=False`.
- Templates and browser scripts display `copilot_core` results; they never compute new numbers.
- FastAPI routes stay thin. Business logic belongs in `copilot_core`.
- Pydantic models are the single source of truth for result objects, API schemas, Gemini tool schemas, stored JSON, and PDF content.

### 4.2 Separate repository

**Decision:** Keep the copilot in its own repository, separate from the ingestion project.

The copilot should consume the existing project's curated BigQuery models and marts rather than duplicate the ingestion pipelines.

**Why:**

- Ingestion, transformation, and AI investigation have different responsibilities.
- Changes to the copilot should not destabilize the data pipelines.
- Each project can be tested, deployed, and maintained independently.
- The separation demonstrates clear service boundaries.

**Alternative considered:** Put ingestion and the copilot in one repository. This could simplify navigation initially, but would couple the data platform to the application and blur project responsibilities.

### 4.3 Data source and access layer

**Decision:** Use curated dbt models and marts in BigQuery as the analytical source of truth, behind a data-service interface with two implementations.

Proposed data flow:

```text
Existing ingestion pipelines
  (IMF and other supported sources)
              |
              v
BigQuery + dbt
  (curated models and marts)
              |
              v  (exported snapshot for demo mode)
Economic Data Service
  - BigQueryDataService (live, read-only)
  - DuckDBDataService (demo, bundled Parquet)
  (approved queries, validation, data-quality checks)
              |
              v
Analytics functions + Gemini
  (calculate first, interpret second)
              |
              v
Investigation workspace
  (findings, charts, tables, sources, reports)
```

The application should not query raw ingestion tables by default.

**Why:** Curated models provide a more consistent contract and reduce the chance that the AI interprets raw or poorly standardized data incorrectly. DuckDB lets demo mode, local development, tests, and CI run the same code paths without cloud credentials.

**Live-mode controls:** a read-only service account, an allowlist of datasets, `maximum_bytes_billed`, dry-run cost checks, and query timeouts.

### 4.4 Hybrid analytical engine

**Decision:** Use approved Python analysis functions for common tasks, with constrained AI-generated SQL as a fallback (Tier 2).

Initial approved functions should cover:

- Time-series trends and growth rates
- Country and indicator comparisons
- Correlations and lagged relationships
- Historical-baseline comparisons
- Configurable anomaly detection

Libraries: pandas, statsmodels, and scipy.

When a question requires a query that the approved functions cannot answer, Gemini may generate SQL. The application must validate and constrain that SQL before execution against approved models.

**Required controls:**

- Read-only credentials and permissions
- Allowlist of permitted datasets and tables
- SQL validation with **sqlglot**: parse to an AST, accept only `SELECT`, check every table reference against the allowlist, and enforce a `LIMIT`
- Query limits and timeouts
- No writes, DDL, or unrestricted access to raw tables
- Logging of queries and analytical operations
- Clear error handling when a query is rejected or fails

sqlglot can also transpile BigQuery SQL to DuckDB, so the fallback can work in demo mode.

**Why not unrestricted AI-generated SQL?** It increases security, cost, correctness, and debugging risks. Approved tools provide predictable behavior for common analytical tasks while the fallback preserves flexibility.

### 4.5 Separate statistical findings from AI interpretation

**Decision:** Python computes numerical results; Gemini interprets the verified results.

**Implementation:** A single, auditable tool-calling loop using the `google-genai` SDK, or Pydantic AI as a thin typed wrapper. No LangChain or agent frameworks; multi-agent orchestration is out of scope.

The model must not invent statistics, claim it executed a query when it did not, or treat correlation as proof of causation.

The application should provide the model with structured analytical outputs and source metadata, then validate that displayed numerical claims are traceable to those outputs.

**Alternative considered:** Let Gemini perform the entire investigation through free-form reasoning. This is simpler to prototype, but less reproducible and harder to validate.

### 4.6 Demo mode and live mode

**Decision:** Provide two explicit data modes. Demo mode is the Tier 1 deliverable; live mode is Tier 2.

#### Demo mode

- Uses bundled, documented sample data (a Parquet snapshot of the curated marts, queried with DuckDB).
- Lets reviewers explore core analytical features without BigQuery credentials.
- Clearly labels sample data and avoids presenting it as live economic information.
- Must continue to work when BigQuery is unavailable.

#### Live mode

- Connects to curated BigQuery data for authorized users.
- Uses server-side credentials (the Cloud Run service identity) and restricted permissions.
- Never exposes credentials in browser code or the public repository.
- Protected by authentication (OIDC login in FastAPI, or Cloud Run IAP).
- Should have sensible query limits and cost controls.

If Gemini or BigQuery is unavailable, the application must clearly explain the limitation rather than pretend an AI investigation succeeded.

**Alternative considered:** Require live BigQuery access for every interaction. That would make the demo fragile for reviewers and expose the project to unnecessary cloud costs.

### 4.7 Investigation history

**Decision:** Use PostgreSQL with SQLAlchemy 2 and Alembic migrations. Run Postgres in Docker Compose locally and use a managed instance (Neon) for dev and prod.

Store:

- User question
- Selected countries, indicators, and time periods
- Analytical parameters and methods
- Findings and chart configuration (as validated Pydantic JSON)
- Source references and relevant metadata
- Timestamps and status

BigQuery remains the economic analytics store; PostgreSQL stores application records and investigation history.

**Why Neon over Cloud SQL:** Its free tier scales to zero, which suits a public demo; Cloud SQL has a continuous minimum cost. Cloud SQL remains an option if tighter GCP IAM integration becomes necessary.

**Alternative considered:** Session state or local files. These are simpler locally but do not reliably provide persistent history in a deployed, multi-session application.

For the MVP, saved investigations do not require collaborative editing, shared workspaces, or a complex permissions model.

### 4.8 PDF reports

**Decision:** Generate PDFs server-side from stored investigation results using Jinja2 HTML templates and WeasyPrint. Render charts as static images with Plotly/Kaleido. Do not trigger a second, independent AI answer when exporting.

A report should contain:

- Executive summary and key findings
- Charts and supporting tables
- Countries, indicators, and periods analyzed
- Methodology and analytical parameters
- Source names and available source metadata
- Data-quality caveats and uncertainty
- Generation timestamp

**Alternative considered:** Add CSV exports and spreadsheet workflows immediately. These are useful, but PDF reports better demonstrate the end-to-end investigation workflow. CSV export can follow once the core product works.

### 4.9 No background monitoring in the MVP

**Decision:** Support on-demand investigations only. Anomaly detection runs when an analyst requests an investigation or analysis that includes it.

**Why:** Scheduled monitoring introduces scheduling, thresholds, notification delivery, retries, and operational monitoring. These are valuable later, but are not necessary to prove the core investigation capability.

Operational alerting on the application's own health (section 4.12) is separate and in scope.

### 4.10 Testing

**Decision:** Three test layers. Python tests live in `tests/`, and unit, integration, and end-to-end tests (Playwright for Python via pytest-playwright) all run with one command, `uv run pytest`, and in CI. There is no `npm test`: templates and partials are tested with pytest and FastAPI TestClient, and browser behaviour with Playwright.

| Layer | Tooling | Covers |
| --- | --- | --- |
| Unit | pytest, hypothesis | Analytics functions, SQL validation, Pydantic contracts, Gemini orchestration with a stubbed model |
| Integration | pytest + FastAPI TestClient against Postgres and DuckDB (via Docker Compose) | API endpoints, persistence, data service, PDF generation |
| End to end | Playwright | Key user journeys: run an investigation, save it, reopen it, export a PDF; demo-mode labelling; service-unavailable errors |

Tests must not call the real Gemini API or BigQuery by default. Use recorded or stubbed responses, and keep optional live smoke tests behind an explicit flag.

### 4.11 Containerization and deployment

**Decision:**

- `docker compose up` starts the full local system: the API, Postgres, and the observability stack (`grafana/otel-lgtm`). There is no separate frontend service.
- There is no frontend build or frontend container: FastAPI serves the pages, the static files, and the API from one process, so deployment is a single Cloud Run service per environment.
- Two environments on Google Cloud Run: **dev** and **prod**, with separate secrets and databases.
- Secrets live in Google Secret Manager and never in the repository, images, logs, or reports.

**Why Cloud Run:** It integrates with BigQuery and Google Cloud IAM through service identities, scales to zero, and gives a public URL.

**Alternative considered:** A simpler Python hosting platform such as Render. It may be easier to deploy initially, but Cloud Run offers a clean path to service identities and controlled BigQuery access.

Keep the architecture small. Do not introduce Kubernetes, microservices, a message broker, or a separate vector database for this MVP; none is required for the core workflow.

### 4.12 CI/CD

**Decision:** GitHub Actions.

1. **On every pull request:** lint (ruff), type checks (mypy), and the full test suite, which also validates the OpenAPI contract and the vendored-file checksums. There is no ESLint, tsc, or Node step.
2. **On merge to `main`:** build the image, push it to Artifact Registry, and deploy automatically to **dev**.
3. **Promotion to prod:** a manually approved workflow (GitHub Environments protection rule) deploys a versioned release tag to **prod**.

Authenticate to Google Cloud with Workload Identity Federation instead of long-lived JSON keys.

### 4.13 Observability, alerting, and on-call agent

**Decision:** Instrument with OpenTelemetry and view in Grafana.

- **Key user journey:** "run an investigation" (browser → API → data service → analytics → Gemini → Postgres).
- **Traces:** browser tracing with a small hand-written script that propagates W3C trace context (no OpenTelemetry web SDK, which would need a JavaScript build; see #44), OTel instrumentation for FastAPI, SQLAlchemy, and data service, plus custom spans for each analysis tool and each Gemini call (following OpenTelemetry GenAI semantic conventions: model, token counts, latency, and tool calls).
- **Metrics:** investigation count, success/failure rate, end-to-end latency, Gemini latency and token usage, and BigQuery bytes processed.
- **Logs:** structured JSON logs carrying the trace ID.
- **Privacy:** no credentials, API keys, or raw user questions in telemetry. Log investigation IDs and metadata instead.
- **Local:** `grafana/otel-lgtm` in Docker Compose (Grafana, Prometheus, Loki, Tempo).
- **Deployed:** Grafana Cloud free tier as the OTLP endpoint.

**Alerting:** At least one user-impact alert, for example: investigation failure rate above 10% over 10 minutes, or p95 investigation latency above a threshold.

**On-call agent:** The alert fires a webhook that triggers an agent (for example, a GitHub Actions workflow running a coding agent). The agent receives the alert context, reads the relevant traces and logs through read-only access, diagnoses the cause, and opens a pull request with a proposed fix. Production changes still go through the normal CI/CD and manual prod approval.

### 4.14 AI-assisted development workflow

**Decision:** Build the project with a documented, agent-driven workflow that reviewers can inspect.

- **Specs and tracker:** Product spec and feature specs in `_docs/`; a public GitHub Project with Issues that carry acceptance criteria. Agents pick up and close issues; PRs link to them.
- **Context management:** `_docs/AGENTS.md` lists the commands (`uv sync`, `uv run pytest`), the project rules (for example, no new dependency without asking), and links to modular docs:
  - `_docs/process.md`: how work is organized (one GitHub issue at a time, acceptance criteria checked before starting and before closing, regular commits)
  - `_docs/agent-team.md`: agent roles and collaboration
  - `_docs/architecture.md`: system design and decisions
  - `_docs/data-contract.md`: available models, fields, and coverage
  - `_docs/api.md`: pointer to the OpenAPI contract
- **Agent team:**

| Role | Responsibility | Inputs → outputs |
| --- | --- | --- |
| PM agent | Turns requirements into specs and issues with acceptance criteria | plan.md → specs, issues |
| Backend agent | Implements `copilot_core` and FastAPI routes against the contract | issue + OpenAPI → backend PR |
| Frontend agent | Implements the UI in Jinja templates, HTMX partials, CSS, and small plain-JavaScript files, rendering `copilot_core` results | issue + `copilot_core` result models → frontend PR |
| QA agent | Writes and maintains integration and Playwright tests from acceptance criteria | acceptance criteria → test PR |
| Ops agent | Owns CI/CD, telemetry, alerts, and on-call response | alerts + telemetry → fix PR |

- **Collaboration:** Work proceeds one GitHub issue at a time. The `copilot_core` result models are the hand-off between backend and frontend; the OpenAPI contract is the hand-off between the API and its clients and tests. The QA agent tests against acceptance criteria, not implementation details. A human reviews and merges every PR.
- **Reusable capabilities:** Project skills (`SKILL.md`) for repeated tasks such as "add an analysis tool", "add an API endpoint", and "add a Playwright journey", plus subagent definitions for the roles above.

---

## 5. Explicitly out of scope

| Feature | Why it is excluded initially |
| --- | --- |
| Forecasting and predictive models | Requires a different validation approach from historical investigation |
| Causal inference claims | Requires stronger identification strategies than correlations or lagged relationships |
| External web research | Adds retrieval, source-quality, and citation-validation complexity |
| Scheduled economic alerts | Adds background jobs and notification infrastructure (application health alerting is in scope) |
| Multi-agent orchestration inside the product | Adds complexity without proving additional value (multi-agent *development* is in scope) |
| User-created unrestricted SQL editor | Adds security and usability risks; controlled SQL fallback is sufficient |
| Multi-user collaboration | Not required to validate individual analyst workflows |
| Exhaustive coverage of every indicator | Source availability and quality vary by country and period |
| CSV export | Useful follow-up feature after the core PDF report works |

These features can be reconsidered after the MVP demonstrates reliable investigations.

---

## 6. MVP acceptance criteria

### Product

- [ ] A reviewer can open the public demo without cloud credentials.
- [ ] An analyst can select countries, indicators, and time periods or start with a natural-language question.
- [ ] The copilot can perform trend, comparison, and anomaly investigations (relationship investigations in Tier 2).
- [ ] Every numerical finding comes from executed analysis, not invented model output.
- [ ] Charts and tables match the results used in the narrative.
- [ ] Sources, methodology, missing data, and uncertainty are visible.
- [ ] A user can save and revisit an investigation.
- [ ] A user can export an investigation to PDF.
- [ ] Demo mode clearly distinguishes sample data from live data.
- [ ] The application handles unavailable data or AI services without fabricating success.
- [ ] Live BigQuery access is read-only and protected from unauthorized use (Tier 2).

### Engineering

- [ ] README describes the problem, functionality, and expected behavior.
- [ ] Specs and a public task tracker with acceptance criteria exist and are used.
- [ ] `AGENTS.md` links to modular docs, including the agent team definition.
- [ ] The full system runs locally with one command (`docker compose up`).
- [ ] Unit, integration, and end-to-end tests run with one command and pass.
- [ ] The application is deployed at a public URL.
- [ ] CI runs tests on every PR; CD deploys to dev automatically and to prod with manual approval.
- [ ] The "run investigation" journey has correlated metrics, traces, and logs visible in Grafana, with no secrets or user data in telemetry.
- [ ] At least one user-impact alert is configured.
- [ ] An on-call agent responds to an alert and opens a fix PR.

---

## 7. Implementation sequence

Phases are ordered so that a working, end-to-end system exists early and later phases add depth.

### Phase 0 — Set up the AI-assisted workflow

- Expand `_docs/AGENTS.md`, the modular docs in `_docs/`, and the agent team definition.
- Create the public GitHub Project; turn this plan into specs and issues with acceptance criteria.
- Add initial project skills and subagent definitions.

**Deliverable:** A repository where agents have durable context and a tracked backlog.

### Phase 1 — Inspect the existing data platform

- Review the existing ingestion repository and documentation.
- Identify actual BigQuery datasets, dbt models, marts, schemas, and source metadata.
- Map which countries, indicators, units, frequencies, and time periods are available.
- Identify missing or inconsistent data before promising specific analysis.
- Export a documented Parquet snapshot for demo mode.

**Deliverable:** `_docs/data-contract.md` based on real models and fields, plus the demo dataset.

### Phase 2 — Contract and walking skeleton

- Write the OpenAPI contract for investigations, analyses, history, and reports.
- Scaffold the FastAPI app with the Jinja and HTMX workspace shell, `copilot_core`, Postgres with Alembic, and Docker Compose.
- Add CI (lint, type checks and tests on every PR) and protect `main` so changes land only through passing PRs.

**Deliverable:** A skeleton that runs with one command locally, with CI on every PR.

The first end-to-end path and the contract-conformance test move to Phase 3, where the data service and analysis they need are built; the dev deployment moves to Phase 6, after the production image, which needs PDF export from Phase 5.

### Phase 3 — Analytical foundation

- Implement the DuckDB data service and filters.
- Implement and test trend, growth, comparison, and anomaly functions (correlation and lag in Tier 2).
- Define standard result objects with values, units, period, methodology, and source metadata.
- Wire one thin end-to-end path: select country and indicator → trend result → chart → saved investigation.
- Test that the FastAPI app matches the OpenAPI contract.

**Deliverable:** Tested analytical functions that work independently of the AI, reachable through one end-to-end path.

### Phase 4 — Gemini orchestration

- Integrate the Gemini API with tool calling over the approved functions.
- Ensure interpretations refer to returned results and acknowledge uncertainty; validate numerical claims.
- Stream investigation progress to the frontend.
- Add timeouts, error handling, and cost controls.

**Deliverable:** A reliable AI investigation flow grounded in actual analysis outputs.

### Phase 5 — Workspace, history, and reports

- Add natural-language input alongside interactive filters.
- Display findings, charts, tables, source references, and caveats.
- Complete investigation history (list, reopen, continue).
- Generate PDF reports from stored investigation results.
- Add Playwright end-to-end tests for the key journeys.

**Deliverable:** A usable end-to-end investigation workspace.

### Phase 6 — Operations

- Add OpenTelemetry instrumentation, structured logs, and metrics for the key journey.
- Add Grafana dashboards and the user-impact alert.
- Build the production image and deploy to dev on Cloud Run, then automatically on merge.
- Add the manually approved prod deployment.
- Implement the on-call agent and demonstrate it on a staged failure.

**Deliverable:** An observable, alerting, two-environment deployment with an on-call agent.

### Phase 7 — Tier 2 features

- Correlation and lagged-relationship investigations.
- Live BigQuery mode with read-only service identity, authentication, and cost controls.
- Constrained SQL fallback with sqlglot validation.

**Deliverable:** Full product scope for authorized live use.

### Phase 8 — Validate and document

- Test representative investigations across multiple countries and indicators.
- Test missing data, unsupported questions, invalid SQL, and unavailable services.
- Verify numerical consistency between text, charts, tables, and PDFs.
- Document setup, architecture, security, data limitations, the agent workflow, and demo instructions.
- Review the project against the acceptance criteria in section 6.

**Deliverable:** A documented, tested, publicly demonstrable project.

---

## 8. Technical principles and implementation guardrails

1. **Inspect actual schemas before coding queries.** Do not assume the existing warehouse contains fields or models that have not been verified.
2. **Contract first.** Change the OpenAPI spec before changing API behavior.
3. **Use a data-access abstraction.** Keep BigQuery- and DuckDB-specific operations out of the UI, API routes, and AI orchestration code.
4. **Keep analytics deterministic where possible.** Implement calculations in tested functions.
5. **Use structured outputs.** Each finding should include the metric, value, unit, period, geography, method, source, and caveat where applicable.
6. **Preserve source lineage.** Track dataset or model identifiers and any available original source and update metadata.
7. **Handle units and frequency carefully.** Do not compare incompatible units, frequencies, or definitions without explicit transformation and explanation.
8. **Represent missingness honestly.** Missing data is not zero; sparse or stale data should be visible.
9. **Protect the live service.** Apply authentication where needed, least-privilege access, query limits, timeouts, and server-side secret management.
10. **Do not expose secrets.** Keep API keys and cloud credentials out of source control, browser bundles, logs, telemetry, and generated reports.
11. **Test failure paths.** Invalid queries, timeouts, missing indicators, and unavailable services should produce clear errors rather than fabricated answers.
12. **Keep demo data identifiable.** Clearly label sample data and any synthetic values.
13. **Instrument as you build.** Add spans and metrics with each feature rather than retrofitting them.
14. **Avoid premature infrastructure.** Add components only when they support a defined MVP requirement.
15. **Ask before adding dependencies.** Dependencies are declared in `pyproject.toml`, and none is added without approval.

---

## 9. Final product recommendation

Treat the African Economic Intelligence Copilot as an **economic investigation system, not a chatbot wrapped around a dashboard**, and build it with a process that is as inspectable as its results.

Its value is the complete workflow:

1. Retrieve the right data.
2. Perform reproducible analysis.
3. Interpret the evidence.
4. Present the results and caveats.
5. Preserve the investigation.
6. Produce a report that another analyst can inspect.

The development process should be equally visible: specs, a tracked backlog, a defined agent team, durable agent context, automated tests, CI/CD, and production telemetry.

The next step is Phase 0 (agent workflow and backlog), followed immediately by Phase 1: inspecting the existing repository's actual BigQuery and dbt schemas before finalizing the supported indicators and query contracts. This ensures the application reflects the data platform that exists rather than an assumed dataset.

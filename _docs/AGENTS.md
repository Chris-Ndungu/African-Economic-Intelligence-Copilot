Product

The African Economic Intelligence Copilot is an AI-powered investigation
workspace for economic and data analysts studying African economies.
Analysts ask a question or pick countries, indicators and periods, and the
copilot explains trends, compares countries and flags anomalies. Python code
computes every number; Gemini only interprets the computed results and must
cite them. It runs in demo mode on a bundled data snapshot without
credentials, and in live mode on curated BigQuery data for authorized users.

Commands

- `uv sync` - install dependencies
- `uv run pytest` - the whole suite
- `uv run pytest tests/test_smoke.py` - one test file
- `uv run uvicorn backend.main:app --reload` - run the API on port 8000 (docs at `/docs`)
- `npm ci` - install frontend dependencies (run from `frontend/`)
- `npm run dev` - serve the frontend at `http://localhost:5173` (run from `frontend/`)
- `npm test` - run the frontend Vitest suite (run from `frontend/`)
- `npm run lint` - lint the frontend with ESLint, failing on any warning (run from `frontend/`)
- `npm run build` - type-check and build the frontend into `frontend/dist/` (run from `frontend/`)
- `npm run gen-types` - regenerate `frontend/src/api/schema.d.ts` from `api/openapi.yaml` (run from `frontend/`)
- `npm run check-types` - fail if `frontend/src/api/schema.d.ts` is out of date with the contract (run from `frontend/`)
- `npx @redocly/cli lint api/openapi.yaml` - lint the OpenAPI contract
- `docker run -d --name copilot-postgres -e POSTGRES_USER=copilot -e POSTGRES_PASSWORD=copilot -e POSTGRES_DB=copilot -p 5432:5432 postgres:17` - start a local Postgres; then set `DATABASE_URL=postgresql+psycopg://copilot:copilot@localhost:5432/copilot` in `.env` or the shell
- `uv run alembic upgrade head` - apply the migrations to the database in `DATABASE_URL`; `uv run alembic downgrade base` removes them
- `uv run alembic check` - fail if the SQLAlchemy models in `copilot_core/db.py` and the migrations differ (needs a database at head)
- `uv run alembic revision --autogenerate -m "describe the change"` - draft a migration from model changes; review it before committing
- `uv run pytest tests/test_migrations.py` - the Postgres integration tests; they need `DATABASE_URL` and a role that can create databases, run in a throwaway database, and are skipped with a reason when `DATABASE_URL` is not set
- `docker rm -f copilot-postgres` - stop and remove the local Postgres

Rules

- Dependencies are added in `pyproject.toml`. Do not add one without
  asking

Repository layout

- `_docs/` - plan, backlog, process and design documents
- `alembic.ini` - Alembic configuration; the connection string comes from `DATABASE_URL`, never this file
- `api/` - the OpenAPI contract, `api/openapi.yaml`
- `backend/` - FastAPI application: thin routes, settings, no business logic
- `frontend/` - React + TypeScript app (Vite, Tailwind, shadcn/ui), with its own npm scripts and Vitest tests
- `copilot_core/` - data access, analysis, Gemini orchestration and
  persistence, with no web-framework imports
- `tests/` - all Python tests, run with `uv run pytest`
- `main.py` - placeholder entry point from `uv init`
- `migrations/` - Alembic migrations; the database schema changes only through a new migration here
- `pyproject.toml` - project metadata, dependencies and pytest settings
- `uv.lock` - locked dependency versions, updated by `uv`
- `README.md` - project overview, setup and test commands
- `AGENTS.md` - pointer to this file for agents that read the repository root
- `CLAUDE.md` - loads this file into Claude Code sessions
- `.python-version` - Python version used by `uv`
- `.gitignore` - files Git ignores
- `.github/` - GitHub issue and pull request templates
- `.claude/` - Claude Code project skills and subagent definitions

Conventions

- Business logic lives in `copilot_core`, with no web-framework imports
- FastAPI routes in `backend/` stay thin: validate input, call
  `copilot_core`, return the result
- Tests live in `tests/` and run with `uv run pytest`
- The OpenAPI contract changes before API behavior does
- Follow the implementation guardrails in section 8 of
  [plan.md](plan.md#8-technical-principles-and-implementation-guardrails)

Skills and subagents

- [.claude/skills/add-analysis-function/SKILL.md](../.claude/skills/add-analysis-function/SKILL.md) - skill: add a tested, deterministic analysis function in `copilot_core`
- [.claude/skills/add-api-endpoint/SKILL.md](../.claude/skills/add-api-endpoint/SKILL.md) - skill: add an endpoint, contract first, with a thin route and a `TestClient` test
- [.claude/skills/add-playwright-journey/SKILL.md](../.claude/skills/add-playwright-journey/SKILL.md) - skill: add an end-to-end journey on demo data with stubbed Gemini
- [.claude/agents/pm.md](../.claude/agents/pm.md) - PM subagent: grooms requirements into issues with checkable acceptance criteria
- [.claude/agents/backend.md](../.claude/agents/backend.md) - backend subagent: implements `copilot_core` and FastAPI routes against the contract
- [.claude/agents/frontend.md](../.claude/agents/frontend.md) - frontend subagent: implements the UI against the contract and generated types
- [.claude/agents/qa.md](../.claude/agents/qa.md) - QA subagent: writes tests from acceptance criteria, editing only `tests/`
- [.claude/agents/ops.md](../.claude/agents/ops.md) - ops subagent: owns CI/CD, telemetry, alerts and fix PRs

Documents

- [process.md](process.md) - how work is organized
- [plan.md](plan.md) - product plan and technical decisions
- [task.md](task.md) - backlog of tasks
- [task-template.md](task-template.md) - template for groomed issues
- [team/pm.md](team/pm.md) - Product Manager role
- [team/software-engineer.md](team/software-engineer.md) - Software Engineer role
- [team/qa-engineer.md](team/qa-engineer.md) - QA Engineer role
- [agent-team.md](agent-team.md) - agent roles and how they collaborate
- [architecture.md](architecture.md) - system design and decisions
- [data-contract.md](data-contract.md) - available data models, fields and coverage
- [api.md](api.md) - the OpenAPI contract between frontend and backend

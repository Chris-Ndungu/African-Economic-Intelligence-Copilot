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

Rules

- Dependencies are added in `pyproject.toml`. Do not add one without
  asking

Repository layout

- `_docs/` - plan, backlog, process and design documents
- `backend/` - FastAPI application: thin routes, settings, no business logic
- `copilot_core/` - data access, analysis, Gemini orchestration and
  persistence, with no web-framework imports
- `tests/` - all Python tests, run with `uv run pytest`
- `main.py` - placeholder entry point from `uv init`
- `pyproject.toml` - project metadata, dependencies and pytest settings
- `uv.lock` - locked dependency versions, updated by `uv`
- `README.md` - project overview, setup and test commands
- `AGENTS.md` - pointer to this file for agents that read the repository root
- `CLAUDE.md` - loads this file into Claude Code sessions
- `.python-version` - Python version used by `uv`
- `.gitignore` - files Git ignores

Conventions

- Business logic lives in `copilot_core`, with no web-framework imports
- FastAPI routes in `backend/` stay thin: validate input, call
  `copilot_core`, return the result
- Tests live in `tests/` and run with `uv run pytest`
- The OpenAPI contract changes before API behavior does
- Follow the implementation guardrails in section 8 of
  [plan.md](plan.md#8-technical-principles-and-implementation-guardrails)

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

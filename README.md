# African Economic Intelligence Copilot

[![CI](https://github.com/Chris-Ndungu/African-Economic-Intelligence-Copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Chris-Ndungu/African-Economic-Intelligence-Copilot/actions/workflows/ci.yml)

An AI-powered economic investigation workspace for analysts studying African economies.

## Live demo

- Public demo (prod): <https://copilot-prod.onrender.com>
- Dev: <https://copilot-dev.onrender.com>

Both run on free Render services that sleep when idle, so the first load after
a pause can take up to a minute. Deployment is described in
[_docs/deployment.md](_docs/deployment.md).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13.

```
uv sync
```

## Run locally

```
uv run uvicorn backend.main:app --reload
```

Then open http://localhost:8000. FastAPI serves the workspace pages, the
static files and the JSON API from one process; the API docs are at
http://localhost:8000/docs. No database, Gemini key or network access is
needed to see the workspace.

## Run with Docker

With only Docker installed:

```
docker compose up
```

Then open http://localhost:8000. Compose starts Postgres (`db`) and the app
(`api`), applies the database migrations, and serves the workspace and the
JSON API. Editing Python files reloads the server; editing templates or
static files shows on the next browser refresh. No `.env` file is needed.

- Ports 5432 (Postgres) and 8000 (the app) must be free on the host.
- Stop with `docker compose down`; the database is kept in a named volume.
- Reset the database with `docker compose down -v`, then `docker compose up`.

## Tests

```
uv run pytest
```

## Documentation

- [Product plan](_docs/plan.md)
- [Backlog](_docs/task.md)
- [Agent instructions](_docs/AGENTS.md)
- [Process](_docs/process.md)
- [Deployment](_docs/deployment.md)
- [Agent team](_docs/agent-team.md)
- Project board: TODO - link added once the board is created

# African Economic Intelligence Copilot

An AI-powered economic investigation workspace for analysts studying African economies.

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

## Tests

```
uv run pytest
```

## Documentation

- [Product plan](_docs/plan.md)
- [Backlog](_docs/task.md)
- [Agent instructions](_docs/AGENTS.md)
- [Process](_docs/process.md)
- [Agent team](_docs/agent-team.md)
- Project board: TODO - link added once the board is created

# Development image for `docker compose up`. The production image is #36.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-install-project

# The source is also bind-mounted by docker-compose.yml, so edits show
# without a rebuild; this copy makes the image work on its own too.
COPY alembic.ini ./
COPY migrations ./migrations
COPY copilot_core ./copilot_core
COPY backend ./backend
COPY api ./api

EXPOSE 8000

# Apply migrations, then serve. If a migration fails, `&&` stops here and
# the container exits non-zero without serving requests.
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && exec uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir backend --reload-dir copilot_core"]

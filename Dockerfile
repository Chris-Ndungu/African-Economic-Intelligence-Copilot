# Production image: one FastAPI process serves the pages, the static files and
# the JSON API. Build with `docker build -t copilot .`; pushing and deploying
# it are #38 and #39. The container does not run migrations; run them as their
# own step so several Cloud Run instances do not race:
#   docker run --rm -e DATABASE_URL=... copilot alembic upgrade head

# --- build: install the locked runtime dependencies --------------------------------
FROM python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

# --- runtime: only what the app needs to run ---------------------------------------
FROM python:3.13-slim

# PDF reports: WeasyPrint needs Pango and a font (#32); Kaleido draws the
# charts with Chromium (#33).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
        chromium \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home --home-dir /home/app app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    BROWSER_PATH=/usr/bin/chromium \
    PORT=8080

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY copilot_core ./copilot_core
COPY backend ./backend
COPY api ./api
COPY data/demo ./data/demo

USER app
EXPOSE 8080

# `exec` so the server receives SIGTERM from Cloud Run.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

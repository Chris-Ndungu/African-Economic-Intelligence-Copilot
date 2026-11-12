"""FastAPI application. Run it with `uv run uvicorn backend.main:app --reload`.

Routes stay thin: validate input, call `copilot_core`, return the result.
The JSON API lives at `/api/...` and `/health` and is described by
`api/openapi.yaml`. Server-rendered pages, HTMX partials and static files
come from `backend.web` and are kept out of the generated schema.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend import api, errors, web
from backend.settings import Settings
from copilot_core.db import create_db_engine
from copilot_core.repository import InvestigationRepository, RepositoryError
from copilot_core.schemas import Health

logger = logging.getLogger("backend.main")


def sweep_stale_runs(settings: Settings) -> int:
    """Fail runs a restart left `running` or never started; 0 without a database."""
    if settings.database_url is None:
        return 0
    engine = create_db_engine(settings.database_url, connect_args={"connect_timeout": 3})
    try:
        changed = InvestigationRepository(engine).sweep(
            running_timeout_seconds=settings.investigation_time_limit_seconds,
            pending_timeout_seconds=settings.pending_run_timeout_seconds,
        )
    except (RepositoryError, Exception) as exc:  # the API starts without its database
        logger.warning("could not sweep stale investigation runs: %s", type(exc).__name__)
        return 0
    finally:
        engine.dispose()
    if changed:
        logger.info("marked %d stale investigation runs as failed", changed)
    return changed


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.getLogger("backend").setLevel(settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sweep_stale_runs(settings)
        yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings

    errors.install(app)

    @app.get("/health", tags=["health"], operation_id="getHealth")
    def health() -> Health:
        """Liveness check. Does not touch Postgres, Gemini or BigQuery."""
        return Health(status="ok")

    app.include_router(api.router)
    app.include_router(web.router)
    app.mount("/static", StaticFiles(directory=web.STATIC_DIR), name="static")

    return app


app = create_app()

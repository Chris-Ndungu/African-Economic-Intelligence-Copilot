"""FastAPI application. Run it with `uv run uvicorn backend.main:app --reload`.

Routes stay thin: validate input, call `copilot_core`, return the result.
The JSON API lives at `/api/...` and `/health` and is described by
`api/openapi.yaml`. Server-rendered pages, HTMX partials and static files
come from `backend.web` and are kept out of the generated schema.
"""

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend import web
from backend.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.getLogger("backend").setLevel(settings.log_level.upper())

    app = FastAPI(title=settings.app_name)
    app.state.settings = settings

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness check. Does not touch Postgres, Gemini or BigQuery."""
        return {"status": "ok"}

    app.include_router(web.router)
    app.mount("/static", StaticFiles(directory=web.STATIC_DIR), name="static")

    return app


app = create_app()

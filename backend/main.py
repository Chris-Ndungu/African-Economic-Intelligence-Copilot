"""FastAPI application. Run it with `uv run uvicorn backend.main:app --reload`.

Routes stay thin: validate input, call `copilot_core`, return the result.
"""

import logging

from fastapi import FastAPI

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

    return app


app = create_app()

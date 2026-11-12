"""Services the routes depend on, created once per app on first use.

Neither service is created at startup: the app and its pages start without
data files or Postgres, and an endpoint that needs a missing service answers
``503`` instead.
"""

import threading

from fastapi import Request
from sqlalchemy import Engine

from backend.settings import Settings
from copilot_core.data import DataService, DuckDBDataService
from copilot_core.db import create_db_engine
from copilot_core.repository import DatabaseUnavailableError, InvestigationRepository

_lock = threading.Lock()


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_data_service(request: Request) -> DataService:
    """The app's data service. Raises ``DataUnavailableError`` if files are missing."""
    state = request.app.state
    with _lock:
        if getattr(state, "data_service", None) is None:
            state.data_service = DuckDBDataService(get_settings(request).data_dir)
        service: DataService = state.data_service
    return service


def get_repository(request: Request) -> InvestigationRepository:
    """The investigation repository. Raises ``DatabaseUnavailableError`` without a database."""
    state = request.app.state
    with _lock:
        if getattr(state, "repository", None) is None:
            url = get_settings(request).database_url
            if url is None:
                raise DatabaseUnavailableError("DATABASE_URL is not set")
            engine: Engine = create_db_engine(
                url, pool_pre_ping=True, connect_args={"connect_timeout": 3}
            )
            state.repository = InvestigationRepository(engine)
        repository: InvestigationRepository = state.repository
    return repository

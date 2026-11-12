"""Services the routes depend on, created once per app on first use.

No service is created at startup: the app and its pages start without
data files, Postgres or a Gemini key, and an endpoint that needs a missing
service answers ``503`` instead. Tests set ``app.state.llm`` to a
``StubLLMClient``; without it, building the Gemini client during a test run
fails, so no test can reach the real API.
"""

import threading

from fastapi import Request
from sqlalchemy import Engine

from backend.settings import Settings
from copilot_core.data import DataService, DuckDBDataService
from copilot_core.db import create_db_engine
from copilot_core.llm import GeminiClient, LLMClient
from copilot_core.repository import DatabaseUnavailableError, InvestigationRepository
from copilot_core.runs import InvestigationService, RunSettings

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


def get_llm(request: Request) -> LLMClient:
    """The app's language model client; Gemini unless a test set a stub."""
    state = request.app.state
    with _lock:
        if getattr(state, "llm", None) is None:
            state.llm = GeminiClient(get_settings(request).gemini_config())
        llm: LLMClient = state.llm
    return llm


def run_settings(settings: Settings) -> RunSettings:
    return RunSettings(
        step_limit=settings.tool_step_limit,
        max_points=settings.max_tool_result_points,
        time_limit_seconds=settings.investigation_time_limit_seconds,
        pending_timeout_seconds=settings.pending_run_timeout_seconds,
        ping_seconds=settings.stream_ping_seconds,
    )


def get_investigation_service(request: Request) -> InvestigationService:
    """Runs investigations. The data service and Gemini are built when a run starts."""
    return InvestigationService(
        repository=get_repository(request),
        data=lambda: get_data_service(request),
        llm=lambda: get_llm(request),
        data_mode="demo",
        settings=run_settings(get_settings(request)),
    )

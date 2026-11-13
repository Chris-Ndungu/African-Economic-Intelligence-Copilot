"""Services the routes depend on, created once per app on first use.

No service is created at startup: the app and its pages start without
data files, Postgres or a Gemini key, and an endpoint that needs a missing
service answers ``503`` instead. Tests set ``app.state.llm`` to a
``StubLLMClient``; without it, building the Gemini client during a test run
fails, so no test can reach the real API.
"""

import re
import threading

from fastapi import Request
from sqlalchemy import Engine

from backend.client_ip import client_ip
from backend.settings import Settings
from backend.visitor import owner_of
from copilot_core.data import DataService, DuckDBDataService
from copilot_core.db import create_db_engine
from copilot_core.llm import GeminiClient, LLMClient, StubLLMClient
from copilot_core.meta import get_meta
from copilot_core.rate_limit import (
    MemoryAttemptStore,
    PostgresAttemptStore,
    RateLimits,
    RunLimiter,
    client_key,
)
from copilot_core.repository import DatabaseUnavailableError, InvestigationRepository
from copilot_core.runs import InvestigationService, RunSettings
from copilot_core.schemas import Meta

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
        base: InvestigationRepository = state.repository
    # Every request sees only its own visitor's investigations.
    return base.for_owner(
        owner_of(request.scope), get_settings(request).anonymous_investigation_limit
    )


def get_run_limiter(request: Request) -> RunLimiter:
    """The run limiter. Counts live in Postgres so they hold across instances.

    Without a database engine (tests with an in-memory repository) counts are
    kept in this process; a deployment always has the database.
    """
    state = request.app.state
    settings = get_settings(request)
    with _lock:
        if getattr(state, "run_limiter", None) is None:
            engine = getattr(get_repository(request), "engine", None)
            store = PostgresAttemptStore(engine) if engine is not None else MemoryAttemptStore()
            state.run_limiter = RunLimiter(
                store,
                RateLimits(
                    per_client_limit=settings.runs_per_ip_per_hour,
                    authenticated_limit=settings.authenticated_runs_per_hour,
                    daily_limit=settings.runs_per_day_total,
                ),
            )
        limiter: RunLimiter = state.run_limiter
    return limiter


def enforce_run_limit(request: Request) -> None:
    """Count one run for this client or raise ``RateLimitedError``; Gemini is not called yet.

    Every path that starts a run calls this: the JSON endpoints and the HTML
    run and retry routes. Reading, listing and exporting never do.
    """
    settings = get_settings(request)
    salt = settings.rate_limit_salt.get_secret_value() if settings.rate_limit_salt else ""
    key = client_key(client_ip(request, settings.trusted_proxy_hops), salt)
    get_run_limiter(request).check(key, "anonymous")


def get_llm(request: Request) -> LLMClient:
    """The app's language model client.

    A client set on ``app.state.llm`` wins. With ``LLM_CLIENT=stub`` each call
    returns a new stub for the scenario in the ``X-Stub-Scenario`` header, or
    the configured default, so one request cannot affect another. With any
    other client the header is ignored.
    """
    state = request.app.state
    settings = get_settings(request)
    if getattr(state, "llm", None) is None and settings.llm_client == "stub":
        scenario = request.headers.get("x-stub-scenario", "")
        if not re.fullmatch(r"[A-Za-z0-9_]+", scenario):  # never build a file path from it
            scenario = settings.stub_scenario
        return StubLLMClient(scenario)
    with _lock:
        if getattr(state, "llm", None) is None:
            state.llm = GeminiClient(get_settings(request).gemini_config())
        llm: LLMClient = state.llm
    return llm


def gemini_configured(request: Request) -> bool:
    """Whether runs can reach Gemini: a key is set, or a client was provided."""
    state = request.app.state
    settings = get_settings(request)
    return (
        settings.gemini_api_key is not None
        or settings.llm_client == "stub"
        or getattr(state, "llm", None) is not None
    )


def get_app_meta(request: Request) -> Meta:
    """The data mode, snapshot date and Gemini state; one answer for pages and `/api/meta`."""
    settings = get_settings(request)
    return get_meta(
        settings.data_dir,
        gemini_configured(request),
        data_mode="demo",  # Live mode on BigQuery arrives with #49.
        snapshot_date=settings.demo_snapshot_date,
    )


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

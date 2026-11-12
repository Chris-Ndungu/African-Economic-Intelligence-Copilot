"""Application settings, read from environment variables.

Every setting has a default that works for local development, so the app
starts without a `.env` file. Variables use the `COPILOT_` prefix, for
example `COPILOT_LOG_LEVEL=debug`. The Postgres connection string is the
exception: it is read from `DATABASE_URL`, the name hosting providers and
tools use. An invalid value raises a `pydantic.ValidationError` that names
the setting, which stops startup.
"""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from copilot_core.data import DEFAULT_DATA_DIR
from copilot_core.llm.gemini import DEFAULT_MODEL, GeminiConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "African Economic Intelligence Copilot"
    """Product name shown in the page header and on the API docs page."""

    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    """Log level for the application loggers."""

    data_dir: Path = DEFAULT_DATA_DIR
    """Folder of the demo Parquet files read by the data service."""

    demo_snapshot_date: date | None = None
    """Date of the demo snapshot; when unset it is read from `data/demo/README.md`."""

    database_url: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")
    """Postgres connection string, or `None` when no database is configured.

    Kept secret so the password never appears in a repr, log or error.
    """

    gemini_api_key: SecretStr | None = None
    """Gemini API key, or `None`: the app still starts, and runs fail as not configured."""

    gemini_model: str = DEFAULT_MODEL
    """The Gemini model; the default is the current stable Flash model."""

    gemini_timeout_seconds: float = Field(default=30.0, gt=0)
    """Longest wait for one Gemini call."""

    gemini_max_retries: int = Field(default=3, ge=0)
    """Retries of a rate-limited (429) or server-error (5xx) Gemini call."""

    gemini_max_output_tokens: int = Field(default=4096, gt=0)
    """Output token limit of one Gemini call."""

    tool_step_limit: int = Field(default=8, ge=1)
    """Tool rounds a run may take before it stops with `step_limit_reached`."""

    max_tool_result_points: int = Field(default=500, ge=1)
    """Data points one tool call may load before it is asked to narrow the request."""

    investigation_time_limit_seconds: float = Field(default=90.0, gt=0)
    """Longest a whole run may take before it is saved as `failed` with code `timeout`."""

    pending_run_timeout_seconds: float = Field(default=300.0, gt=0)
    """How long a `pending` run waits for its stream before it fails as `not_started`."""

    stream_ping_seconds: float = Field(default=15.0, gt=0)
    """Longest gap between server-sent events or `: ping` comments while a run streams."""

    environment: Literal["local", "test", "prod"] = "local"
    """Where the app runs (`COPILOT_ENVIRONMENT`); `prod` refuses the stub client."""

    llm_client: Literal["gemini", "stub"] = Field(default="gemini", validation_alias="LLM_CLIENT")
    """`gemini` calls the real API; `stub` replays recordings and is for end-to-end tests."""

    stub_scenario: str = Field(
        default="run_success",
        pattern=r"^[A-Za-z0-9_]+$",
        validation_alias="LLM_STUB_SCENARIO",
    )
    """Recording in `tests/fixtures/llm/` the stub replays when a request names none."""

    @model_validator(mode="after")
    def _no_stub_in_production(self) -> "Settings":
        if self.llm_client == "stub" and self.environment == "prod":
            raise ValueError(
                "LLM_CLIENT=stub is not allowed when COPILOT_ENVIRONMENT=prod: the stub replays "
                "recorded answers instead of calling Gemini, so production would show fake results"
            )
        return self

    @field_validator("database_url", "gemini_api_key", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    def gemini_config(self) -> GeminiConfig:
        return GeminiConfig(
            api_key=self.gemini_api_key,
            model=self.gemini_model,
            timeout_seconds=self.gemini_timeout_seconds,
            max_retries=self.gemini_max_retries,
            max_output_tokens=self.gemini_max_output_tokens,
        )

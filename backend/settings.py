"""Application settings, read from environment variables.

Every setting has a default that works for local development, so the app
starts without a `.env` file. Variables use the `COPILOT_` prefix, for
example `COPILOT_LOG_LEVEL=debug`. An invalid value raises a
`pydantic.ValidationError` that names the setting, which stops startup.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "African Economic Intelligence Copilot"
    """Title shown on the API docs page."""

    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    """Log level for the application loggers."""

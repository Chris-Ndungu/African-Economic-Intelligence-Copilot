"""Application settings, read from environment variables.

Every setting has a default that works for local development, so the app
starts without a `.env` file. Variables use the `COPILOT_` prefix, for
example `COPILOT_LOG_LEVEL=debug`. The Postgres connection string is the
exception: it is read from `DATABASE_URL`, the name hosting providers and
tools use. An invalid value raises a `pydantic.ValidationError` that names
the setting, which stops startup.
"""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
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

    database_url: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")
    """Postgres connection string, or `None` when no database is configured.

    Kept secret so the password never appears in a repr, log or error.
    """

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

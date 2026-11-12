import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app, create_app
from backend.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    # Isolate settings from the developer's shell and any local .env file.
    for name in list(os.environ):
        if name.startswith("COPILOT_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def test_health_returns_ok():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_needs_no_external_services():
    # No database, Gemini or BigQuery settings exist or are configured.
    response = TestClient(create_app(Settings())).get("/health")

    assert response.status_code == 200


def test_docs_list_health():
    client = TestClient(app)

    assert client.get("/docs").status_code == 200
    assert "/health" in client.get("/openapi.json").json()["paths"]


def test_settings_have_defaults_without_env_file():
    settings = Settings()

    assert settings.log_level == "info"
    assert settings.app_name == "African Economic Intelligence Copilot"


def test_environment_variable_overrides_default(monkeypatch):
    monkeypatch.setenv("COPILOT_LOG_LEVEL", "debug")
    monkeypatch.setenv("COPILOT_APP_NAME", "Test Copilot")

    settings = Settings()

    assert settings.log_level == "debug"
    assert create_app(settings).title == "Test Copilot"


def test_invalid_setting_names_the_setting(monkeypatch):
    monkeypatch.setenv("COPILOT_LOG_LEVEL", "loud")

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert "log_level" in str(excinfo.value)


def test_invalid_setting_stops_startup():
    env = {**os.environ, "COPILOT_LOG_LEVEL": "loud"}
    result = subprocess.run(
        [sys.executable, "-c", "import backend.main"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "log_level" in result.stderr


def test_env_example_lists_every_setting():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    for name, field in Settings.model_fields.items():
        # A field with an alias, such as DATABASE_URL, is read without the prefix.
        variable = field.validation_alias or f"COPILOT_{name.upper()}"
        assert f"{variable}=" in example, variable


def test_env_file_is_ignored_and_example_is_not():
    def ignored(path):
        return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0

    assert ignored(".env")
    assert not ignored(".env.example")

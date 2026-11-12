"""The `LLM_CLIENT` setting and the `X-Stub-Scenario` header (#34, #35).

These run without a browser, Docker or Postgres.
"""

import os

import pydantic
import pytest
from fastapi.testclient import TestClient
from memory_repository import MemoryRepository

from backend.main import create_app
from backend.settings import Settings

SELECTION = {"countries": ["KEN"], "indicator": "PCPIPCH", "start": "2015", "end": "2023"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name in (
            "DATABASE_URL",
            "LLM_CLIENT",
            "LLM_STUB_SCENARIO",
        ):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def make_client(**settings):
    app = create_app(Settings(**settings))
    app.state.repository = MemoryRepository()
    return TestClient(app)


def run(client, headers=None):
    """The response of a run: `200` with the investigation, or the error body."""
    return client.post("/api/investigations/run", json={"selection": SELECTION}, headers=headers)


def test_the_default_client_is_gemini():
    assert Settings().llm_client == "gemini"


def test_the_environment_variable_chooses_the_stub(monkeypatch):
    monkeypatch.setenv("LLM_CLIENT", "stub")
    assert Settings().llm_client == "stub"


@pytest.mark.parametrize("environment", ["local", "test"])
def test_the_stub_is_allowed_outside_production(environment):
    assert Settings(llm_client="stub", environment=environment).llm_client == "stub"


def test_the_app_refuses_to_start_with_the_stub_in_production_and_says_why():
    with pytest.raises(pydantic.ValidationError, match="LLM_CLIENT=stub is not allowed"):
        create_app(Settings(llm_client="stub", environment="prod"))


def test_with_the_stub_a_run_succeeds_without_a_gemini_key():
    with make_client(llm_client="stub") as client:
        assert client.get("/api/meta").json()["gemini_configured"] is True
        response = run(client)
    assert response.status_code == 200
    assert response.json()["result"]["interpretation"]["findings"]


def test_the_scenario_header_picks_the_recording_for_that_request():
    with make_client(llm_client="stub") as client:
        down = run(client, {"X-Stub-Scenario": "run_gemini_down"})
        after = run(client)
    assert down.status_code == 503
    assert down.json()["service"] == "gemini"
    assert after.status_code == 200


def test_the_configured_scenario_is_used_without_a_header():
    with make_client(llm_client="stub", stub_scenario="run_gemini_down") as client:
        assert run(client).status_code == 503


def test_a_header_that_is_not_a_scenario_name_cannot_reach_another_file():
    with make_client(llm_client="stub") as client:
        response = run(client, {"X-Stub-Scenario": "../../pyproject"})
    assert response.status_code == 200


def test_the_header_has_no_effect_when_the_client_is_gemini():
    # No key is set, so the run cannot succeed (in a test run the real client is blocked
    # outright); a stub would have succeeded.
    with make_client(llm_client="gemini") as client:
        response = run(client, {"X-Stub-Scenario": "run_success"})
    assert response.status_code != 200

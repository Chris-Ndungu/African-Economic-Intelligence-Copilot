"""The Gemini client wrapper and its stub (#24).

``GeminiClient`` is tested through a fake transport that stands in for the
SDK call, so no test needs the network or an API key. ``StubLLMClient``
replays the recordings in ``tests/fixtures/llm/``.
"""

import asyncio
import json
import subprocess
import sys

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import SecretStr

from backend.main import create_app
from backend.settings import Settings
from copilot_core.llm import (
    GeminiClient,
    GeminiConfig,
    LLMBlocked,
    LLMError,
    LLMNotConfigured,
    LLMRequestError,
    LLMTimeout,
    LLMTruncated,
    LLMUnavailable,
    Message,
    StubLLMClient,
    StubRecordingError,
    ToolDeclaration,
)
from copilot_core.llm.gemini import LiveGeminiInTestsError
from copilot_core.llm.stub import DEFAULT_RECORDINGS

KEY = "AIzaTEST-not-a-real-key-123456"
HELLO = [Message(role="user", text="Hello")]


def reply(text="Hi", finish=types.FinishReason.STOP, parts=None, block=None, thoughts=None):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=parts or [types.Part(text=text)]),
                finish_reason=finish,
            )
        ],
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=block)
        if block
        else None,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, candidates_token_count=3, thoughts_token_count=thoughts
        ),
        model_version="gemini-3.6-flash",
    )


def api_error(code, message="failed"):
    body = {"error": {"code": code, "message": message, "status": "ERROR"}}
    cls = genai_errors.ServerError if code >= 500 else genai_errors.ClientError
    return cls(code, body)


class FakeTransport:
    """Returns or raises the given outcomes in order and records each call."""

    def __init__(self, *outcomes, delay=0.0):
        self.outcomes = list(outcomes)
        self.calls = []
        self.delay = delay

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.delay:
            await asyncio.sleep(self.delay)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client(*outcomes, key=KEY, delay=0.0, **config):
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    transport = FakeTransport(*outcomes, delay=delay)
    gemini = GeminiClient(
        GeminiConfig(api_key=SecretStr(key) if key else None, **config),
        transport=transport,
        sleep=sleep,
    )
    return gemini, transport, sleeps


def generate(llm, messages=HELLO, **kwargs):
    return asyncio.run(llm.generate(messages, **kwargs))


# --- GeminiClient ----------------------------------------------------------------


def test_a_reply_returns_text_token_usage_and_latency():
    llm, transport, _ = client(reply("Hello there", thoughts=2))
    response = generate(llm)
    assert response.text == "Hello there"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5  # reply tokens plus thinking tokens
    assert response.usage.latency_ms >= 0
    assert response.model == "gemini-3.6-flash"
    assert transport.calls[0]["model"] == "gemini-3.6-flash"


def test_tool_calls_are_returned_and_declarations_sent():
    part = types.Part(
        function_call=types.FunctionCall(name="analyze_trend", args={"country": "KEN"}, id="c1")
    )
    llm, transport, _ = client(reply(parts=[part]))
    tool = ToolDeclaration(
        name="analyze_trend",
        description="Trend",
        parameters={"type": "object", "properties": {"country": {"type": "string"}}},
    )
    response = generate(llm, tools=[tool])
    assert [(c.name, c.args, c.id) for c in response.tool_calls] == [
        ("analyze_trend", {"country": "KEN"}, "c1")
    ]
    sent = transport.calls[0]["config"].tools[0].function_declarations[0]
    assert sent.name == "analyze_trend"


def test_a_response_schema_asks_for_json():
    from copilot_core.interpretation import Interpretation

    llm, transport, _ = client(reply("{}"))
    generate(llm, response_schema=Interpretation)
    config = transport.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["title"] == "Interpretation"


def test_settings_set_the_model_and_output_token_limit():
    llm, transport, _ = client(reply(), model="gemini-other", max_output_tokens=123)
    generate(llm)
    assert transport.calls[0]["model"] == "gemini-other"
    assert transport.calls[0]["config"].max_output_tokens == 123


@pytest.mark.parametrize("code", [429, 500, 503])
def test_rate_limit_and_server_errors_are_retried_with_exponential_backoff(code):
    llm, transport, sleeps = client(api_error(code), api_error(code), reply("ok"), max_retries=3)
    assert generate(llm).text == "ok"
    assert len(transport.calls) == 3
    assert sleeps == [1.0, 2.0]


def test_retries_stop_at_the_limit_with_llm_unavailable():
    errors = [api_error(503) for _ in range(4)]
    llm, transport, sleeps = client(*errors, max_retries=3, backoff_seconds=0.5)
    with pytest.raises(LLMUnavailable, match="503"):
        generate(llm)
    assert len(transport.calls) == 4  # the first call and three retries
    assert sleeps == [0.5, 1.0, 2.0]


@pytest.mark.parametrize("error", [httpx2.ConnectError("refused"), httpx.ConnectError("refused")])
def test_network_errors_are_retried(error):
    llm, transport, sleeps = client(error, reply("ok"))
    assert generate(llm).text == "ok"
    assert sleeps == [1.0]


def test_the_app_imports_without_httpx():
    """The production image has no dev dependencies, so no httpx (a crash on Render)."""
    code = (
        "import sys; sys.modules['httpx'] = None; "
        "import httpx2, backend.main, copilot_core.llm.gemini as g; "
        "assert g._NETWORK_ERRORS == (httpx2.HTTPError,)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_other_client_errors_are_not_retried(code):
    llm, transport, sleeps = client(api_error(code), reply("unused"))
    with pytest.raises(LLMRequestError, match=str(code)):
        generate(llm)
    assert len(transport.calls) == 1
    assert sleeps == []


def test_a_slow_call_raises_llm_timeout():
    llm, transport, _ = client(reply(), delay=1.0, timeout_seconds=0.05)
    with pytest.raises(LLMTimeout, match="0.05 seconds"):
        generate(llm)


def test_a_blocked_prompt_raises_llm_blocked():
    llm, *_ = client(reply(block=types.BlockedReason.SAFETY))
    with pytest.raises(LLMBlocked, match="SAFETY"):
        generate(llm)


@pytest.mark.parametrize(
    "reason", [types.FinishReason.SAFETY, types.FinishReason.PROHIBITED_CONTENT]
)
def test_a_blocked_reply_raises_llm_blocked(reason):
    llm, *_ = client(reply(finish=reason))
    with pytest.raises(LLMBlocked):
        generate(llm)


def test_a_reply_cut_off_by_the_token_limit_raises_llm_truncated():
    llm, *_ = client(reply(finish=types.FinishReason.MAX_TOKENS), max_output_tokens=50)
    with pytest.raises(LLMTruncated, match="50 output token limit"):
        generate(llm)


def test_without_an_api_key_the_first_call_raises_llm_not_configured():
    llm, transport, _ = client(reply(), key=None)
    with pytest.raises(LLMNotConfigured, match="COPILOT_GEMINI_API_KEY"):
        generate(llm)
    assert transport.calls == []


def test_every_error_shares_one_base_class():
    for error in (LLMNotConfigured, LLMTimeout, LLMUnavailable, LLMRequestError, LLMBlocked):
        assert issubclass(error, LLMError)
    assert issubclass(LLMTruncated, LLMError)


def test_the_api_starts_without_an_api_key():
    with TestClient(create_app(Settings(gemini_api_key=None))) as test_client:
        assert test_client.get("/health").status_code == 200


def test_the_default_model_is_named_in_env_example():
    from copilot_core.llm import DEFAULT_MODEL
    from tests.conftest import ROOT

    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert f"COPILOT_GEMINI_MODEL={DEFAULT_MODEL}" in example
    for name in ("API_KEY", "TIMEOUT_SECONDS", "MAX_RETRIES", "MAX_OUTPUT_TOKENS"):
        assert f"COPILOT_GEMINI_{name}" in example
    assert Settings().gemini_model == DEFAULT_MODEL


# --- The API key never leaks ------------------------------------------------------


def test_the_key_is_not_in_the_repr_of_the_client_or_settings():
    llm, *_ = client(reply())
    settings = Settings(gemini_api_key=KEY)
    assert KEY not in repr(llm)
    assert KEY not in repr(settings)
    assert KEY not in str(settings.gemini_config())


def test_the_key_is_redacted_from_error_messages():
    llm, *_ = client(api_error(400, f"API key {KEY} not valid"))
    with pytest.raises(LLMRequestError) as caught:
        generate(llm)
    assert KEY not in str(caught.value)
    assert "[redacted]" in str(caught.value)


def test_the_key_is_redacted_from_network_errors():
    errors = [httpx.ConnectError(f"https://example/?key={KEY}") for _ in range(2)]
    llm, *_ = client(*errors, max_retries=1)
    with pytest.raises(LLMUnavailable) as caught:
        generate(llm)
    assert KEY not in str(caught.value)


# --- No test reaches the real API -------------------------------------------------


def test_building_a_real_client_in_a_test_run_fails(monkeypatch):
    monkeypatch.delenv("RUN_LIVE_GEMINI", raising=False)
    with pytest.raises(LiveGeminiInTestsError, match="StubLLMClient"):
        GeminiClient(GeminiConfig(api_key=SecretStr(KEY)))


def test_the_app_cannot_reach_gemini_from_a_test_without_a_stub(monkeypatch):
    from backend.dependencies import get_llm

    monkeypatch.delenv("RUN_LIVE_GEMINI", raising=False)

    class FakeRequest:
        app = create_app(Settings(gemini_api_key=KEY))

    with pytest.raises(LiveGeminiInTestsError):
        get_llm(FakeRequest())  # type: ignore[arg-type]


# --- StubLLMClient ----------------------------------------------------------------


def test_the_stub_replays_a_recording_and_records_calls():
    stub = StubLLMClient("text_reply")
    response = generate(stub, system="Be brief.")
    assert response.text == "Hello from the stub."
    assert (response.usage.input_tokens, response.usage.output_tokens) == (12, 5)
    assert response.usage.latency_ms == 42.0
    assert stub.calls[0].system == "Be brief."
    assert stub.calls[0].messages == HELLO


@pytest.mark.parametrize(
    ("scenario", "error"),
    [
        ("error_not_configured", LLMNotConfigured),
        ("error_timeout", LLMTimeout),
        ("error_unavailable", LLMUnavailable),
        ("error_request", LLMRequestError),
        ("error_blocked", LLMBlocked),
        ("error_truncated", LLMTruncated),
    ],
)
def test_each_failure_has_a_stub_scenario(scenario, error):
    with pytest.raises(error):
        generate(StubLLMClient(scenario))


def test_a_missing_recording_fails_naming_the_file():
    with pytest.raises(StubRecordingError, match=r"no_such_scenario\.json"):
        StubLLMClient("no_such_scenario")


def test_a_recording_that_runs_out_fails_the_test():
    stub = StubLLMClient("text_reply")
    generate(stub)
    with pytest.raises(StubRecordingError, match="call 2 has none"):
        generate(stub)


def test_every_recording_is_valid_json_with_responses():
    for path in DEFAULT_RECORDINGS.glob("*.json"):
        recording = json.loads(path.read_text(encoding="utf-8"))
        assert recording["description"], path
        assert recording["responses"], path


def test_the_sdk_client_outlives_construction(monkeypatch):
    """The SDK closes its HTTP client when its Client is garbage-collected, so the
    GeminiClient must hold the Client, not just `client.aio.models` (a real run on
    Render failed with "client has been closed")."""
    import gc

    monkeypatch.setenv("RUN_LIVE_GEMINI", "1")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)  # a stale path breaks the TLS context
    gemini = GeminiClient(GeminiConfig(api_key=SecretStr(KEY)))
    gc.collect()
    assert gemini._sdk is not None
    assert not gemini._sdk._api_client._async_httpx_client.is_closed

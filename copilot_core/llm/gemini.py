"""The one place that uses the ``google-genai`` SDK.

:class:`GeminiClient` implements :class:`~copilot_core.llm.types.LLMClient`:
it applies the timeout, retries rate-limit and server errors with
exponential backoff, maps every failure to a typed
:class:`~copilot_core.llm.errors.LLMError` and reports token usage and
latency for each call.

The API key is a ``SecretStr``. It never appears in a log line, an error
message or the client's ``repr``: messages from the SDK are scrubbed of it
before they are raised.

Under pytest, building a client that would reach the real API fails unless
``RUN_LIVE_GEMINI=1`` is set, so a test that forgot to use
:class:`~copilot_core.llm.stub.StubLLMClient` cannot call Gemini.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx2
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, SecretStr

from copilot_core.llm.errors import (
    LLMBlocked,
    LLMError,
    LLMNotConfigured,
    LLMRequestError,
    LLMTimeout,
    LLMTruncated,
    LLMUnavailable,
)
from copilot_core.llm.types import LLMResponse, Message, ToolCall, ToolDeclaration, Usage

# google-genai sends requests with httpx2, a runtime dependency of the SDK. It
# also accepts httpx when that is installed (only the dev group has it), and
# the two packages' errors are unrelated classes, so catch both when present.
_NETWORK_ERRORS: tuple[type[Exception], ...] = (httpx2.HTTPError,)
try:
    import httpx
except ImportError:  # the production image has no httpx
    pass
else:
    _NETWORK_ERRORS += (httpx.HTTPError,)

__all__ = [
    "DEFAULT_MODEL",
    "GeminiClient",
    "GeminiConfig",
    "LiveGeminiInTestsError",
    "live_gemini_allowed",
]

logger = logging.getLogger("copilot_core.llm")

DEFAULT_MODEL = "gemini-2.5-flash"
"""Gemini 2.5 Flash: quick, with free-tier quota for tool calling."""

BLOCKED = {
    types.FinishReason.SAFETY,
    types.FinishReason.RECITATION,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.SPII,
    types.FinishReason.IMAGE_SAFETY,
    types.FinishReason.IMAGE_PROHIBITED_CONTENT,
}


class LiveGeminiInTestsError(RuntimeError):
    """A test tried to build a client that reaches the real Gemini API."""


def live_gemini_allowed() -> bool:
    """False under pytest unless ``RUN_LIVE_GEMINI=1``; always true outside tests."""
    return "pytest" not in sys.modules or os.environ.get("RUN_LIVE_GEMINI") == "1"


ThinkingLevel = Literal["minimal", "low", "medium", "high"]

THINKING_BUDGETS: dict[ThinkingLevel, int] = {
    "minimal": 0,
    "low": 1024,
    "medium": 8192,
    "high": -1,
}
"""Gemini 2.5 models take a token budget instead of a level; -1 lets the model decide."""


def thinking_config(model: str, level: ThinkingLevel) -> types.ThinkingConfig:
    """The thinking setting ``model`` accepts: a budget for Gemini 2.x, a level for later ones.

    Gemini 2.5 rejects ``thinking_level`` with a 400, and Gemini 3 prefers it to a budget.
    """
    name = model.removeprefix("models/")
    if name.startswith(("gemini-2.", "gemini-1.")):
        return types.ThinkingConfig(thinking_budget=THINKING_BUDGETS[level])
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel(level.upper()))


TIMEOUT_RETRIES = 1
"""A timed-out call is retried this many times, within ``max_retries``."""


@dataclass(frozen=True)
class GeminiConfig:
    """Settings for :class:`GeminiClient`, filled from the app settings."""

    api_key: SecretStr | None = None
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 60.0
    max_retries: int = 3
    max_output_tokens: int = 4096
    thinking_level: ThinkingLevel = "low"
    """How much Gemini reasons before answering. Gemini 3 defaults to high, which
    can take longer than the timeout; choosing tools and describing numbers that
    Python computed needs little reasoning."""
    backoff_seconds: float = 1.0
    """The first retry waits this long; each later one waits twice as long."""


class Transport(Protocol):
    """The SDK call :class:`GeminiClient` makes; tests pass a fake."""

    def generate_content(
        self, *, model: str, contents: Any, config: Any
    ) -> Awaitable[types.GenerateContentResponse]: ...


@dataclass
class GeminiClient:
    """Gemini through ``google-genai``, with timeouts, retries and typed errors."""

    config: GeminiConfig
    transport: Transport | None = field(default=None, repr=False)
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep, repr=False)
    _sdk: genai.Client | None = field(default=None, init=False, repr=False)
    """Keeps the SDK client alive: it closes its HTTP client when garbage-collected."""

    def __post_init__(self) -> None:
        if self.transport is not None:
            return
        if not live_gemini_allowed():
            raise LiveGeminiInTestsError(
                "GeminiClient would call the real Gemini API during a test run. Use "
                "StubLLMClient, or set RUN_LIVE_GEMINI=1 for the live tests."
            )
        if self.config.api_key is not None:
            self._sdk = genai.Client(api_key=self.config.api_key.get_secret_value())
            self.transport = self._sdk.aio.models

    def __repr__(self) -> str:
        return f"GeminiClient(model={self.config.model!r}, configured={self.configured})"

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def configured(self) -> bool:
        return self.config.api_key is not None

    def _redact(self, text: str) -> str:
        key = self.config.api_key.get_secret_value() if self.config.api_key else ""
        return text.replace(key, "[redacted]") if key else text

    async def generate(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        tools: list[ToolDeclaration] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        if self.config.api_key is None or self.transport is None:
            raise LLMNotConfigured("Gemini is not configured: set COPILOT_GEMINI_API_KEY")
        contents = [_content(m) for m in messages]
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self.config.max_output_tokens,
            thinking_config=thinking_config(self.config.model, self.config.thinking_level),
            tools=[types.Tool(function_declarations=[_declaration(t) for t in tools])]
            if tools
            else None,
            response_mime_type="application/json" if response_schema else None,
            response_json_schema=response_schema.model_json_schema() if response_schema else None,
        )
        attempt = 0
        timeouts = 0
        error: LLMError
        while True:
            started = time.perf_counter()
            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    response = await self.transport.generate_content(
                        model=self.config.model, contents=contents, config=config
                    )
            except TimeoutError:
                error = LLMTimeout(
                    f"Gemini did not answer within {self.config.timeout_seconds:g} seconds"
                )
                timeouts += 1
                if timeouts > TIMEOUT_RETRIES or attempt >= self.config.max_retries:
                    raise error from None
            except genai_errors.APIError as exc:
                error = self._map_api_error(exc)
                if not isinstance(error, LLMUnavailable) or attempt >= self.config.max_retries:
                    raise error from None
            except _NETWORK_ERRORS as exc:
                error = LLMUnavailable(self._redact(f"Gemini could not be reached: {exc}"))
                if attempt >= self.config.max_retries:
                    raise error from None
            else:
                latency = (time.perf_counter() - started) * 1000
                return self._parse(response, latency)
            delay = self.config.backoff_seconds * 2**attempt
            attempt += 1
            logger.warning(
                "Gemini call failed (%s); retry %d of %d in %.1fs",
                error,
                attempt,
                self.config.max_retries,
                delay,
            )
            await self.sleep(delay)

    def _map_api_error(self, exc: genai_errors.APIError) -> LLMError:
        message = self._redact(f"Gemini returned {exc.code}: {exc.message or exc.status or ''}")
        if exc.code == 429 or exc.code >= 500:
            return LLMUnavailable(message)
        return LLMRequestError(message)

    def _parse(self, response: types.GenerateContentResponse, latency_ms: float) -> LLMResponse:
        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason is not None:
            raise LLMBlocked(f"Gemini blocked the prompt: {feedback.block_reason.value}")
        if not response.candidates:
            raise LLMUnavailable("Gemini returned no reply")
        candidate = response.candidates[0]
        if candidate.finish_reason in BLOCKED:
            raise LLMBlocked(f"Gemini blocked the reply: {candidate.finish_reason.value}")
        if candidate.finish_reason == types.FinishReason.MAX_TOKENS:
            raise LLMTruncated(
                f"Gemini's reply hit the {self.config.max_output_tokens} output token limit"
            )
        parts = candidate.content.parts if candidate.content and candidate.content.parts else []
        texts = [p.text for p in parts if p.text and not p.thought]
        calls = tuple(
            ToolCall(
                name=p.function_call.name or "",
                args=p.function_call.args or {},
                id=p.function_call.id,
            )
            for p in parts
            if p.function_call is not None
        )
        meta = response.usage_metadata
        usage = Usage(
            input_tokens=(meta.prompt_token_count or 0) if meta else 0,
            output_tokens=((meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0))
            if meta
            else 0,
            latency_ms=latency_ms,
        )
        return LLMResponse(
            text="".join(texts) or None,
            tool_calls=calls,
            usage=usage,
            model=response.model_version or self.config.model,
            raw=candidate.content,
        )


def _declaration(tool: ToolDeclaration) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=tool.name, description=tool.description, parameters_json_schema=tool.parameters
    )


def _content(message: Message) -> types.Content:
    if message.role == "model" and isinstance(message.raw, types.Content):
        return message.raw
    parts: list[types.Part] = []
    if message.text:
        parts.append(types.Part(text=message.text))
    for call in message.tool_calls:
        parts.append(
            types.Part(function_call=types.FunctionCall(name=call.name, args=call.args, id=call.id))
        )
    for reply in message.tool_responses:
        parts.append(
            types.Part(
                function_response=types.FunctionResponse(
                    name=reply.name, response=reply.response, id=reply.id
                )
            )
        )
    return types.Content(role="model" if message.role == "model" else "user", parts=parts)

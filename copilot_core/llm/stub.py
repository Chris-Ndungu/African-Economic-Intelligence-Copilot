"""A language model that replays recorded responses, for tests and demos.

Each scenario is a JSON file, ``<scenario>.json``, in the recordings folder
(``tests/fixtures/llm/`` by default)::

    {
      "description": "What the scenario shows",
      "responses": [
        {"tool_calls": [{"name": "analyze_trend", "args": {...}}]},
        {"text": "Done."},
        {"json": {...}},
        {"error": "LLMUnavailable", "message": "Gemini returned 503"},
        {"delay_seconds": 0.5, "text": "A slow reply"}
      ]
    }

Each call to :meth:`StubLLMClient.generate` returns the next response in
order: ``text`` as text, ``json`` serialized as the text of a structured
reply, ``tool_calls`` as tool calls, and ``error`` raised as that
:class:`~copilot_core.llm.errors.LLMError` subclass. Calls are recorded in
``calls`` so tests can check what was sent.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from copilot_core.llm import errors
from copilot_core.llm.types import LLMResponse, Message, ToolCall, ToolDeclaration, Usage

__all__ = ["DEFAULT_RECORDINGS", "RecordedCall", "StubLLMClient", "StubRecordingError"]

DEFAULT_RECORDINGS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"

ERRORS: dict[str, type[errors.LLMError]] = {
    name: getattr(errors, name) for name in errors.__all__ if name != "LLMError"
}


class StubRecordingError(AssertionError):
    """The scenario has no recording, or its recording ran out of responses."""


@dataclass(frozen=True)
class RecordedCall:
    messages: list[Message]
    system: str | None
    tools: list[ToolDeclaration] | None
    response_schema: type[BaseModel] | None


@dataclass
class StubLLMClient:
    """Replays ``<recordings>/<scenario>.json``; never touches the network."""

    scenario: str
    recordings: Path = DEFAULT_RECORDINGS
    model_name: str = "stub-gemini"
    calls: list[RecordedCall] = field(default_factory=list)
    _responses: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        path = self.recordings / f"{self.scenario}.json"
        if not path.is_file():
            raise StubRecordingError(
                f"No recording for LLM scenario {self.scenario!r}: {path} does not exist"
            )
        self._responses = list(json.loads(path.read_text(encoding="utf-8"))["responses"])
        self._path = path

    @property
    def model(self) -> str:
        return self.model_name

    @property
    def remaining(self) -> int:
        return len(self._responses) - len(self.calls)

    async def generate(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        tools: list[ToolDeclaration] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        index = len(self.calls)
        self.calls.append(RecordedCall(list(messages), system, tools, response_schema))
        if index >= len(self._responses):
            raise StubRecordingError(
                f"{self._path} has {len(self._responses)} responses; call {index + 1} has none"
            )
        recorded = self._responses[index]
        if delay := recorded.get("delay_seconds"):
            await asyncio.sleep(delay)
        if "error" in recorded:
            error = ERRORS.get(recorded["error"])
            if error is None:
                raise StubRecordingError(f"{self._path}: unknown error {recorded['error']!r}")
            raise error(recorded.get("message", recorded["error"]))
        text = recorded.get("text")
        if "json" in recorded:
            text = json.dumps(recorded["json"])
        usage = recorded.get("usage", {})
        return LLMResponse(
            text=text,
            tool_calls=tuple(ToolCall(**call) for call in recorded.get("tool_calls", [])),
            usage=Usage(
                input_tokens=usage.get("input_tokens", 100),
                output_tokens=usage.get("output_tokens", 20),
                latency_ms=usage.get("latency_ms", 1.0),
            ),
            model=self.model_name,
        )

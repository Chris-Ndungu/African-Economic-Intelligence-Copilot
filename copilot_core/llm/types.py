"""Provider-neutral messages, tool declarations and responses.

The tool loop and the interpretation step speak only these types, so
nothing outside :mod:`copilot_core.llm.gemini` imports the Gemini SDK.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "LLMClient",
    "LLMResponse",
    "Message",
    "ToolCall",
    "ToolDeclaration",
    "ToolResponse",
    "Usage",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolCall(_Frozen):
    """A tool the model asked to run, with its arguments."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class ToolResponse(_Frozen):
    """What a tool returned, sent back to the model."""

    name: str
    response: dict[str, Any]
    id: str | None = None


class Message(_Frozen):
    """One turn of the conversation.

    ``raw`` holds the provider's own copy of a model turn so it can be sent
    back unchanged; Gemini needs this for the thought signatures that come
    with tool calls. Clients that do not need it ignore it.
    """

    role: Literal["user", "model", "tool"]
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_responses: tuple[ToolResponse, ...] = ()
    raw: Any = Field(default=None, exclude=True, repr=False)


class ToolDeclaration(_Frozen):
    """A tool the model may call: its name, purpose and JSON Schema arguments."""

    name: str
    description: str
    parameters: dict[str, Any]


class Usage(_Frozen):
    """Tokens and time one model call used."""

    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class LLMResponse(_Frozen):
    """A model reply: text, tool calls or both, with what it cost."""

    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    raw: Any = Field(default=None, exclude=True, repr=False)

    def as_message(self) -> Message:
        """This reply as a model turn, to send back on the next call."""
        return Message(role="model", text=self.text, tool_calls=self.tool_calls, raw=self.raw)


class LLMClient(Protocol):
    """How ``copilot_core`` talks to a language model.

    Every failure raises a subclass of :class:`copilot_core.llm.errors.LLMError`.
    """

    @property
    def model(self) -> str: ...

    async def generate(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        tools: list[ToolDeclaration] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Send the conversation and return the model's reply."""
        ...

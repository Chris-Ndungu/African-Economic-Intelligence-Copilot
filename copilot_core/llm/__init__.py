"""The language model client: one protocol, Gemini behind it, a stub for tests.

Only :mod:`copilot_core.llm.gemini` imports the ``google-genai`` SDK.
"""

from copilot_core.llm.errors import (
    LLMBlocked,
    LLMError,
    LLMNotConfigured,
    LLMRequestError,
    LLMTimeout,
    LLMTruncated,
    LLMUnavailable,
)
from copilot_core.llm.gemini import DEFAULT_MODEL, GeminiClient, GeminiConfig
from copilot_core.llm.stub import StubLLMClient, StubRecordingError
from copilot_core.llm.types import (
    LLMClient,
    LLMResponse,
    Message,
    ToolCall,
    ToolDeclaration,
    ToolResponse,
    Usage,
)

__all__ = [
    "DEFAULT_MODEL",
    "GeminiClient",
    "GeminiConfig",
    "LLMBlocked",
    "LLMClient",
    "LLMError",
    "LLMNotConfigured",
    "LLMRequestError",
    "LLMResponse",
    "LLMTimeout",
    "LLMTruncated",
    "LLMUnavailable",
    "Message",
    "StubLLMClient",
    "StubRecordingError",
    "ToolCall",
    "ToolDeclaration",
    "ToolResponse",
    "Usage",
]

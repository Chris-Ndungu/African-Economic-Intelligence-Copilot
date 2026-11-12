"""Typed failures of a language model call.

Every error shares :class:`LLMError`, so a caller can catch every Gemini
failure in one place and still tell them apart. Messages never contain the
API key.
"""

from __future__ import annotations

__all__ = [
    "LLMBlocked",
    "LLMError",
    "LLMNotConfigured",
    "LLMRequestError",
    "LLMTimeout",
    "LLMTruncated",
    "LLMUnavailable",
]


class LLMError(Exception):
    """A language model call failed. ``code`` is the saved error code."""

    code = "gemini_unavailable"


class LLMNotConfigured(LLMError):
    """No API key is set, so no call can be made."""

    code = "gemini_not_configured"


class LLMTimeout(LLMError):
    """The call took longer than the configured timeout."""

    code = "gemini_timeout"


class LLMUnavailable(LLMError):
    """Rate-limited (429) or a server error (5xx), still failing after the retries."""

    code = "gemini_unavailable"


class LLMRequestError(LLMError):
    """The request was rejected (a 4xx other than 429); retrying would not help."""

    code = "gemini_request_error"


class LLMBlocked(LLMError):
    """The prompt or the reply was blocked by safety filters."""

    code = "gemini_blocked"


class LLMTruncated(LLMError):
    """The reply was cut off by the output token limit."""

    code = "gemini_truncated"

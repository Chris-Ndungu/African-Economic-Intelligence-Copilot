"""One mapping from error codes to the words the user sees.

The progress partial, the results view, the history and the export button
all use this module, so a failure reads the same everywhere. Each entry says
what happened and what the user can do. An unknown code gets a generic
message that shows the code, never a blank area. This module has no
web-framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from copilot_core.schemas import InvestigationErrorCode

__all__ = [
    "ERROR_MESSAGES",
    "RUN_CODES",
    "UI_CODES",
    "ErrorMessage",
    "error_message",
    "message_table",
    "unsupported_message",
]


@dataclass(frozen=True)
class ErrorMessage:
    code: str
    title: str
    """What happened, in a few words."""
    action: str
    """What the user can do."""

    @property
    def text(self) -> str:
        return f"{self.title}. {self.action}"


def _entry(code: str, title: str, action: str) -> tuple[str, ErrorMessage]:
    return code, ErrorMessage(code, title, action)


ERROR_MESSAGES: dict[str, ErrorMessage] = dict(
    [
        _entry(
            "data_unavailable",
            "The data is unavailable",
            "The data service could not be read, so nothing was analyzed. Try again in a few minutes.",
        ),
        _entry(
            "gemini_not_configured",
            "Gemini is not configured",
            "Questions need a Gemini API key, and none is set. Ask the administrator to add one.",
        ),
        _entry(
            "gemini_unavailable",
            "Gemini is unavailable",
            "The language model did not answer, so nothing was interpreted. Try again in a few minutes.",
        ),
        _entry(
            "gemini_timeout",
            "Gemini timed out",
            "The language model took too long to answer. Try again, or ask a narrower question.",
        ),
        _entry(
            "gemini_blocked",
            "Gemini declined to answer",
            "Its safety filters blocked this request. Rephrase the question and try again.",
        ),
        _entry(
            "gemini_truncated",
            "Gemini's answer was cut off",
            "Ask a narrower question: fewer countries, one indicator or a shorter period.",
        ),
        _entry(
            "gemini_request_error",
            "Gemini rejected the request",
            "Rephrase the question and try again. If it keeps happening, report it.",
        ),
        _entry(
            "interpretation_invalid",
            "Gemini's answer could not be read",
            "No results are shown, because they could not be checked. Try again.",
        ),
        _entry(
            "timeout",
            "The investigation took too long",
            "Ask a narrower question: fewer countries, one indicator or a shorter period.",
        ),
        _entry(
            "step_limit_reached",
            "The step limit was reached",
            "The investigation needed too many rounds of analysis. Ask a narrower question: "
            "fewer countries, one indicator or a shorter period.",
        ),
        _entry(
            "interrupted",
            "The investigation was interrupted",
            "The server restarted while it was running. Run it again.",
        ),
        _entry(
            "not_started",
            "The investigation was not started",
            "It was created but never began running. Run it again.",
        ),
        _entry(
            "client_disconnected",
            "Cancelled",
            "The investigation was stopped before it finished. Run it again if you still want it.",
        ),
        _entry(
            "internal_error",
            "An unexpected error occurred",
            "Nothing was saved as a result. Try again, and report it if it keeps happening.",
        ),
        _entry(
            "connection_lost",
            "The connection was lost",
            "The investigation may still finish. Its saved outcome will appear in the history.",
        ),
        _entry(
            "unsupported_question",
            "This question is not supported",
            "Ask about a supported indicator, country or period.",
        ),
    ]
)

UI_CODES = ("connection_lost", "unsupported_question")
"""Codes the page shows that a run is never saved with."""

RUN_CODES: tuple[str, ...] = get_args(InvestigationErrorCode)


def error_message(code: str | None) -> ErrorMessage:
    """The message for ``code``; a generic one naming the code if it is unknown."""
    known = ERROR_MESSAGES.get(code or "")
    if known is not None:
        return known
    shown = code or "none"
    return ErrorMessage(
        shown,
        "Something went wrong",
        f"The investigation failed (error code: {shown}). Try again, and report it if it keeps happening.",
    )


def unsupported_message(reason: str | None) -> str:
    """The unsupported-question message, with the reason Gemini gave if there is one."""
    base = ERROR_MESSAGES["unsupported_question"]
    return f"{base.title}: {reason}" if reason else base.text


def message_table() -> dict[str, dict[str, str]]:
    """Every message as plain data, for the page to render once as JSON."""
    return {
        code: {"title": m.title, "action": m.action, "text": m.text}
        for code, m in ERROR_MESSAGES.items()
    }

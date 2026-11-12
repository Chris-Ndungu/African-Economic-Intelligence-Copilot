"""Plain-words steps for the progress list, and the checks on a run form.

The workspace shows each progress event of a run as one step in a list.
:func:`describe_event` decides the words; the template only prints them.
:func:`build_run_request` applies the same rules the browser applies to the
run form, so a request that skips the page is checked too. This module has
no web-framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from copilot_core.events import (
    AnalysisFinishedEvent,
    AnalysisStartedEvent,
    FetchingDataEvent,
    InterpretingEvent,
    ProgressEvent,
    StartedEvent,
    ValidatingEvent,
)
from copilot_core.schemas import MAX_QUESTION_LENGTH, InvestigationRunRequest, Selection
from copilot_core.selection import PanelSelection

__all__ = [
    "EMPTY_HINT",
    "RunForm",
    "Step",
    "build_run_request",
    "describe_event",
    "normalize_question",
    "rerun_request",
    "too_long_hint",
]

TOOL_LABELS = {
    "get_coverage": "coverage check",
    "analyze_trend": "trend analysis",
    "compare_countries": "country comparison",
    "compare_with_baseline": "baseline comparison",
    "detect_anomalies": "anomaly detection",
}

EMPTY_HINT = "Type a question, or choose an indicator, countries and a period, to run."


@dataclass(frozen=True)
class Step:
    """One line of the progress list."""

    kind: Literal["step", "error"]
    text: str


def _label(tool: str) -> str:
    return TOOL_LABELS.get(tool, tool.replace("_", " "))


def describe_event(event: ProgressEvent) -> Step | None:
    """The step for ``event``, or ``None`` for an event that is not a step."""
    if isinstance(event, StartedEvent):
        return Step("step", "Starting the investigation")
    if isinstance(event, FetchingDataEvent):
        return Step("step", f"Fetching data for the {_label(event.tool)}")
    if isinstance(event, AnalysisStartedEvent):
        return Step("step", f"Running {_label(event.tool)}")
    if isinstance(event, AnalysisFinishedEvent):
        if event.error:
            return Step("error", f"The {_label(event.tool)} failed: {event.error}")
        return Step("step", f"Finished {_label(event.tool)}")
    if isinstance(event, InterpretingEvent):
        return Step("step", "Interpreting the results")
    if isinstance(event, ValidatingEvent):
        return Step("step", "Checking numbers")
    return None


@dataclass(frozen=True)
class RunForm:
    """The outcome of checking a run form: a request to run, or a hint."""

    question: str
    body: InvestigationRunRequest | None
    hint: str | None


def normalize_question(text: str) -> str:
    """The question as the analyst typed it: browser line breaks as ``\n``, trimmed."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def too_long_hint(length: int) -> str:
    return (
        f"The question has {length:,} characters; the limit is {MAX_QUESTION_LENGTH:,}. "
        "Shorten it to run."
    )


def build_run_request(question: str, selection: PanelSelection | None) -> RunForm:
    """Check a question and a complete selection; at least one is needed."""
    text = normalize_question(question)
    if len(text) > MAX_QUESTION_LENGTH:
        return RunForm(text, None, too_long_hint(len(text)))
    if not text and selection is None:
        return RunForm(text, None, EMPTY_HINT)
    fields: dict[str, object] = {}
    if text:
        fields["question"] = text
    if selection is not None:
        fields["selection"] = Selection(
            countries=list(selection.countries),
            indicator=selection.indicator,
            start=selection.start,
            end=selection.end,
        )
    return RunForm(text, InvestigationRunRequest.model_validate(fields), None)


def rerun_request(question: str | None, selection: Selection | None) -> InvestigationRunRequest:
    """The request that runs a saved investigation's input again."""
    fields: dict[str, object] = {}
    if question:
        fields["question"] = question
    if selection is not None:
        fields["selection"] = selection
    return InvestigationRunRequest.model_validate(fields)

"""Progress events of an investigation run.

The run emits these as each step happens. Routes only serialize them: the
JSON event stream (``GET /api/investigations/{id}/events``) and, later, the
HTML stream of the workspace. Each class's ``event`` is its server-sent
event name. Events carry no API keys, tool data or stack traces.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from copilot_core.schemas import InvestigationErrorCode, ServiceName

__all__ = [
    "TERMINAL_EVENTS",
    "AnalysisFinishedEvent",
    "AnalysisStartedEvent",
    "Emit",
    "FailedEvent",
    "FetchingDataEvent",
    "Heartbeat",
    "InProgressEvent",
    "InterpretingEvent",
    "ProgressEvent",
    "SavedEvent",
    "StartedEvent",
    "ValidatingEvent",
]


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event: ClassVar[str]


class StartedEvent(_Event):
    event = "started"
    investigation_id: uuid.UUID


class FetchingDataEvent(_Event):
    event = "fetching_data"
    tool: str


class AnalysisStartedEvent(_Event):
    event = "analysis_started"
    tool: str
    result_id: str


class AnalysisFinishedEvent(_Event):
    event = "analysis_finished"
    tool: str
    result_id: str
    error: str | None


class InterpretingEvent(_Event):
    event = "interpreting"


class ValidatingEvent(_Event):
    event = "validating"


class SavedEvent(_Event):
    event = "saved"
    investigation_id: uuid.UUID
    status: Literal["succeeded"] = "succeeded"


class FailedEvent(_Event):
    event = "failed"
    investigation_id: uuid.UUID
    code: InvestigationErrorCode
    message: str
    service: ServiceName | None


class InProgressEvent(_Event):
    event = "in_progress"
    investigation_id: uuid.UUID
    status: Literal["running"] = "running"


ProgressEvent = (
    StartedEvent
    | FetchingDataEvent
    | AnalysisStartedEvent
    | AnalysisFinishedEvent
    | InterpretingEvent
    | ValidatingEvent
    | SavedEvent
    | FailedEvent
    | InProgressEvent
)

TERMINAL_EVENTS = (SavedEvent, FailedEvent, InProgressEvent)


@dataclass(frozen=True)
class Heartbeat:
    """No event for a while; the stream sends a ``: ping`` comment."""


Emit = Callable[[ProgressEvent], Awaitable[None]]


async def ignore(event: ProgressEvent) -> None:
    """An :data:`Emit` that drops events, for runs nobody streams."""

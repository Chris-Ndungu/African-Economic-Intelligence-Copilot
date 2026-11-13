"""The one tool-calling loop.

:func:`run_tool_loop` sends the conversation and the tool declarations to
the model, runs the tools it asks for, sends their results back and repeats
until the model answers without a tool call or the step limit is hit. It is
a plain loop with no agent framework.

Bad requests from the model never crash the loop: an unknown tool, invalid
arguments, an analysis error, a request outside the selection or one that
would load too much data go back to the model as an error result, and the
call is recorded. :class:`~copilot_core.llm.errors.LLMError` and
:class:`~copilot_core.data.DataUnavailableError` pass through unchanged, so
the caller can tell "Gemini is down" and "the data is down" from "the
analysis failed".
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from copilot_core.analysis import AnalysisError
from copilot_core.data import DataService, DataUnavailableError, InvalidRequestError
from copilot_core.events import (
    AnalysisFinishedEvent,
    AnalysisStartedEvent,
    Emit,
    FetchingDataEvent,
    ignore,
)
from copilot_core.llm.types import LLMClient, LLMResponse, Message, ToolCall, ToolResponse
from copilot_core.schemas import LLMUsage, Selection, ToolCallRecord, ToolResult
from copilot_core.telemetry import annotate, fail_span, span
from copilot_core.tools.registry import TOOLS, OutOfScopeError, check_scope, count_points

__all__ = ["DEFAULT_MAX_POINTS", "DEFAULT_STEP_LIMIT", "LoopResult", "UsageTotals", "run_tool_loop"]

DEFAULT_STEP_LIMIT = 8
DEFAULT_MAX_POINTS = 500


@dataclass
class UsageTotals:
    """Tokens and time of every model call in a run."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0

    def add(self, response: LLMResponse) -> None:
        self.calls += 1
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        self.latency_ms += response.usage.latency_ms

    def model(self) -> LLMUsage:
        return LLMUsage(
            calls=self.calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            latency_ms=round(self.latency_ms, 3),
        )


@dataclass
class LoopResult:
    """Everything the loop recorded. ``final_text`` is ``None`` unless ``status`` is final."""

    status: Literal["final", "step_limit_reached"] = "final"
    messages: list[Message] = field(default_factory=list)
    final_text: str | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    results: list[ToolResult] = field(default_factory=list)
    usage: UsageTotals = field(default_factory=UsageTotals)

    @property
    def results_by_id(self) -> dict[str, ToolResult]:
        return {r.result_id: r for r in self.results}


def _problems(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors()
    )


async def _run_call(
    call: ToolCall,
    result_id: str,
    step: int,
    data: DataService,
    scope: Selection | None,
    max_points: int,
    emit: Emit,
    record: LoopResult,
) -> dict[str, Any]:
    """Run one tool call, record it and return what the model is sent."""
    started = time.perf_counter()
    error: str | None = None
    error_type = ""
    points = 0
    flagged = 0
    payload: dict[str, Any] | None = None
    tool = TOOLS.get(call.name)
    if tool is None:
        error = f"Unknown tool {call.name!r}. Allowed tools: {', '.join(TOOLS)}."
    else:
        with span(
            f"tool.{call.name}", **{"tool.name": call.name, "result.id": result_id}
        ) as tool_span:
            try:
                args = tool.args_model.model_validate(call.args)
                check_scope(args, scope)
                await emit(FetchingDataEvent(tool=tool.name))
                loaded = await asyncio.to_thread(tool.fetch, args, data)
                points = count_points(loaded)
                if points > max_points:
                    raise OutOfScopeError(
                        f"This request covers {points} data points, more than the limit of "
                        f"{max_points}. Ask for fewer countries or a shorter period."
                    )
                await emit(AnalysisStartedEvent(tool=tool.name, result_id=result_id))
                payload = await asyncio.to_thread(tool.analyse, args, loaded)
                flagged = int(payload.get("flagged_count") or 0)
            except ValidationError as exc:
                error_type = type(exc).__name__
                error = f"Invalid arguments for {call.name}: {_problems(exc)}"
            except DataUnavailableError:
                raise
            except (AnalysisError, InvalidRequestError, OutOfScopeError) as exc:
                error_type = type(exc).__name__
                error = str(exc)
            if error is not None:
                fail_span(tool_span, error_type)
            annotate(**{"row.count": points, "anomalies.flagged": flagged})
    duration = round((time.perf_counter() - started) * 1000, 3)
    if tool is not None:
        await emit(AnalysisFinishedEvent(tool=tool.name, result_id=result_id, error=error))
    record.tool_calls.append(
        ToolCallRecord(
            step=step,
            tool=call.name,
            arguments=dict(call.args),
            result_id=result_id,
            status="error" if error else "ok",
            error=error,
            duration_ms=duration,
        )
    )
    if error is not None or payload is None:
        return {"result_id": result_id, "error": error}
    record.results.append(
        ToolResult(result_id=result_id, tool=call.name, arguments=dict(call.args), data=payload)
    )
    return {"result_id": result_id, "data": payload}


async def run_tool_loop(
    llm: LLMClient,
    messages: list[Message],
    data: DataService,
    *,
    system: str | None = None,
    step_limit: int = DEFAULT_STEP_LIMIT,
    max_points: int = DEFAULT_MAX_POINTS,
    scope: Selection | None = None,
    emit: Emit = ignore,
    record: LoopResult | None = None,
) -> LoopResult:
    """Let the model call tools until it answers or ``step_limit`` tool rounds are used.

    Calls in one reply all run, in the order given. Result IDs are ``r1``,
    ``r2``, ... in call order across the run. Pass ``record`` to keep what
    was recorded if the loop is interrupted.
    """
    record = record if record is not None else LoopResult()
    record.messages = list(messages)
    declarations = [tool.declaration() for tool in TOOLS.values()]
    rounds = 0
    while True:
        response = await llm.generate(record.messages, system=system, tools=declarations)
        record.usage.add(response)
        record.messages.append(response.as_message())
        if not response.tool_calls:
            record.status = "final"
            record.final_text = response.text
            return record
        if rounds >= step_limit:
            record.status = "step_limit_reached"
            return record
        rounds += 1
        replies = []
        for call in response.tool_calls:
            result_id = f"r{len(record.tool_calls) + 1}"
            reply = await _run_call(call, result_id, rounds, data, scope, max_points, emit, record)
            replies.append(ToolResponse(name=call.name, response=reply, id=call.id))
        record.messages.append(Message(role="tool", tool_responses=tuple(replies)))

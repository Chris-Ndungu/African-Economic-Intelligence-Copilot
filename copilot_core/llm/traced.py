"""A model call as a span and metrics, following the OpenTelemetry GenAI conventions.

The span is named ``chat <model>`` and carries the model, the token counts and
the finish reason. Each tool call the model asks for is a span event with the
tool name. The prompt and the reply text are never recorded.
"""

from __future__ import annotations

import time
from typing import Any

from copilot_core.llm.types import LLMClient, LLMResponse
from copilot_core.telemetry import record_llm_call, span


async def traced_generate(llm: LLMClient, *args: Any, **kwargs: Any) -> LLMResponse:
    """``llm.generate(...)`` inside a ``chat <model>`` span."""
    model = llm.model
    with span(
        f"chat {model}",
        **{
            "gen_ai.system": "gemini",
            "gen_ai.request.model": model,
            "gen_ai.operation.name": "chat",
        },
    ) as chat:
        started = time.perf_counter()
        response = await llm.generate(*args, **kwargs)
        seconds = time.perf_counter() - started
        chat.set_attributes(
            {
                "gen_ai.response.model": response.model or model,
                "gen_ai.usage.input_tokens": response.usage.input_tokens,
                "gen_ai.usage.output_tokens": response.usage.output_tokens,
                "gen_ai.response.finish_reasons": ["tool_calls" if response.tool_calls else "stop"],
            }
        )
        for call in response.tool_calls:
            chat.add_event("gen_ai.tool.call", {"tool.name": call.name})
        record_llm_call(
            response.model or model,
            seconds,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
    return response

"""Analysis functions as Gemini tools, and the tool-calling loop (#25).

Every test uses ``StubLLMClient`` recordings and the demo data; none needs
the network.
"""

import asyncio

import pytest
from google.genai import types

from copilot_core.data import DataUnavailableError, DuckDBDataService
from copilot_core.events import AnalysisFinishedEvent, AnalysisStartedEvent, FetchingDataEvent
from copilot_core.llm import LLMUnavailable, StubLLMClient
from copilot_core.llm.types import Message
from copilot_core.schemas import Selection
from copilot_core.tools import TOOLS, LoopResult, declarations, run_tool_loop
from copilot_core.tools.loop import DEFAULT_STEP_LIMIT

DATA = DuckDBDataService()
QUESTION = [Message(role="user", text="How did inflation change in Kenya?")]


def loop(scenario, **kwargs):
    stub = StubLLMClient(scenario)
    result = asyncio.run(run_tool_loop(stub, QUESTION, kwargs.pop("data", DATA), **kwargs))
    return result, stub


def sent_back(stub, call=1):
    """The tool responses sent to the model on call number ``call`` (0-based)."""
    return stub.calls[call].messages[-1].tool_responses


# --- Registry ---------------------------------------------------------------------


def test_exactly_the_approved_tools_are_registered():
    assert list(TOOLS) == [
        "get_coverage",
        "analyze_trend",
        "compare_countries",
        "compare_with_baseline",
        "detect_anomalies",
    ]


@pytest.mark.parametrize("name", list(TOOLS))
def test_each_tool_schema_is_accepted_by_google_genai(name):
    tool = TOOLS[name]
    schema = types.Schema.from_json_schema(
        json_schema=types.JSONSchema.model_validate(tool.parameters()), api_option="GEMINI_API"
    )
    declaration = types.FunctionDeclaration(
        name=tool.name, description=tool.description, parameters=schema
    )
    assert declaration.parameters is not None
    assert declaration.parameters.properties
    types.FunctionDeclaration(
        name=tool.name, description=tool.description, parameters_json_schema=tool.parameters()
    )


@pytest.mark.parametrize("name", list(TOOLS))
def test_each_tool_schema_comes_from_its_pydantic_model(name):
    tool = TOOLS[name]
    assert set(tool.parameters()["properties"]) == set(tool.args_model.model_fields)
    assert "Use it" in tool.description


def test_declarations_are_sent_to_the_model():
    _, stub = loop("loop_single_tool")
    assert [d.name for d in stub.calls[0].tools] == list(TOOLS)
    assert declarations() == stub.calls[0].tools


def test_the_default_step_limit_is_eight_tool_rounds():
    assert DEFAULT_STEP_LIMIT == 8


# --- The loop ---------------------------------------------------------------------


def test_one_tool_call_then_a_final_answer():
    result, stub = loop("loop_single_tool")
    assert result.status == "final"
    assert result.final_text == "I have the results I need."
    [call] = result.tool_calls
    assert (call.step, call.tool, call.result_id, call.status) == (1, "analyze_trend", "r1", "ok")
    assert call.arguments == {
        "country": "KEN",
        "indicator": "PCPIPCH",
        "start": "2015",
        "end": "2023",
    }
    assert call.duration_ms >= 0
    [reply] = sent_back(stub)
    assert reply.response["result_id"] == "r1"
    assert reply.response["data"]["result"]["slope"]["unit"] == "percentage points per year"
    assert result.results_by_id["r1"].data == reply.response["data"]
    assert result.usage.calls == 2


def test_tool_results_are_the_serialized_analysis_models():
    result, _ = loop("loop_single_tool")
    data = result.results[0].data
    assert data["series"][0]["id"] == "series:PCPIPCH:KEN:2015-2023"
    assert data["series"][0]["points"][0] == {"period": "2015", "value": 6.6}
    assert data["result"]["slope"]["method"]["name"]


def test_two_calls_in_one_reply_both_run_in_order():
    result, stub = loop("loop_two_tools")
    assert [(c.result_id, c.arguments["country"]) for c in result.tool_calls] == [
        ("r1", "KEN"),
        ("r2", "NGA"),
    ]
    assert [r.response["result_id"] for r in sent_back(stub)] == ["r1", "r2"]


def test_an_unknown_tool_is_not_run_and_gemini_is_told_the_allowed_tools():
    result, stub = loop("loop_unknown_tool")
    [call] = result.tool_calls
    assert (call.tool, call.status) == ("forecast_inflation", "error")
    assert "Unknown tool 'forecast_inflation'" in call.error
    assert "analyze_trend" in sent_back(stub)[0].response["error"]
    assert result.results == []
    assert result.status == "final"


def test_invalid_arguments_go_back_as_an_error_and_the_loop_continues():
    result, stub = loop("loop_invalid_args")
    [call] = result.tool_calls
    assert call.status == "error"
    assert call.error.startswith("Invalid arguments for analyze_trend")
    assert "country" in call.error and "end" in call.error
    assert result.status == "final"


def test_analysis_errors_go_back_as_errors_and_never_crash_the_loop():
    result, stub = loop("loop_analysis_error")
    unknown, baseline = result.tool_calls
    assert unknown.status == "error" and "XXX" in unknown.error
    assert baseline.status == "error" and "2023" in baseline.error
    assert [r.response.get("error") is not None for r in sent_back(stub)] == [True, True]
    assert result.status == "final"


def test_a_result_over_the_size_limit_asks_for_a_narrower_request():
    result, stub = loop("loop_too_much_data", max_points=50)
    [call] = result.tool_calls
    assert call.status == "error"
    assert "more than the limit of 50" in call.error
    assert "data" not in sent_back(stub)[0].response


def test_hitting_the_step_limit_stops_without_a_final_answer():
    result, stub = loop("loop_step_limit", step_limit=2)
    assert result.status == "step_limit_reached"
    assert result.final_text is None
    assert [c.step for c in result.tool_calls] == [1, 2]
    assert len(stub.calls) == 3  # the third reply asked for more tools and was not run


def test_a_gemini_outage_mid_loop_passes_through_unchanged():
    record = LoopResult()
    with pytest.raises(LLMUnavailable, match="503"):
        asyncio.run(run_tool_loop(StubLLMClient("loop_outage"), QUESTION, DATA, record=record))
    assert [c.result_id for c in record.tool_calls] == ["r1"]


def test_a_data_outage_passes_through_unchanged(tmp_path):
    class DownData:
        def get_series(self, *args):
            raise DataUnavailableError("the data files are missing")

    with pytest.raises(DataUnavailableError):
        loop("loop_single_tool", data=DownData())


def test_calls_outside_the_selection_go_back_as_errors():
    scope = Selection(countries=["NGA"], indicator="PCPIPCH", start="2015", end="2023")
    result, _ = loop("loop_two_tools", scope=scope)
    kenya, nigeria = result.tool_calls
    assert kenya.status == "error" and "outside the selection" in kenya.error
    assert nigeria.status == "ok"


def test_progress_events_are_emitted_for_each_call():
    events = []

    async def emit(event):
        events.append(event)

    loop("loop_two_tools", emit=emit)
    assert [type(e) for e in events] == [
        FetchingDataEvent,
        AnalysisStartedEvent,
        AnalysisFinishedEvent,
    ] * 2
    assert [e.result_id for e in events if isinstance(e, AnalysisFinishedEvent)] == ["r1", "r2"]

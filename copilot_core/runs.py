"""Run an investigation from a question, a selection or both, and save it.

:class:`InvestigationService` creates the investigation as ``pending``,
claims it (``running``), lets Gemini call the analysis tools, asks for the
structured interpretation, checks its numbers, builds chart specs and saves
the investigation as ``succeeded``. Any failure is saved as ``failed`` with
an error code, and the run never reports success when Gemini or the data
failed.

The run happens inside the caller's request: :meth:`InvestigationService.run`
for the synchronous endpoint and :meth:`InvestigationService.stream` for the
event stream. Both emit the same progress events from
:mod:`copilot_core.events`; nothing keeps running after the response ends.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from copilot_core.charts import chart_specs
from copilot_core.claims import validate_interpretation
from copilot_core.data import DataService, DataUnavailableError
from copilot_core.db import DataMode
from copilot_core.events import (
    Emit,
    FailedEvent,
    Heartbeat,
    InProgressEvent,
    InterpretingEvent,
    ProgressEvent,
    SavedEvent,
    StartedEvent,
    ValidatingEvent,
    ignore,
)
from copilot_core.interpretation import (
    PROMPT_VERSION,
    Interpretation,
    InterpretationInvalid,
    VerifiedInterpretation,
    parse_interpretation,
    system_prompt,
)
from copilot_core.llm.errors import LLMError
from copilot_core.llm.traced import traced_generate
from copilot_core.llm.types import LLMClient, Message
from copilot_core.models import AnomalyResult, BaselineResult, ComparisonResult, SeriesResult
from copilot_core.repository import InvestigationRepository
from copilot_core.schemas import (
    Investigation,
    InvestigationError,
    InvestigationErrorCode,
    InvestigationRequest,
    InvestigationResult,
    InvestigationRun,
    InvestigationRunRequest,
    InvestigationType,
    PeriodRange,
    Selection,
    ServiceName,
    ValidationSummary,
)
from copilot_core.telemetry import (
    fail_span,
    investigation_id_var,
    record_claims,
    record_investigation,
    span,
)
from copilot_core.tools.loop import LoopResult, run_tool_loop

__all__ = [
    "DEMO_CAVEAT",
    "InvestigationService",
    "RunSettings",
    "StepLimitReached",
    "investigate",
    "selection_question",
    "user_prompt",
]

logger = logging.getLogger("copilot_core.runs")

DEMO_CAVEAT = "Demo mode uses a bundled sample snapshot, not live data."

FINAL_INSTRUCTION = (
    "Now give your final answer as JSON matching the response schema, following the grounding "
    "rules: cite result IDs for every finding, list every number you use with its result ID and "
    "field, label each finding fact or hypothesis, and fill data_gaps and caveats. If the "
    "question is unsupported, set unsupported_reason and leave findings empty."
)


@dataclass(frozen=True)
class RunSettings:
    step_limit: int = 8
    max_points: int = 500
    time_limit_seconds: float = 90.0
    pending_timeout_seconds: float = 300.0
    ping_seconds: float = 15.0


class StepLimitReached(Exception):
    """The model still asked for tools after the step limit."""


def _outcome(investigation: Investigation) -> str:
    """The ``outcome`` metric label: ``succeeded``, ``unsupported`` or the error code."""
    if investigation.status == "failed":
        return investigation.error.code if investigation.error else "internal_error"
    interpretation = getattr(investigation.result, "interpretation", None)
    if getattr(interpretation, "unsupported_reason", None):
        return "unsupported"
    return "succeeded"


def selection_question(selection: Selection) -> str:
    """The fixed question for a run started from a selection alone."""
    return (
        f"Describe the trend in {selection.indicator} for {', '.join(selection.countries)} "
        f"from {selection.start} to {selection.end}"
    )


def _title(question: str | None, selection: Selection | None) -> str:
    text = question or (selection_question(selection) if selection else "Investigation")
    text = " ".join(text.split())
    return text if len(text) <= 200 else text[:199] + "…"


def _final_event(investigation: Investigation) -> ProgressEvent:
    if investigation.status == "succeeded":
        return SavedEvent(investigation_id=investigation.id)
    if investigation.status == "running":
        return InProgressEvent(investigation_id=investigation.id)
    error = investigation.error or InvestigationError(
        code="internal_error", message="The investigation failed.", service=None
    )
    return FailedEvent(
        investigation_id=investigation.id,
        code=error.code,
        message=error.message,
        service=error.service,
    )


class InvestigationService:
    """Creates, runs and streams investigations.

    ``data`` and ``llm`` are factories, called when a run starts, so an
    unavailable data service or an unconfigured Gemini fails that run and is
    saved, rather than failing before the investigation exists.
    """

    def __init__(
        self,
        repository: InvestigationRepository,
        data: Callable[[], DataService],
        llm: Callable[[], LLMClient],
        data_mode: DataMode = "demo",
        settings: RunSettings | None = None,
    ) -> None:
        self.repository = repository
        self.data = data
        self.llm = llm
        self.data_mode = data_mode
        self.settings = settings or RunSettings()

    # --- Creating and running ---------------------------------------------------

    def create(self, body: InvestigationRunRequest) -> Investigation:
        """Save the run as ``pending`` without starting it."""
        return self.repository.create_run(
            question=body.question,
            selection=body.selection,
            data_mode=self.data_mode,
            title=_title(body.question, body.selection),
        )

    def get(self, investigation_id: uuid.UUID) -> Investigation:
        return self.repository.get(investigation_id)

    async def run_new(self, body: InvestigationRunRequest, emit: Emit = ignore) -> Investigation:
        """Create a run and run it to the end; returns the saved investigation."""
        investigation = self.create(body)
        return await self.run(investigation.id, emit)

    async def run(self, investigation_id: uuid.UUID, emit: Emit = ignore) -> Investigation:
        """Claim a ``pending`` run and run it; anything else is returned as it is."""
        claim = self.repository.claim(investigation_id, self.settings.pending_timeout_seconds)
        if not claim.claimed:
            return claim.investigation
        return await self._execute(claim.investigation, emit)

    async def stream(
        self, investigation: Investigation
    ) -> AsyncGenerator[ProgressEvent | Heartbeat]:
        """Run ``investigation`` if it is pending, yielding each event as it happens.

        A finished investigation yields only its final event; one another
        connection is running yields one ``in_progress`` event. A
        :class:`~copilot_core.events.Heartbeat` is yielded whenever no event
        came for ``ping_seconds``. Closing the iterator cancels the run, which
        is saved as ``failed`` with code ``client_disconnected``.
        """
        if investigation.status != "pending":
            yield _final_event(investigation)
            return
        claim = self.repository.claim(investigation.id, self.settings.pending_timeout_seconds)
        if not claim.claimed:
            yield _final_event(claim.investigation)
            return

        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
        task = asyncio.create_task(self._execute(claim.investigation, queue.put))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), self.settings.ping_seconds)
                except TimeoutError:
                    yield Heartbeat()
                    continue
                yield event
                if isinstance(event, SavedEvent | FailedEvent):
                    break
            await task
        finally:
            if not task.done():
                task.cancel()
                self._fail_now(investigation.id, "client_disconnected")

    # --- The run ------------------------------------------------------------------

    async def _execute(self, investigation: Investigation, emit: Emit) -> Investigation:
        token = investigation_id_var.set(str(investigation.id))
        started = time.perf_counter()
        try:
            with span(
                "investigation.run",
                **{"investigation.id": str(investigation.id), "data.mode": self.data_mode},
            ) as run_span:
                saved = await self._execute_steps(investigation, emit)
                error = saved.error
                if saved.status == "failed":
                    fail_span(run_span, "InvestigationFailed", error.code if error else None)
                run_span.set_attribute("investigation.status", saved.status)
                record_investigation(_outcome(saved), time.perf_counter() - started)
                logger.info(
                    "investigation %s",
                    "succeeded" if saved.status == "succeeded" else "failed",
                    extra={
                        "investigation_id": str(saved.id),
                        "outcome": saved.status,
                        "error_code": error.code if error else None,
                        "data_mode": self.data_mode,
                    },
                )
                return saved
        finally:
            investigation_id_var.reset(token)

    async def _execute_steps(self, investigation: Investigation, emit: Emit) -> Investigation:
        run = investigation.run
        question = run.question if run else None
        selection = run.selection if run else None
        record = LoopResult()
        meta: dict[str, str | None] = {"model": None, "prompt_version": PROMPT_VERSION}
        await emit(StartedEvent(investigation_id=investigation.id))

        def run_record(validation: ValidationSummary | None = None) -> InvestigationRun:
            return InvestigationRun(
                question=question,
                selection=selection,
                prompt_version=meta["prompt_version"],
                model=meta["model"],
                tool_calls=record.tool_calls,
                validation=validation,
                usage=record.usage.model(),
            )

        async def fail(
            code: InvestigationErrorCode, message: str, service: ServiceName | None
        ) -> Investigation:
            error = InvestigationError(code=code, message=message, service=service)
            self.repository.mark_failed(investigation.id, error, run_record())
            await emit(
                FailedEvent(
                    investigation_id=investigation.id, code=code, message=message, service=service
                )
            )
            return self.repository.get(investigation.id)

        try:
            async with asyncio.timeout(self.settings.time_limit_seconds):
                data = self.data()
                llm = self.llm()
                meta["model"] = llm.model
                verified = await investigate(
                    llm, data, question, selection, self.settings, emit, record
                )
                record_claims(verified.verified_count, verified.unverified_count)
                meta["model"] = verified.model
                result = self._result(verified, record, question, selection)
                validation = ValidationSummary(
                    verified_count=verified.verified_count,
                    unverified_count=verified.unverified_count,
                    unverified_findings=sum(
                        f.verification == "unverified" for f in verified.findings
                    ),
                )
                with span("investigation.save", **{"investigation.id": str(investigation.id)}):
                    saved = self.repository.save_success(
                        investigation.id, result, run_record(validation)
                    )
            if saved is None:
                return self.repository.get(investigation.id)
            await emit(SavedEvent(investigation_id=investigation.id))
            return saved
        except LLMError as exc:
            return await fail(exc.code, f"Gemini failed: {exc}", "gemini")  # type: ignore[arg-type]
        except InterpretationInvalid as exc:
            logger.warning("invalid interpretation (reply of %d characters)", len(exc.raw or ""))
            return await fail(
                "interpretation_invalid",
                "Gemini's reply could not be read as an interpretation.",
                "gemini",
            )
        except DataUnavailableError as exc:
            logger.error("data service unavailable during a run: %s", exc)
            return await fail(
                "data_unavailable", "The data service is unavailable.", "data_service"
            )
        except StepLimitReached:
            return await fail(
                "step_limit_reached",
                f"The investigation needed more than {self.settings.step_limit} rounds of "
                "analysis. Ask a narrower question: fewer countries, one indicator or a "
                "shorter period.",
                None,
            )
        except TimeoutError:
            return await fail(
                "timeout",
                f"The investigation took longer than {self.settings.time_limit_seconds:g} seconds.",
                None,
            )
        except asyncio.CancelledError:
            self._fail_now(investigation.id, "client_disconnected", run_record())
            raise
        except Exception:
            logger.exception("investigation run failed")
            return await fail("internal_error", "An unexpected error occurred.", None)

    def _fail_now(
        self,
        investigation_id: uuid.UUID,
        code: InvestigationErrorCode,
        run: InvestigationRun | None = None,
    ) -> None:
        """Save a failure without awaiting, for a run that is being cancelled."""
        with contextlib.suppress(Exception):
            self.repository.mark_failed(
                investigation_id,
                InvestigationError(
                    code=code, message="The client disconnected before the run ended.", service=None
                ),
                run,
                statuses=("running",),
            )

    def _result(
        self,
        interpretation: VerifiedInterpretation,
        record: LoopResult,
        question: str | None,
        selection: Selection | None,
    ) -> InvestigationResult:
        series: dict[str, SeriesResult] = {}
        comparisons, baselines, anomalies = [], [], []
        for result in record.results:
            for item in result.data.get("series", []):
                parsed = SeriesResult.model_validate(item)
                series.setdefault(parsed.id, parsed)
            body = result.data.get("result")
            if result.tool == "compare_countries":
                comparisons.append(ComparisonResult.model_validate(body))
            elif result.tool == "compare_with_baseline":
                baselines.append(BaselineResult.model_validate(body))
            elif result.tool == "detect_anomalies":
                anomalies.append(AnomalyResult.model_validate(body))
        sources = list({s.source.id: s.source for s in series.values()}.values())
        caveats = [c for s in series.values() for c in s.caveats]
        if self.data_mode == "demo":
            caveats.insert(0, DEMO_CAVEAT)
        return InvestigationResult(
            data_mode=self.data_mode,
            request=_request(record, question, selection),
            findings=[],
            series=list(series.values()),
            comparisons=comparisons,
            baselines=baselines,
            anomalies=anomalies,
            interpretation=interpretation,
            tool_results=record.results,
            charts=chart_specs(interpretation, record.results),
            sources=sources,
            caveats=tuple(dict.fromkeys(caveats)),
            generated_at=datetime.now(UTC),
        )


def user_prompt(data: DataService, question: str | None, selection: Selection | None) -> str:
    text = question or (selection_question(selection) if selection else "")
    text = text.replace("<question>", "").replace("</question>", "")
    indicators = "; ".join(f"{i.code} ({i.name}, {i.unit})" for i in data.list_indicators())
    lines = [f"<question>{text}</question>", "", f"Supported indicators: {indicators}."]
    lines.append("Countries are African countries, named by ISO3 code (for example KEN).")
    if selection is not None:
        lines.append(
            f"The analyst selected countries {', '.join(selection.countries)}, indicator "
            f"{selection.indicator}, from {selection.start} to {selection.end}. Query only "
            "within this selection."
        )
    return "\n".join(lines)


async def investigate(
    llm: LLMClient,
    data: DataService,
    question: str | None,
    selection: Selection | None,
    settings: RunSettings,
    emit: Emit = ignore,
    record: LoopResult | None = None,
) -> VerifiedInterpretation:
    """Let Gemini call the tools, ask for the interpretation and check its numbers.

    Raises :class:`StepLimitReached`, :class:`~copilot_core.llm.errors.LLMError`,
    :class:`~copilot_core.interpretation.InterpretationInvalid` or
    :class:`~copilot_core.data.DataUnavailableError`. ``record`` keeps the tool
    calls and token usage, even when a step fails.
    """
    record = record if record is not None else LoopResult()
    prompt = await asyncio.to_thread(user_prompt, data, question, selection)
    system = system_prompt(PROMPT_VERSION)
    with span("llm.tool_loop") as loop_span:
        await run_tool_loop(
            llm,
            [Message(role="user", text=prompt)],
            data,
            system=system,
            step_limit=settings.step_limit,
            max_points=settings.max_points,
            scope=selection,
            emit=emit,
            record=record,
        )
        loop_span.set_attribute("tool.calls", len(record.tool_calls))
        if record.status == "step_limit_reached":
            raise StepLimitReached
        await emit(InterpretingEvent())
        # The interpretation call is a Gemini call too, so it nests under the loop.
        reply = await traced_generate(
            llm,
            [*record.messages, Message(role="user", text=FINAL_INSTRUCTION)],
            system=system,
            response_schema=Interpretation,
        )
        record.usage.add(reply)
    draft = parse_interpretation(reply.text)
    await emit(ValidatingEvent())
    with span("interpretation.validate") as validate_span:
        verified = validate_interpretation(
            draft, record.results, model=reply.model or llm.model, prompt_version=PROMPT_VERSION
        )
        validate_span.set_attributes(
            {
                "claims.verified": verified.verified_count,
                "claims.unverified": verified.unverified_count,
            }
        )
    return verified


def _request(
    record: LoopResult, question: str | None, selection: Selection | None
) -> InvestigationRequest | None:
    """The selection the results cover, from the tool calls or the analyst's selection."""
    countries: dict[str, None] = {}
    indicators: dict[str, None] = {}
    starts, ends = [], []
    tools = set()
    for result in record.results:
        args = result.arguments
        tools.add(result.tool)
        for country in args.get("countries") or [args.get("country")]:
            if country:
                countries[country] = None
        for indicator in args.get("indicators") or [args.get("indicator")]:
            if indicator:
                indicators[indicator] = None
        if "start" in args and "end" in args:
            starts.append(args["start"])
            ends.append(args["end"])
    if selection is not None and not (countries and indicators and starts):
        countries = dict.fromkeys(selection.countries)
        indicators = {selection.indicator: None}
        starts, ends = [selection.start], [selection.end]
    if not (countries and indicators and starts):
        return None
    kind: InvestigationType = (
        "anomaly"
        if tools & {"detect_anomalies", "compare_with_baseline"}
        else "comparison"
        if "compare_countries" in tools or len(countries) > 1
        else "trend"
    )
    return InvestigationRequest(
        question=question,
        investigation_type=kind,
        countries=list(countries)[:10],
        indicators=list(indicators)[:5],
        period=PeriodRange(start=min(starts), end=max(ends)),
    )

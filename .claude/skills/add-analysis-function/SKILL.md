---
name: add-analysis-function
description: Use when adding or changing a deterministic analysis function in copilot_core, such as a trend, comparison, baseline or anomaly calculation.
---

# Add an analysis function

Python computes every number; Gemini only interprets the results. An analysis
function is where those numbers come from, so it must be deterministic,
tested and honest about missing data. The reasons are in
[`_docs/plan.md` section 4.4](../../../_docs/plan.md#44-hybrid-analytical-engine)
and [section 4.5](../../../_docs/plan.md#45-separate-statistical-findings-from-ai-interpretation).

## Steps

1. Read the GitHub issue and its acceptance criteria. Implement against them;
   do not change them.
2. Check that the result models exist. `SourceRef`, `Finding`, `SeriesResult`,
   `ComparisonResult`, `BaselineResult` and `AnomalyResult` are created by #11
   in `copilot_core/models.py` (or a `copilot_core/models/` package). If they
   do not exist yet, stop: the task is blocked by #11.
3. Put the function in a module under `copilot_core/analysis/`. That package
   is created by #16 (`copilot_core/analysis/trend.py`); if it does not exist
   yet, the first analysis task creates it.
4. Take result models (for example a `SeriesResult`) as input. Do no data
   loading, I/O or randomness inside the function.
5. Return the Pydantic result models from #11, never bare floats, dicts or
   DataFrames. Every result records the method name and parameters, and
   carries the input's unit, period, geography and source.
6. Handle the edge cases explicitly, with a caveat on the result rather than
   an exception, except where the issue says to raise:
   - an empty series, or one with only missing values
   - a single data point
   - missing periods (missing is `None`, never `0`)
   - mixed frequencies (raise an error naming the frequencies found)
   - a zero base for a percentage (missing with a caveat, never infinity)
7. Write the tests listed under "Tests to add", then run `uv run pytest`.
8. Commit, and comment on the issue with what you did.

## Conventions

- The function lives in `copilot_core` and imports nothing from FastAPI or
  any other web framework ([`_docs/AGENTS.md`](../../../_docs/AGENTS.md))
- It returns the Pydantic result models from #11; Pydantic models are the
  single source of truth for results
  ([`_docs/plan.md` section 4.1](../../../_docs/plan.md#41-application-architecture-fastapi--react-contract-first))
- Follow the guardrails in
  [`_docs/plan.md` section 8](../../../_docs/plan.md#8-technical-principles-and-implementation-guardrails),
  especially units and frequency, missingness, and structured outputs
- Use pandas, statsmodels or scipy (`_docs/plan.md` section 4.4). None of
  them, nor `hypothesis`, is a dependency yet: ask before adding one to
  `pyproject.toml`
- Do not expose the function as a Gemini tool here; that is #25

## Tests to add

Put the tests in `tests/`, for example `tests/test_analysis_<name>.py`.

- pytest unit tests with exact numbers on a small hand-calculated series
- An empty series (and one with only missing values) returns a result with a
  caveat
- A single data point returns its level, with the derived values missing and
  a caveat
- Missing periods are reported as missing, not skipped and not zero
- Mixed frequencies raise an error that names the frequencies
- hypothesis property tests for the invariants of the method, for example:
  reversing time order negates a slope, adding a constant leaves a slope
  unchanged, scaling values by k scales a slope by k
- Every returned model round-trips through `model_dump_json()` and
  `model_validate_json()`

## Done when

- [ ] The function is in `copilot_core/analysis/` with no FastAPI import
- [ ] It returns the Pydantic result models from #11
- [ ] pytest and hypothesis tests cover empty series, a single data point,
      missing periods and mixed frequencies
- [ ] No dependency was added without asking
- [ ] `uv run pytest` passes

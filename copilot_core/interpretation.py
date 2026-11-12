"""Gemini's structured interpretation and the prompt that asks for it.

:class:`Interpretation` is the response schema Gemini fills: a summary,
findings that each cite tool result IDs and the numbers they use, caveats,
data gaps and, for a question the data cannot answer, an
``unsupported_reason`` with no findings. :func:`parse_interpretation` turns
Gemini's reply into it or raises :class:`InterpretationInvalid`.

After :mod:`copilot_core.claims` checks every number, the result is a
:class:`VerifiedInterpretation`, the contract's ``Interpretation``.

The system prompt lives in ``copilot_core/prompts/<version>.md``; its
version string is saved with every interpretation.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

__all__ = [
    "PROMPT_VERSION",
    "CitedNumber",
    "Interpretation",
    "InterpretationFinding",
    "InterpretationInvalid",
    "NumberCheck",
    "VerifiedFinding",
    "VerifiedInterpretation",
    "parse_interpretation",
    "system_prompt",
]

PROMPT_VERSION = "interpret_v1"
PROMPTS = Path(__file__).resolve().parent / "prompts"


class _Body(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class CitedNumber(_Body):
    """A number a finding uses, and the tool result field it comes from."""

    value: float
    unit: str
    result_id: str = Field(description="The tool result the number comes from, e.g. r1.")
    field: str = Field(
        description="Dotted path to the number in that result's data, e.g. result.slope.value."
    )


class InterpretationFinding(_Body):
    statement: str
    label: Literal["fact", "hypothesis"]
    result_ids: Annotated[list[str], Field(min_length=1)]
    numbers: list[CitedNumber] = Field(default_factory=list)


class Interpretation(_Body):
    """What Gemini returns as its final answer (the response schema)."""

    summary: str
    findings: list[InterpretationFinding]
    caveats: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    unsupported_reason: str | None = None

    @model_validator(mode="after")
    def _unsupported_has_no_findings(self) -> Interpretation:
        if self.unsupported_reason and self.findings:
            raise ValueError("an unsupported question must have no findings")
        return self


class NumberCheck(_Body):
    """How one number was checked against the tool results."""

    text: str
    value: float
    result_id: str | None
    field: str | None
    verified: bool
    reason: str | None


class VerifiedFinding(InterpretationFinding):
    numbers: list[CitedNumber]
    verification: Literal["verified", "unverified"]
    checks: list[NumberCheck]
    reasons: list[str]


class VerifiedInterpretation(_Body):
    """The interpretation after every number was checked (the contract's ``Interpretation``)."""

    model_config = ConfigDict(title="Interpretation")

    summary: str
    findings: list[VerifiedFinding]
    caveats: list[str]
    data_gaps: list[str]
    unsupported_reason: str | None
    summary_checks: list[NumberCheck]
    verified_count: Annotated[int, Field(ge=0)]
    unverified_count: Annotated[int, Field(ge=0)]
    model: str
    prompt_version: str


class InterpretationInvalid(Exception):
    """Gemini's reply is not valid JSON or does not match :class:`Interpretation`.

    ``raw`` holds the reply for logs; it is never shown to users.
    """

    code = "interpretation_invalid"

    def __init__(self, message: str, raw: str | None) -> None:
        super().__init__(message)
        self.raw = raw


def parse_interpretation(text: str | None) -> Interpretation:
    if not text:
        raise InterpretationInvalid("Gemini returned no interpretation", text)
    try:
        return Interpretation.model_validate_json(text)
    except ValidationError as exc:
        kind = "not valid JSON" if exc.errors()[0]["type"] == "json_invalid" else "invalid"
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'reply'}: {e['msg']}" for e in exc.errors()
        )
        raise InterpretationInvalid(
            f"Gemini's interpretation is {kind}: {problems}", text
        ) from None


@cache
def system_prompt(version: str = PROMPT_VERSION) -> str:
    return (PROMPTS / f"{version}.md").read_text(encoding="utf-8")

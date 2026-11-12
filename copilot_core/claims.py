"""Check every number in Gemini's interpretation against the tool results.

:func:`validate_interpretation` marks each finding ``verified`` or
``unverified`` and gives a reason for every number it could not trace.
Unverified findings are kept, flagged, so the workspace can label them. The
check is deterministic: the same interpretation and results always give the
same answer.

Rules
-----

Cited numbers
    Each cited number names a result ID and a field, a dotted path into that
    result's ``data`` such as ``result.slope.value`` or
    ``series.0.points.3.value``. A missing result ID is ``unknown result``.
    The number must equal the field's value rounded to the decimals written
    in the cited number. A number that matches no field of any tool result,
    such as a difference the model worked out itself, is ``not in any tool
    result``.

Numbers in the text
    Numbers in a finding's statement must each match one of that finding's
    cited numbers; numbers in the summary must match a cited number of any
    finding. A number in the text that is not cited is unverified.

    Extraction handles negatives, decimals, thousands separators (``1,200``),
    percent signs and scale words (``1.2 million``, ``3.4bn``). A number
    matches when it equals the cited value rounded half-up to the number of
    decimals written in the text, at the scale written: "4.3%" matches 4.27,
    and "1.2 million" matches 1,234,567. A unit with a scale of its own
    (``USD_BN``, ``MILLIONS``) is read at that scale unless the text names
    another. A number written without a sign also matches a negative value,
    because words such as "fell" carry the direction.

Percentages
    "5%" matches a stored 0.05 only if the result's unit says it is a
    fraction; otherwise "5%" must match 5.

Years and periods
    Years (a whole number from 1900 to 2100) and periods such as ``2023-Q1``
    or ``2023-01`` are checked against the period labels in the cited
    results, not against their values.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from copilot_core.interpretation import (
    CitedNumber,
    Interpretation,
    InterpretationFinding,
    NumberCheck,
    VerifiedFinding,
    VerifiedInterpretation,
)
from copilot_core.models import period_frequency
from copilot_core.schemas import ToolResult

__all__ = ["TextNumber", "extract_numbers", "validate_interpretation"]

SCALES = {
    "thousand": 1e3,
    "k": 1e3,
    "million": 1e6,
    "mn": 1e6,
    "m": 1e6,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "trillion": 1e12,
    "tn": 1e12,
}
UNIT_SCALES = {"USD_BN": 1e9, "MILLIONS": 1e6, "THOUSANDS": 1e3}

_NUMBER = re.compile(
    r"""
    (?<![\w.])
    (?P<sign>[-−]?)
    (?P<digits>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    (?P<period>-Q[1-4]|-(?:0[1-9]|1[0-2])(?!\d))?
    (?:\s?(?P<percent>%|percent\b))?
    (?:\s?(?P<scale>thousand|million|billion|trillion|bn|mn|tn|k|m|b)\b)?
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass(frozen=True)
class TextNumber:
    """A number as written in the text."""

    text: str
    value: float
    decimals: int
    signed: bool
    percent: bool
    scale: float | None
    period: str | None
    """The period label, for a year or a period such as ``2023-Q1``."""


def extract_numbers(text: str) -> list[TextNumber]:
    """Every number written in ``text``, in order."""
    found = []
    for match in _NUMBER.finditer(text):
        digits = match["digits"].replace(",", "")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale_word = (match["scale"] or "").lower()
        percent = bool(match["percent"])
        period = None
        if match["period"]:
            period = digits + match["period"]
        elif (
            decimals == 0
            and "," not in match["digits"]
            and not percent
            and not scale_word
            and not match["sign"]
            and 1900 <= int(digits) <= 2100
        ):
            period = digits
        value = float(digits) * (-1 if match["sign"] else 1)
        found.append(
            TextNumber(
                text=match.group(0).strip(),
                value=value,
                decimals=decimals,
                signed=bool(match["sign"]),
                percent=percent,
                scale=SCALES[scale_word] if scale_word else None,
                period=period,
            )
        )
    return found


def _round(value: float, decimals: int) -> Decimal:
    return Decimal(repr(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def _decimals(value: float) -> int:
    text = repr(float(value))
    if "e" in text:
        return 6
    return len(text.split(".")[1].rstrip("0"))


def _is_fraction(unit: str) -> bool:
    lowered = unit.lower()
    return any(word in lowered for word in ("fraction", "ratio", "proportion", "share"))


def _text_matches(number: TextNumber, value: float, unit: str) -> bool:
    if number.percent and _is_fraction(unit):
        value *= 100
    unit_scale = UNIT_SCALES.get(unit.upper(), 1.0)
    if number.scale is not None:
        value = value * unit_scale / number.scale
    written = Decimal(repr(abs(number.value) if not number.signed else number.value))
    if not number.signed:
        return _round(abs(value), number.decimals) == written
    return _round(value, number.decimals) == written


def _resolve(data: Any, path: str) -> Any:
    node = data
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise KeyError(path)
    return node


def _leaves(data: Any) -> Iterator[Any]:
    if isinstance(data, dict):
        for value in data.values():
            yield from _leaves(value)
    elif isinstance(data, list):
        for value in data:
            yield from _leaves(value)
    else:
        yield data


def _numbers(data: Any) -> Iterator[float]:
    for leaf in _leaves(data):
        if isinstance(leaf, int | float) and not isinstance(leaf, bool) and math.isfinite(leaf):
            yield float(leaf)


def _periods(data: Any) -> set[str]:
    return {leaf for leaf in _leaves(data) if isinstance(leaf, str) and period_frequency(leaf)}


class _Checker:
    def __init__(self, results: Sequence[ToolResult]) -> None:
        self.results = {r.result_id: r for r in results}

    def anywhere(self, value: float, decimals: int | None = None) -> bool:
        for result in self.results.values():
            for found in _numbers(result.data):
                d = decimals if decimals is not None else _decimals(value)
                if _round(found, d) == _round(value, d):
                    return True
        return False

    def cited(self, number: CitedNumber) -> NumberCheck:
        def check(verified: bool, reason: str | None) -> NumberCheck:
            return NumberCheck(
                text=repr(number.value).removesuffix(".0"),
                value=number.value,
                result_id=number.result_id,
                field=number.field,
                verified=verified,
                reason=reason,
            )

        result = self.results.get(number.result_id)
        if result is None:
            return check(False, "unknown result")
        try:
            actual = _resolve(result.data, number.field)
        except KeyError:
            try:
                actual = _resolve(result.data, f"result.{number.field}")
            except KeyError:
                missing = f"field {number.field} not in {number.result_id}"
                return check(
                    False, missing if self.anywhere(number.value) else "not in any tool result"
                )
        if isinstance(actual, str) and period_frequency(actual):
            same = actual == repr(number.value).removesuffix(".0")
            return check(same, None if same else f"{number.field} is {actual}")
        if not isinstance(actual, int | float) or isinstance(actual, bool):
            return check(False, f"{number.field} in {number.result_id} is not a number")
        decimals = _decimals(number.value)
        if _round(float(actual), decimals) == _round(number.value, decimals):
            return check(True, None)
        if self.anywhere(number.value):
            return check(False, f"does not match {number.field} of {number.result_id} ({actual})")
        return check(False, "not in any tool result")

    def text(
        self,
        number: TextNumber,
        cited: Sequence[tuple[CitedNumber, NumberCheck]],
        result_ids: Sequence[str],
    ) -> NumberCheck:
        def check(
            verified: bool, reason: str | None, source: CitedNumber | None = None
        ) -> NumberCheck:
            return NumberCheck(
                text=number.text,
                value=number.value,
                result_id=source.result_id if source else None,
                field=source.field if source else None,
                verified=verified,
                reason=reason,
            )

        if number.period is not None:
            known = [rid for rid in result_ids if rid in self.results]
            if not known:
                return check(False, "unknown result")
            for rid in known:
                if number.period in _periods(self.results[rid].data):
                    return NumberCheck(
                        text=number.text,
                        value=number.value,
                        result_id=rid,
                        field=None,
                        verified=True,
                        reason=None,
                    )
            return check(False, "period not in the cited results")

        unverified: tuple[CitedNumber, NumberCheck] | None = None
        for source, source_check in cited:
            if _text_matches(number, source.value, source.unit):
                if source_check.verified:
                    return check(True, None, source)
                unverified = unverified or (source, source_check)
        if unverified is not None:
            return check(False, unverified[1].reason, unverified[0])
        if self.anywhere(number.value, number.decimals):
            return check(False, "not cited")
        return check(False, "not in any tool result")


def _reason(check: NumberCheck) -> str:
    return f"{check.text} ({check.reason})"


def _finding(checker: _Checker, finding: InterpretationFinding) -> VerifiedFinding:
    reasons = [f"unknown result {rid}" for rid in finding.result_ids if rid not in checker.results]
    cited = [(n, checker.cited(n)) for n in finding.numbers]
    checks = [c for _, c in cited]
    checks += [
        checker.text(n, cited, finding.result_ids) for n in extract_numbers(finding.statement)
    ]
    reasons += [_reason(c) for c in checks if not c.verified]
    return VerifiedFinding(
        **finding.model_dump(),
        verification="unverified" if reasons else "verified",
        checks=checks,
        reasons=reasons,
    )


def validate_interpretation(
    interpretation: Interpretation,
    results: Sequence[ToolResult],
    *,
    model: str,
    prompt_version: str,
) -> VerifiedInterpretation:
    """Mark each finding verified or unverified and count the numbers checked."""
    checker = _Checker(results)
    findings = [_finding(checker, f) for f in interpretation.findings]
    all_cited = [
        (number, checker.cited(number)) for f in interpretation.findings for number in f.numbers
    ]
    summary_checks = [
        checker.text(n, all_cited, list(checker.results))
        for n in extract_numbers(interpretation.summary)
    ]
    checks = [c for f in findings for c in f.checks] + summary_checks
    verified = sum(c.verified for c in checks)
    return VerifiedInterpretation(
        summary=interpretation.summary,
        findings=findings,
        caveats=interpretation.caveats,
        data_gaps=interpretation.data_gaps,
        unsupported_reason=interpretation.unsupported_reason,
        summary_checks=summary_checks,
        verified_count=verified,
        unverified_count=len(checks) - verified,
        model=model,
        prompt_version=prompt_version,
    )

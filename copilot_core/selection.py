"""The rules of the selection panel: what an analyst may pick, and why not.

``build_selection_panel`` is a pure function. It takes the countries,
indicators and coverage a ``DataService`` returns, plus the values the form
submitted, and returns the panel state the page renders: the options, which
countries are disabled and why, the allowed period range, the country that
limits it, any messages, and the valid :class:`~copilot_core.schemas.Selection`
or ``None`` while the form is incomplete. Templates only print this state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from copilot_core.models import Frequency
from copilot_core.schemas import Country, CoverageEntry, Indicator

__all__ = [
    "MAX_COUNTRIES",
    "CountryOption",
    "IndicatorOption",
    "PanelSelection",
    "SelectionPanel",
    "SubmittedSelection",
    "build_selection_panel",
    "period_labels",
    "submitted_from_form",
]

MAX_COUNTRIES = 8


@dataclass(frozen=True)
class SubmittedSelection:
    """The raw form values. Blank strings mean nothing was chosen."""

    countries: Sequence[str] = ()
    indicator: str = ""
    start: str = ""
    end: str = ""


@dataclass(frozen=True)
class PanelSelection:
    """A selection the data can support."""

    countries: tuple[str, ...]
    indicator: str
    start: str
    end: str


@dataclass(frozen=True)
class CountryOption:
    code: str
    name: str
    selected: bool
    disabled: bool
    reason: str | None


@dataclass(frozen=True)
class IndicatorOption:
    code: str
    label: str
    selected: bool


@dataclass(frozen=True)
class SelectionPanel:
    countries: list[CountryOption]
    indicators: list[IndicatorOption]
    indicator: str
    frequency: Frequency | None
    periods: list[str]
    start: str
    end: str
    range_start: str | None
    range_end: str | None
    limiting: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    selection: PanelSelection | None = None


def period_labels(first: str, last: str, frequency: Frequency) -> list[str]:
    """Every period label from ``first`` to ``last``, in the given frequency."""
    if frequency == "annual":
        return [str(y) for y in range(int(first), int(last) + 1)]
    if frequency == "quarterly":
        y, q = int(first[:4]), int(first[6])
        ly, lq = int(last[:4]), int(last[6])
        out: list[str] = []
        while (y, q) <= (ly, lq):
            out.append(f"{y}-Q{q}")
            y, q = (y, q + 1) if q < 4 else (y + 1, 1)
        return out
    if frequency == "monthly":
        y, m = int(first[:4]), int(first[5:7])
        ly, lm = int(last[:4]), int(last[5:7])
        out = []
        while (y, m) <= (ly, lm):
            out.append(f"{y}-{m:02d}")
            y, m = (y, m + 1) if m < 12 else (y + 1, 1)
        return out
    return []


def _joined(names: Sequence[str]) -> str:
    return ", ".join(names)


def build_selection_panel(
    countries: Sequence[Country],
    indicators: Sequence[Indicator],
    coverage: Sequence[CoverageEntry],
    submitted: SubmittedSelection | None = None,
) -> SelectionPanel:
    """The panel state for the submitted values. See the module docstring."""
    submitted = submitted or SubmittedSelection()
    by_code = {c.code: c for c in countries}
    indicator = next((i for i in indicators if i.code == submitted.indicator), None)
    messages: list[str] = []
    errors: list[str] = []

    # Coverage of the chosen indicator: country code -> (first, last) with data.
    covered: dict[str, tuple[str, str]] = {}
    if indicator is not None:
        for entry in coverage:
            if (
                entry.indicator_code == indicator.code
                and entry.first_period is not None
                and entry.last_period is not None
                and entry.observation_count > 0
            ):
                covered[entry.country_code] = (entry.first_period, entry.last_period)

    # Selected countries: known codes only, without repeats, in list order.
    wanted = set(submitted.countries)
    chosen = [c.code for c in countries if c.code in wanted]

    if indicator is not None:
        removed = [by_code[c].name for c in chosen if c not in covered]
        if removed:
            chosen = [c for c in chosen if c in covered]
            messages.append(f"Removed {_joined(removed)}: no data for {indicator.name}.")
    if len(chosen) > MAX_COUNTRIES:
        chosen = chosen[:MAX_COUNTRIES]
        messages.append(
            f"At most {MAX_COUNTRIES} countries can be selected, so only the first "
            f"{MAX_COUNTRIES} stay checked."
        )

    country_options = [
        CountryOption(
            code=c.code,
            name=c.name,
            selected=c.code in chosen,
            disabled=indicator is not None and c.code not in covered,
            reason=(
                f"No data for {indicator.name}"
                if indicator is not None and c.code not in covered
                else None
            ),
        )
        for c in countries
    ]
    indicator_options = [
        IndicatorOption(
            code=i.code,
            label=f"{i.name} ({i.unit}, {i.frequency})",
            selected=indicator is not None and i.code == indicator.code,
        )
        for i in indicators
    ]

    # The allowed period range: the periods every selected country covers, or
    # every period any country covers while none is selected.
    periods: list[str] = []
    range_start = range_end = None
    limiting: list[str] = []
    if indicator is not None and covered:
        basis = {c: covered[c] for c in chosen} or covered
        range_start = max(first for first, _ in basis.values())
        range_end = min(last for _, last in basis.values())
        if not chosen:
            range_start = min(first for first, _ in basis.values())
            range_end = max(last for _, last in basis.values())
        else:
            starters = [by_code[c].name for c, (f, _) in basis.items() if f == range_start]
            enders = [by_code[c].name for c, (_, la) in basis.items() if la == range_end]
            if any(f != range_start for f, _ in basis.values()):
                limiting.append(f"{_joined(starters)} limits the start to {range_start}.")
            if any(la != range_end for _, la in basis.values()):
                limiting.append(f"{_joined(enders)} limits the end to {range_end}.")
        if range_start <= range_end:
            periods = period_labels(range_start, range_end, indicator.frequency)
        else:
            errors.append(
                f"The selected countries have no period in common for {indicator.name}: "
                "remove one to continue."
            )
            range_start = range_end = None
            limiting = []

    start, end = submitted.start, submitted.end
    if periods:
        for name, value in (("start", start), ("end", end)):
            if value and value not in periods:
                messages.append(
                    f"The {name} period {value} is outside the data for the selected "
                    f"countries and was reset."
                )
        start = start if start in periods else periods[0]
        end = end if end in periods else periods[-1]
    else:
        start = end = ""

    missing: list[str] = []
    if not chosen:
        missing.append("Choose at least one country.")
    if indicator is None:
        missing.append("Choose an indicator.")
    if periods and start > end:
        errors.append(f"The start period ({start}) is after the end period ({end}).")

    selection = None
    if not missing and not errors and indicator is not None and periods:
        selection = PanelSelection(tuple(chosen), indicator.code, start, end)

    return SelectionPanel(
        countries=country_options,
        indicators=indicator_options,
        indicator=indicator.code if indicator else "",
        frequency=indicator.frequency if indicator else None,
        periods=periods,
        start=start,
        end=end,
        range_start=range_start,
        range_end=range_end,
        limiting=limiting,
        messages=messages,
        errors=errors,
        missing=missing,
        selection=selection,
    )


def submitted_from_form(form: Mapping[str, Sequence[str]]) -> SubmittedSelection:
    """Read the panel's form fields from a parsed, multi-valued form."""

    def one(name: str) -> str:
        values = form.get(name, [])
        return values[0].strip() if values else ""

    return SubmittedSelection(
        countries=[v.strip() for v in form.get("country", [])],
        indicator=one("indicator"),
        start=one("start"),
        end=one("end"),
    )

"""Unit tests for the selection panel rules in ``copilot_core.selection``."""

from selection_helpers import COUNTRIES, COVERAGE, EXTRA, INDICATORS, entry

from copilot_core.selection import MAX_COUNTRIES, SubmittedSelection, build_selection_panel


def panel(countries=(), indicator="", start="", end="", **kw):
    return build_selection_panel(
        kw.get("all_countries", COUNTRIES),
        INDICATORS,
        kw.get("coverage", COVERAGE),
        SubmittedSelection(list(countries), indicator, start, end),
    )


def test_a_complete_selection_is_returned_valid():
    state = panel(["KEN", "NGA"], "INF", "2000", "2020")

    assert state.selection is not None
    assert (state.selection.countries, state.selection.indicator) == (("KEN", "NGA"), "INF")
    assert (state.selection.start, state.selection.end) == ("2000", "2020")
    assert state.missing == [] and state.errors == []


def test_an_incomplete_selection_is_none_and_says_what_is_missing():
    state = panel()

    assert state.selection is None
    assert state.missing == ["Choose at least one country.", "Choose an indicator."]


def test_more_than_eight_countries_keeps_eight_and_names_the_limit():
    many = [*COUNTRIES, *EXTRA]
    coverage = [entry(c.code, "INF", "2000", "2020") for c in many]
    state = panel([c.code for c in many[:9]], "INF", all_countries=many, coverage=coverage)

    assert sum(o.selected for o in state.countries) == MAX_COUNTRIES == 8
    assert any("At most 8 countries" in m for m in state.messages)


def test_a_country_without_data_is_disabled_with_its_reason():
    state = panel([], "INF")
    ssd = next(o for o in state.countries if o.code == "SSD")

    assert ssd.disabled and ssd.reason == "No data for Inflation"
    assert not next(o for o in state.countries if o.code == "KEN").disabled


def test_the_period_is_limited_by_coverage_and_names_the_limiting_country():
    state = panel(["EGY", "GHA"], "INF")

    assert state.periods[0] == "2000" and state.periods[-1] == "2022"
    assert state.limiting == [
        "Ghana limits the start to 2000.",
        "Ghana limits the end to 2022.",
    ]
    assert (state.start, state.end) == ("2000", "2022")


def test_no_limiting_country_when_coverage_matches():
    state = panel(["EGY", "NGA"], "INF")

    assert state.limiting == []


def test_start_after_end_is_an_error_without_a_selection():
    state = panel(["KEN"], "INF", "2010", "2005")

    assert state.selection is None
    assert state.errors == ["The start period (2010) is after the end period (2005)."]


def test_changing_the_indicator_clears_countries_without_data_and_says_which():
    state = panel(["KEN", "SSD"], "INF")

    assert [o.code for o in state.countries if o.selected] == ["KEN"]
    assert state.messages == ["Removed South Sudan: no data for Inflation."]


def test_countries_with_no_common_period_are_an_error():
    coverage = [entry("EGY", "INF", "1990", "2000"), entry("GHA", "INF", "2010", "2020")]
    state = panel(["EGY", "GHA"], "INF", coverage=coverage)

    assert state.selection is None and state.periods == []
    assert "no period in common" in state.errors[0]


def test_a_period_outside_coverage_is_reset_with_a_message():
    state = panel(["GHA"], "INF", "1990", "2030")

    assert (state.start, state.end) == ("2000", "2022")
    assert len(state.messages) == 2


def test_unknown_codes_are_ignored():
    state = panel(["ZZZ", "KEN"], "NOPE")

    assert state.indicator == "" and [o.code for o in state.countries if o.selected] == ["KEN"]

"""Checking the interpretation's numbers against the tool results (#27).

Each rule has a passing and a failing case.
"""

import pytest

from copilot_core.claims import extract_numbers, validate_interpretation
from copilot_core.interpretation import CitedNumber, Interpretation, InterpretationFinding
from copilot_core.schemas import ToolResult

RESULTS = [
    ToolResult(
        result_id="r1",
        tool="analyze_trend",
        arguments={"country": "KEN", "indicator": "PCPIPCH", "start": "2015", "end": "2023"},
        data={
            "result": {
                "slope": {"value": 4.27, "unit": "%", "period": {"start": "2015", "end": "2023"}},
                "level_change": {"value": -1.5, "unit": "percentage points"},
            },
            "series": [{"points": [{"period": "2022", "value": 7.6}]}],
        },
    ),
    ToolResult(
        result_id="r2",
        tool="analyze_trend",
        arguments={},
        data={
            "result": {
                "gdp": {"value": 1234567.0, "unit": "USD"},
                "share": {"value": 0.05, "unit": "fraction"},
                "rate": {"value": 0.05, "unit": "USD"},
                "exports": {"value": 3.4, "unit": "USD_BN"},
                "quarter": {"value": 2.0, "period": "2023-Q1"},
                "big": {"value": 1200.0, "unit": "USD"},
            }
        },
    ),
]


def cite(value, field, result_id="r1", unit="%"):
    return CitedNumber(value=value, unit=unit, result_id=result_id, field=field)


def check(statement, numbers=(), result_ids=("r1",), summary="", label="fact"):
    interpretation = Interpretation(
        summary=summary,
        findings=[
            InterpretationFinding(
                statement=statement,
                label=label,
                result_ids=list(result_ids),
                numbers=list(numbers),
            )
        ],
    )
    return validate_interpretation(interpretation, RESULTS, model="m", prompt_version="v")


def verified(statement, numbers=(), **kwargs):
    return check(statement, numbers, **kwargs).findings[0].verification == "verified"


def reasons(statement, numbers=(), **kwargs):
    return check(statement, numbers, **kwargs).findings[0].reasons


SLOPE = cite(4.27, "result.slope.value")


# --- Cited numbers ------------------------------------------------------------------


def test_a_cited_number_matching_its_field_is_verified():
    assert verified("The trend was 4.27%.", [SLOPE])


def test_a_cited_number_not_matching_its_field_is_unverified():
    result = check("The trend was 4.5%.", [cite(4.5, "result.slope.value")])
    finding = result.findings[0]
    assert finding.verification == "unverified"
    assert "not in any tool result" in finding.reasons[0]


def test_a_cited_number_is_compared_at_the_decimals_it_is_written_with():
    assert verified("The trend was 4.3%.", [cite(4.3, "result.slope.value")])
    assert not verified("The trend was 4.2%.", [cite(4.2, "result.slope.value")])


def test_a_field_path_without_the_result_prefix_is_accepted():
    assert verified("The trend was 4.27%.", [cite(4.27, "slope.value")])


def test_a_missing_field_is_unverified():
    assert "not in r1" in reasons("Value 7.6.", [cite(7.6, "result.missing.value")])[0]


def test_an_unknown_result_id_makes_the_finding_unverified():
    assert reasons("Inflation rose.", result_ids=["r9"]) == ["unknown result r9"]
    assert "unknown result" in reasons("Up 4.27%.", [cite(4.27, "x", "r9")], result_ids=["r1"])[0]


def test_a_number_the_model_calculated_itself_is_unverified():
    # 4.27 - (-1.5) = 5.77: no tool returned it.
    found = reasons("The gap is 5.77 points.", [cite(5.77, "result.slope.value")])
    assert found and all("not in any tool result" in r for r in found)


# --- Numbers in the text --------------------------------------------------------------


def test_a_number_in_the_text_must_be_cited():
    assert verified("Rose 4.27% in 2022.", [SLOPE])
    found = reasons("Rose 4.27% while the series shows 7.6.", [SLOPE])
    assert found == ["7.6 (not cited)"]


def test_a_number_in_no_result_and_not_cited_is_not_in_any_tool_result():
    assert reasons("Rose 4.27%, or 9.9 overall.", [SLOPE]) == ["9.9 (not in any tool result)"]


def test_text_numbers_round_to_the_decimals_written():
    assert verified("Inflation trended up 4.3%.", [SLOPE])
    assert verified("Inflation trended up 4%.", [SLOPE])
    assert not verified("Inflation trended up 4.2%.", [SLOPE])


def test_negatives_are_extracted():
    level = cite(-1.5, "result.level_change.value", unit="percentage points")
    assert verified("The level changed by -1.5 points.", [level])
    assert not verified("The level changed by -1.6 points.", [level])


def test_an_unsigned_number_matches_a_negative_value_because_words_carry_the_sign():
    level = cite(-1.5, "result.level_change.value", unit="percentage points")
    assert verified("The level fell by 1.5 points.", [level])


def test_thousands_separators():
    big = cite(1200.0, "result.big.value", "r2", "USD")
    assert verified("Exports were 1,200 dollars.", [big], result_ids=["r2"])
    assert not verified("Exports were 1,300 dollars.", [big], result_ids=["r2"])


@pytest.mark.parametrize(
    ("text", "ok"), [("1.2 million", True), ("1.23 million", True), ("1.3 million", False)]
)
def test_scale_words(text, ok):
    gdp = cite(1234567.0, "result.gdp.value", "r2", "USD")
    assert verified(f"GDP was {text} dollars.", [gdp], result_ids=["r2"]) is ok


def test_abbreviated_scale_words_and_units_with_their_own_scale():
    exports = cite(3.4, "result.exports.value", "r2", "USD_BN")
    assert verified("Exports were $3.4bn.", [exports], result_ids=["r2"])
    assert verified("Exports were 3.4 billion dollars.", [exports], result_ids=["r2"])
    assert verified("Exports were 3.4 (USD billions).", [exports], result_ids=["r2"])
    assert not verified("Exports were $3.4 million.", [exports], result_ids=["r2"])


def test_a_percentage_matches_a_fraction_only_when_the_unit_says_so():
    share = cite(0.05, "result.share.value", "r2", "fraction")
    assert verified("The share was 5%.", [share], result_ids=["r2"])
    rate = cite(0.05, "result.rate.value", "r2", "USD")
    assert not verified("The rate was 5%.", [rate], result_ids=["r2"])


def test_years_are_checked_against_the_periods_of_the_cited_results():
    assert verified("Between 2015 and 2023 the trend was 4.27%.", [SLOPE])
    assert reasons("In 2010 the trend was 4.27%.", [SLOPE]) == [
        "2010 (period not in the cited results)"
    ]


def test_periods_such_as_quarters_are_checked_against_periods():
    quarter = cite(2.0, "result.quarter.value", "r2", "%")
    assert verified("In 2023-Q1 it was 2%.", [quarter], result_ids=["r2"])
    assert not verified("In 2023-Q2 it was 2%.", [quarter], result_ids=["r2"])


def test_numbers_in_the_summary_must_match_a_cited_number():
    ok = check("Rose 4.27%.", [SLOPE], summary="The trend was 4.3% a year.")
    assert all(c.verified for c in ok.summary_checks)
    bad = check("Rose 4.27%.", [SLOPE], summary="Inflation will reach 12% next year.")
    assert [c.reason for c in bad.summary_checks] == ["not in any tool result"]


# --- The whole interpretation ---------------------------------------------------------


def test_unverified_findings_are_kept_and_flagged():
    interpretation = Interpretation(
        summary="s",
        findings=[
            InterpretationFinding(
                statement="Rose 4.27%.", label="fact", result_ids=["r1"], numbers=[SLOPE]
            ),
            InterpretationFinding(statement="Rose 9.9%.", label="hypothesis", result_ids=["r1"]),
        ],
    )
    result = validate_interpretation(interpretation, RESULTS, model="m", prompt_version="v")
    assert [f.verification for f in result.findings] == ["verified", "unverified"]
    assert result.findings[1].statement == "Rose 9.9%."


def test_counts_of_verified_and_unverified_numbers():
    result = check("Rose 4.27% and 9.9.", [SLOPE], summary="Since 2015.")
    # cited 4.27, text 4.27, text 9.9, summary 2015
    assert (result.verified_count, result.unverified_count) == (3, 1)


def test_the_validator_is_deterministic():
    first = check("Rose 4.3% in 2022 but 9.9 later.", [SLOPE], summary="Up 4.27%.")
    for _ in range(5):
        assert check("Rose 4.3% in 2022 but 9.9 later.", [SLOPE], summary="Up 4.27%.") == first


def test_extraction_skips_ids_and_codes():
    numbers = extract_numbers("Result r1 for NY.GDP.MKTP.KD.ZG and Q1 was 5.")
    assert [n.text for n in numbers] == ["5"]


def test_extraction_reads_each_form():
    found = {n.text: n for n in extract_numbers("-1.5, 1,200, 4.3%, 1.2 million, 3.4bn, 2023-Q1")}
    assert found["-1.5"].value == -1.5 and found["-1.5"].signed
    assert found["1,200"].value == 1200
    assert found["4.3%"].percent and found["4.3%"].decimals == 1
    assert found["1.2 million"].scale == 1e6
    assert found["3.4bn"].scale == 1e9
    assert found["2023-Q1"].period == "2023-Q1"

"""Country comparison and historical baseline (#17)."""

import math

import pytest

from copilot_core.analysis import AnalysisError, compare_countries, compare_with_baseline
from copilot_core.models import BaselineResult, ComparisonResult
from tests.helpers import make_series

# --- Comparison ---------------------------------------------------------------


def test_comparison_exact_numbers_and_alignment():
    kenya = make_series([1.0, 2.0, 3.0, 4.0], start=2018, country="KEN")  # 2018-2021
    nigeria = make_series([2.0, 4.0, 6.0, 8.0], start=2019, country="NGA")  # 2019-2022
    result = compare_countries([kenya, nigeria])
    assert isinstance(result, ComparisonResult)
    assert result.shared_periods == ("2019", "2020", "2021")
    assert result.ranking_period == "2021"
    first, second = result.entries
    assert (first.geography.country_code, first.rank, first.value) == ("NGA", 1, 6.0)
    assert (second.geography.country_code, second.rank, second.value) == ("KEN", 2, 4.0)
    assert (second.mean, second.median, second.minimum, second.maximum) == (3.0, 3.0, 2.0, 4.0)
    assert second.standard_deviation == pytest.approx(1.0)
    assert first.standard_deviation == pytest.approx(2.0)
    assert second.excluded_periods == ("2018",) and first.excluded_periods == ("2022",)
    assert (second.first_period, second.last_period, second.observation_count) == (
        "2018",
        "2021",
        4,
    )
    assert second.shared_count == 3
    assert "not a judgement" in result.method.description
    entries = [e.model_dump_json(exclude={"method"}) for e in result.entries]
    assert not any("better" in e or "worse" in e for e in entries)


def test_fewer_than_two_series_raise():
    with pytest.raises(AnalysisError, match="at least two"):
        compare_countries([make_series([1.0, 2.0])])


def test_different_units_raise_naming_each_country():
    with pytest.raises(AnalysisError, match="KEN: %, NGA: USD"):
        compare_countries([make_series([1.0]), make_series([1.0], unit="USD", country="NGA")])


def test_different_frequencies_raise_naming_each_country():
    quarterly = make_series([1.0, 2.0], country="NGA", labels=["2018-Q1", "2018-Q2"])
    with pytest.raises(AnalysisError, match="KEN: annual, NGA: quarterly"):
        compare_countries([make_series([1.0, 2.0]), quarterly])


def test_ties_share_a_rank_in_country_code_order():
    result = compare_countries(
        [
            make_series([5.0], country="NGA"),
            make_series([3.0], country="GHA"),
            make_series([5.0], country="KEN"),
        ]
    )
    ranked = [(e.geography.country_code, e.rank) for e in result.entries]
    assert ranked == [("KEN", 1), ("NGA", 1), ("GHA", 3)]


def test_country_without_shared_values_is_no_data_and_not_ranked():
    result = compare_countries([make_series([1.0, 2.0]), make_series([None, None], country="TZA")])
    last = result.entries[-1]
    assert (last.geography.country_code, last.status, last.rank, last.value) == (
        "TZA",
        "no_data",
        None,
        None,
    )
    assert "no value in the shared periods" in last.caveats[0]
    assert result.entries[0].rank == 1


def test_no_shared_periods_means_no_ranking():
    result = compare_countries(
        [make_series([1.0, 2.0], start=2018), make_series([1.0, 2.0], start=2020, country="NGA")]
    )
    assert result.shared_periods == () and result.ranking_period is None
    assert all(e.rank is None for e in result.entries)
    assert "share no periods" in result.caveats[0]


# --- Baseline -----------------------------------------------------------------

SERIES = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 10.0]  # 2015-2021


def test_baseline_exact_numbers():
    result = compare_with_baseline(make_series(SERIES, start=2015), "2021", window=4)
    assert isinstance(result, BaselineResult)
    assert (result.baseline_period.start, result.baseline_period.end) == ("2017", "2020")
    assert result.value == 10.0
    assert result.baseline_value == pytest.approx(4.5)
    assert result.median == pytest.approx(4.5)
    assert result.standard_deviation == pytest.approx(math.sqrt(5 / 3))
    assert result.z_score == pytest.approx(5.5 / math.sqrt(5 / 3))
    assert result.percentile_rank == 100.0
    assert result.difference == pytest.approx(5.5)
    assert result.percent_difference == pytest.approx(5.5 / 4.5 * 100)
    assert (result.window_count, result.missing_count) == (4, 0)
    assert result.method.parameters["window"] == 4
    assert "less than or equal to the target" in result.method.description


def test_target_is_not_in_its_own_window():
    result = compare_with_baseline(make_series([1.0, 2.0, 3.0, 100.0]), "2021", window=3)
    assert result.baseline_period.end == "2020"
    assert result.baseline_value == pytest.approx(2.0)


def test_percentile_rank_counts_less_than_or_equal():
    result = compare_with_baseline(make_series([3.0, 4.0, 5.0, 6.0, 4.0]), "2022", window=4)
    assert result.percentile_rank == 50.0


def test_missing_values_in_the_window_are_excluded_and_counted():
    result = compare_with_baseline(make_series([3.0, None, 5.0, 7.0, 9.0]), "2022", window=4)
    assert (result.window_count, result.missing_count) == (3, 1)
    assert result.baseline_value == pytest.approx(5.0)
    assert any("1 missing" in c for c in result.caveats)


def test_window_past_the_first_period_uses_what_exists():
    result = compare_with_baseline(make_series([1.0, 2.0, 3.0, 4.0]), "2021", window=10)
    assert result.window_count == 3
    assert any("Only 3 of the requested 10" in c for c in result.caveats)


def test_fewer_than_three_values_leave_statistics_missing():
    result = compare_with_baseline(make_series([1.0, 2.0, 9.0]), "2020", window=10)
    assert result.baseline_value is None and result.z_score is None
    assert result.percentile_rank is None
    assert any("at least 3" in c for c in result.caveats)


def test_zero_standard_deviation_leaves_z_score_missing():
    result = compare_with_baseline(make_series([5.0, 5.0, 5.0, 6.0]), "2021", window=3)
    assert result.z_score is None
    assert result.standard_deviation == 0.0
    assert any("z-score is undefined" in c for c in result.caveats)


def test_missing_target_raises_naming_the_period():
    with pytest.raises(AnalysisError, match="2021"):
        compare_with_baseline(make_series([1.0, 2.0, 3.0, None]), "2021")

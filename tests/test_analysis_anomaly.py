"""Configurable anomaly detection (#18)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copilot_core.analysis import AnalysisError, detect_anomalies
from copilot_core.analysis.anomaly import DEFAULTS
from copilot_core.models import AnomalyResult
from tests.helpers import make_series

NOISE = [10.0, 11.0] * 6  # 12 values, mean 10.5 in any window of 10


def flagged(result):
    return [(p.period.start, p.direction) for p in result.points if p.status == "flagged"]


def test_defaults_are_stated():
    assert DEFAULTS == {
        "rolling_zscore": {"window": 10, "threshold": 3.0},
        "iqr": {"window": 10, "threshold": 1.5},
    }
    result = detect_anomalies(make_series(NOISE))
    assert result.method.parameters["window"] == 10
    assert result.method.parameters["threshold"] == 3.0
    assert detect_anomalies(make_series(NOISE), "iqr").method.parameters["threshold"] == 1.5


@pytest.mark.parametrize("method", ["rolling_zscore", "iqr"])
def test_spike_is_flagged_up(method):
    result = detect_anomalies(make_series([*NOISE, 20.0, 10.0]), method)
    assert isinstance(result, AnomalyResult)
    assert flagged(result) == [("2030", "up")]
    spike = result.points[12]
    assert spike.method.name == method
    assert spike.threshold > 0 and spike.score is not None
    assert spike.window is not None
    assert (spike.window.start, spike.window.end) == ("2020", "2029")


@pytest.mark.parametrize("method", ["rolling_zscore", "iqr"])
def test_dip_is_flagged_down(method):
    result = detect_anomalies(make_series([*NOISE, 1.0]), method)
    assert flagged(result) == [("2030", "down")]


def test_flagged_point_carries_its_baseline():
    spike = detect_anomalies(make_series([*NOISE, 20.0])).points[12]
    assert spike.baseline_mean == pytest.approx(10.5)
    assert spike.baseline_standard_deviation == pytest.approx((10 * 0.25 / 9) ** 0.5)
    assert spike.expected_value == pytest.approx(10.5)
    iqr_spike = detect_anomalies(make_series([*NOISE, 20.0]), "iqr").points[12]
    assert (iqr_spike.q1, iqr_spike.q3, iqr_spike.iqr) == (10.0, 11.0, 1.0)


def test_exact_z_score():
    result = detect_anomalies(make_series([1.0, 2.0, 3.0, 10.0]), window=3)
    point = result.points[3]
    assert point.score == pytest.approx(8.0)  # (10 - 2) / 1
    assert (point.baseline_mean, point.baseline_standard_deviation) == (2.0, 1.0)
    assert point.status == "flagged" and point.direction == "up"


def test_exact_iqr_distance():
    result = detect_anomalies(make_series([1.0, 2.0, 3.0, 4.0, 10.0]), "iqr", window=4)
    point = result.points[4]
    assert (point.q1, point.q3, point.iqr) == (1.75, 3.25, 1.5)
    assert point.expected_value == 2.5
    assert point.score == pytest.approx(10.0 - (3.25 + 1.5 * 1.5))


def test_window_is_trailing_and_early_points_are_not_scored():
    result = detect_anomalies(make_series([1.0, 2.0, 3.0, 10.0, 2.0]), window=3)
    for point in result.points[:3]:
        assert point.status == "not_scored" and "earlier periods" in point.reason
        assert point.is_anomaly is None
    assert result.points[3].window.end == "2020"  # never includes itself


def test_sparse_series_skips_missing_values_in_the_window():
    series = make_series([1.0, None, 2.0, None, 3.0, 4.0, 5.0, 9.0], start=2018)
    result = detect_anomalies(series, window=3)
    by_period = {p.period.start: p for p in result.points}
    assert by_period["2019"].reason == "The value is missing."
    assert "1 non-missing values" in by_period["2022"].reason  # window 2019-2021
    assert "2 non-missing values" in by_period["2023"].reason  # window 2020-2022
    assert by_period["2025"].status == "flagged"  # window 2022-2024: 3, 4, 5
    assert result.scored_count == sum(p.status != "not_scored" for p in result.points)


def test_short_series_has_no_flags_and_a_caveat():
    result = detect_anomalies(make_series([1.0, 2.0, 3.0, 50.0]))
    assert result.flagged_count == 0 and result.scored_count == 0
    assert any("too short for a window of 10" in c for c in result.caveats)
    assert any("could not be checked" in c for c in result.caveats)


@pytest.mark.parametrize("method", ["rolling_zscore", "iqr"])
def test_zero_spread_is_not_scored_rather_than_flagged(method):
    result = detect_anomalies(make_series([5.0, 5.0, 5.0, 5.0, 9.0]), method, window=3)
    assert result.flagged_count == 0
    assert result.points[3].status == "not_scored"
    assert "zero" in result.points[3].reason
    assert any("no spread" in c for c in result.caveats)


def test_level_shift_flags_only_its_first_point():
    result = detect_anomalies(make_series([10.0, 11.0] * 5 + [30.0] * 5))
    assert flagged(result) == [("2028", "up")]


def test_nothing_flagged_is_distinguishable_from_not_checked():
    result = detect_anomalies(make_series([*NOISE, 10.0]))
    assert result.flagged_count == 0 and result.scored_count == 3
    assert any("No anomalies: 3 values were scored" in c for c in result.caveats)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"window": 2}, "window must be at least 3"),
        ({"threshold": 0}, "greater than zero"),
        ({"threshold": -1.0}, "greater than zero"),
        ({"method": "mad"}, "supported methods: rolling_zscore, iqr"),
    ],
)
def test_invalid_parameters_raise(kwargs, message):
    with pytest.raises(AnalysisError, match=message):
        detect_anomalies(make_series(NOISE), **kwargs)


ints = st.lists(st.one_of(st.none(), st.integers(-50, 50).map(float)), min_size=4, max_size=20)


@given(ints, st.integers(-1000, 1000), st.sampled_from(["rolling_zscore", "iqr"]))
def test_adding_a_constant_does_not_change_the_flags(values, c, method):
    original = detect_anomalies(make_series(values), method, window=3)
    shifted = detect_anomalies(
        make_series([None if v is None else v + c for v in values]), method, window=3
    )
    assert [p.status for p in shifted.points] == [p.status for p in original.points]

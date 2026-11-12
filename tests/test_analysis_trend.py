"""Trend and growth analysis (#16)."""

import ast
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copilot_core.analysis import AnalysisError, analyze_trend
from copilot_core.models import NumericResult, SeriesPoint, SeriesResult
from tests.helpers import make_series

ROOT = Path(__file__).resolve().parent.parent


def test_exact_numbers_on_a_hand_calculated_series():
    # x = 0..3, y = 1, 2, 4, 3: Sxx = 5, Sxy = 4, Syy = 5.
    trend = analyze_trend(make_series([1.0, 2.0, 4.0, 3.0]))
    assert trend.slope.value == pytest.approx(0.8)
    assert trend.intercept.value == pytest.approx(1.3)
    assert trend.r_squared.value == pytest.approx(0.64)
    assert trend.points_used == 4
    assert trend.level_change.value == pytest.approx(2.0)
    assert trend.percent_change.value == pytest.approx(200.0)
    assert [g.value for g in trend.growth] == pytest.approx([100.0, 100.0, -25.0])


def test_slope_unit_is_written_out():
    trend = analyze_trend(make_series([1.0, 2.0, 4.0]))
    assert trend.slope.unit == "percentage points per year"
    assert trend.level_change.unit == "percentage points"
    assert analyze_trend(make_series([1.0, 2.0, 4.0], unit="USD")).slope.unit == "USD per year"


def test_change_states_the_periods_actually_used():
    trend = analyze_trend(make_series([None, 2.0, 3.0, 5.0, None], start=2018))
    assert (trend.level_change.period.start, trend.level_change.period.end) == ("2019", "2021")
    assert trend.level_change.value == pytest.approx(3.0)


def test_growth_with_a_missing_side_is_missing_not_skipped():
    trend = analyze_trend(make_series([1.0, None, 2.0, 4.0]))
    assert len(trend.growth) == 3
    assert [g.value for g in trend.growth] == [None, None, 100.0]
    assert "2019" in trend.growth[0].caveats[0]
    assert (trend.growth[1].period.start, trend.growth[1].period.end) == ("2019", "2020")


def test_every_result_records_method_parameters_source_and_unit():
    series = make_series([1.0, 2.0, 4.0])
    trend = analyze_trend(series)
    results = [trend.level_change, trend.percent_change, trend.slope, trend.intercept]
    for result in [*results, trend.r_squared, *trend.growth]:
        assert isinstance(result, NumericResult)
        assert result.method.name
        assert result.method.parameters["series_id"] == series.id
        assert result.source == series.source
        assert result.unit


def test_empty_series_returns_no_values_and_a_caveat():
    trend = analyze_trend(make_series([None, None, None]))
    assert trend.level is None
    assert trend.slope.value is None and trend.slope.caveats
    assert trend.level_change.value is None
    assert any("no values" in c for c in trend.caveats)
    series = make_series([1.0]).model_copy(update={"points": ()})
    assert analyze_trend(series).slope.value is None


def test_single_point_returns_its_level_only():
    trend = analyze_trend(make_series([None, 5.0, None]))
    assert trend.level is not None and trend.level.value == 5.0
    assert trend.level_change.value is None
    assert trend.slope.value is None
    assert all(g.value is None for g in trend.growth)
    assert any("single value" in c for c in trend.caveats)


def test_two_points_warn_about_significance():
    trend = analyze_trend(make_series([1.0, 3.0]))
    assert trend.slope.value == pytest.approx(2.0)
    assert any("two points" in c for c in trend.slope.caveats)


def test_base_of_zero_is_missing_not_infinite():
    trend = analyze_trend(make_series([0.0, 2.0, 3.0]))
    assert trend.percent_change.value is None
    assert "zero" in trend.percent_change.caveats[0]
    assert trend.growth[0].value is None and "zero" in trend.growth[0].caveats[0]


def test_negative_base_warns_that_the_sign_is_hard_to_read():
    trend = analyze_trend(make_series([-4.0, -2.0]))
    assert trend.percent_change.value == pytest.approx(50.0)
    assert "negative" in trend.percent_change.caveats[0]


def test_mixed_frequencies_raise_naming_them():
    good = make_series([1.0, 2.0])
    mixed = SeriesResult.model_construct(
        **{
            **dict(good),
            "points": (
                SeriesPoint(period="2018", value=1.0),
                SeriesPoint(period="2018-Q2", value=2),
            ),
        }
    )
    with pytest.raises(AnalysisError, match="annual, quarterly"):
        analyze_trend(mixed)


def test_more_than_half_missing_adds_a_caveat_with_the_count():
    trend = analyze_trend(make_series([1.0, None, None, None, 2.0]))
    assert "3 of 5 periods are missing." in trend.caveats


def test_same_input_same_answer():
    series = make_series([1.0, 2.5, 2.0, 4.0])
    assert analyze_trend(series) == analyze_trend(series)


def test_trend_module_does_no_io_and_imports_no_web_framework():
    for name in ("trend", "comparison", "baseline", "anomaly", "common"):
        tree = ast.parse((ROOT / "copilot_core" / "analysis" / f"{name}.py").read_text("utf-8"))
        modules = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not modules & {"fastapi", "starlette", "duckdb", "random", "os", "pathlib"}, name


values = st.lists(st.integers(-1000, 1000).map(float), min_size=3, max_size=15)


@given(values)
def test_reversing_time_negates_the_slope(ys):
    forward = analyze_trend(make_series(ys)).slope.value
    backward = analyze_trend(make_series(ys[::-1])).slope.value
    assert backward == pytest.approx(-forward, abs=1e-9)


@given(values, st.integers(-10_000, 10_000))
def test_adding_a_constant_leaves_the_slope_unchanged(ys, c):
    slope = analyze_trend(make_series(ys)).slope.value
    shifted = analyze_trend(make_series([y + c for y in ys])).slope.value
    assert shifted == pytest.approx(slope, abs=1e-7)


@given(values, st.integers(-5, 5))
def test_multiplying_by_k_multiplies_the_slope(ys, k):
    slope = analyze_trend(make_series(ys)).slope.value
    scaled = analyze_trend(make_series([y * k for y in ys])).slope.value
    assert scaled == pytest.approx(slope * k, abs=1e-7)

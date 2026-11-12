"""The figure builder: ChartSpec plus results in, Plotly figure dict out."""

import json

import pytest

from copilot_core.analysis import detect_anomalies
from copilot_core.figures import FigureError, MixedUnitsError, build_chart, build_figure
from copilot_core.schemas import ChartSpec, ToolResult
from tests.helpers import make_series


def tool_result(tool, series, result=None, result_id="r1"):
    data = {"series": [s.model_dump(mode="json") for s in series]}
    if result is not None:
        data["result"] = result.model_dump(mode="json")
    return ToolResult(result_id=result_id, tool=tool, arguments={}, data=data)


def spec(series, kind="line", title="A chart", result_id="r1"):
    return ChartSpec(
        id="chart:r1",
        kind=kind,
        title=title,
        result_id=result_id,
        unit=series[0].unit if series else None,
        series_ids=[s.id for s in series],
    )


def test_timeseries_has_one_line_per_country_and_the_unit_on_the_axis():
    series = [make_series([1.0, 2.0, 3.0]), make_series([4.0, 5.0, 6.0], country="NGA")]
    figure = build_figure(spec(series), [tool_result("analyze_trend", series)])

    assert [t["name"] for t in figure["data"]] == ["Kenya (KEN)", "Nigeria (NGA)"]
    assert figure["layout"]["yaxis"]["title"]["text"] == "%"
    assert figure["data"][0]["x"] == ["2018", "2019", "2020"]
    assert figure["data"][0]["y"] == [1.0, 2.0, 3.0]
    assert "annual" in figure["layout"]["xaxis"]["title"]["text"]
    # Lines differ by dash and marker, not by colour alone.
    assert figure["data"][0]["line"]["dash"] != figure["data"][1]["line"]["dash"]
    assert figure["data"][0]["marker"]["symbol"] != figure["data"][1]["marker"]["symbol"]


def test_a_gap_is_null_and_not_bridged():
    series = [make_series([1.0, None, 3.0])]
    figure = build_figure(spec(series), [tool_result("analyze_trend", series)])
    trace = figure["data"][0]

    assert trace["y"] == [1.0, None, 3.0]
    assert trace["connectgaps"] is False
    assert json.loads(json.dumps(figure))["data"][0]["y"][1] is None
    assert "missing" in trace["text"][1]


def test_comparison_puts_countries_on_one_axis():
    series = [make_series([1.0, 2.0]), make_series([3.0, 4.0], country="GHA")]
    figure = build_figure(spec(series, "bar"), [tool_result("compare_countries", series)])

    assert len(figure["data"]) == 2 and figure["layout"]["yaxis"]["title"]["text"] == "%"


def test_mixed_units_are_an_error_not_a_figure():
    series = [make_series([1.0, 2.0]), make_series([3.0, 4.0], country="GHA", unit="USD")]
    results = [tool_result("compare_countries", series)]

    with pytest.raises(MixedUnitsError) as error:
        build_figure(spec(series, "bar"), results)

    assert error.value.units == ("%", "USD")
    view = build_chart(spec(series, "bar"), results)
    assert view.figure is None
    assert view.error == ("These results use different units and cannot share one axis: %, USD.")


def test_anomaly_marks_flagged_points_by_shape_with_formatted_hover():
    stable = [10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 10.1]
    values = [*stable, 30.0, *stable, *stable, 0.5]
    series = make_series(values, start=2000)
    anomalies = detect_anomalies(series)
    assert anomalies.flagged_count >= 2
    figure = build_figure(
        spec([series]), [tool_result("detect_anomalies", [series], result=anomalies)]
    )

    line, up, down = figure["data"]
    assert line["mode"] == "lines" and line["connectgaps"] is False
    assert up["marker"]["symbol"] == "triangle-up" and "2010" in up["x"]
    assert down["marker"]["symbol"] == "triangle-down" and "2031" in down["x"]
    hover = up["text"][0]
    assert "Period: 2010" in hover and "Value: 30.00 %" not in hover
    assert "Value: 30.0 %" in hover
    assert "Statistic:" in hover and "Threshold: 3.00" in hover
    assert f"Method: {anomalies.method.name}" in hover


def test_a_result_with_no_values_is_an_empty_view_with_its_caveat():
    series = [make_series([None, None])]
    view = build_chart(spec(series), [tool_result("analyze_trend", series)])

    assert view.empty and view.figure is None and view.table is None
    assert view.caveats == ["Some values are missing."]


def test_a_coverage_spec_and_a_missing_result_have_no_figure():
    series = [make_series([1.0])]
    with pytest.raises(FigureError):
        build_figure(spec(series, "table"), [tool_result("get_coverage", series)])
    with pytest.raises(FigureError):
        build_figure(spec(series, result_id="nope"), [tool_result("analyze_trend", series)])


def test_the_table_has_the_chart_values_one_row_per_period():
    series = [make_series([1.0, None]), make_series([3.0, 4.0], country="GHA")]
    view = build_chart(spec(series), [tool_result("analyze_trend", series)])

    assert view.table is not None
    assert [c[0] for c in view.table.columns] == ["Kenya", "Ghana"]
    assert [(r.period, [c.value for c in r.cells]) for r in view.table.rows] == [
        ("2018", [1.0, 3.0]),
        ("2019", [None, 4.0]),
    ]
    assert view.sources == ["IMF DataMapper"]

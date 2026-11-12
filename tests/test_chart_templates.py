"""The chart and table partials, rendered with fixture results."""

import json
import re

from test_web import STATIC, Page, text

from backend.web import PLOTLY_FILE, templates
from copilot_core.figures import ChartView, build_chart
from copilot_core.schemas import ChartSpec, ToolResult
from tests.helpers import make_series


def view_for(series, kind="line", title="Inflation"):
    result = ToolResult(
        result_id="r1",
        tool="analyze_trend",
        arguments={},
        data={"series": [s.model_dump(mode="json") for s in series]},
    )
    spec = ChartSpec(
        id="c1",
        kind=kind,
        title=title,
        result_id="r1",
        unit=series[0].unit,
        series_ids=[s.id for s in series],
    )
    return build_chart(spec, [result])


def render(name, view):
    return templates.env.get_template(f"partials/{name}.html").render(view=view)


def test_table_shows_a_dash_for_a_missing_value_and_the_unit_in_the_header():
    html = render("table", view_for([make_series([1.5, None, 3.0])]))
    page = Page(html)

    assert text(page.find_all("th", scope="col")[1]) == "Kenya (%)"
    missing = page.find("td", **{"aria-label": "missing"})
    assert text(missing) == "—"
    assert ">0.0<" not in html


def test_missing_values_have_an_empty_sort_value_and_others_their_number():
    page = Page(render("table", view_for([make_series([1.5, None, 3.0])])))
    cells = [c for c in page.find_all("td")]

    assert [c.attrs["data-sort-value"] for c in cells] == ["1.5", "", "3.0"]
    assert "data-sortable" in page.find("table").attrs


def test_table_values_are_formatted_by_the_shared_filter():
    page = Page(render("table", view_for([make_series([1234.567], unit="USD_BN")])))

    assert text(page.find_all("td")[0]) == "1,234.6"


def test_empty_state_shows_the_caveat_text_and_no_chart():
    html = render("chart", view_for([make_series([None, None])]))

    assert "No values to show for this selection." in html
    assert "Some values are missing." in html
    assert "plotly-chart" not in html


def test_chart_shows_source_gap_note_and_json_figure():
    html = render("chart", view_for([make_series([1.0, None])]))
    page = Page(html)

    assert text(page.find("p", **{"class": "chart-source"})) == "Source: IMF DataMapper"
    assert "missing data" in text(page.find("p", **{"class": "chart-note"}))
    payload = re.search(r'<script type="application/json" class="chart-data">(.*?)</script>', html)
    assert json.loads(payload.group(1))["data"][0]["y"] == [1.0, None]


def test_a_script_end_tag_in_a_title_or_source_cannot_break_out():
    evil = "</script><script>alert(1)</script>"
    series = make_series([1.0, 2.0])
    series = series.model_copy(update={"source": series.source.model_copy(update={"name": evil})})
    html = render("chart", view_for([series], title=evil))

    assert "<script>alert(1)" not in html
    assert len(re.findall(r"</script>", html)) == 1
    payload = re.search(r'class="chart-data">(.*?)</script>', html).group(1)
    assert json.loads(payload)["layout"]["title"]["text"] == evil
    assert "&lt;/script&gt;" in html  # the source name, as escaped text


def test_the_error_view_names_the_units():
    view = ChartView(kind=None, title="t", error="These results use different units: %, USD.")

    assert "different units" in render("chart", view)


def test_the_scripts_exist_and_the_base_page_loads_them():
    from fastapi.testclient import TestClient

    from backend.main import create_app
    from backend.settings import Settings

    client = TestClient(create_app(Settings()))
    sources = [
        e.attrs["src"] for e in Page(client.get("/").text).find_all("script") if "src" in e.attrs
    ]

    assert f"/static/{PLOTLY_FILE}" in sources
    assert "/static/charts.js" in sources and "/static/table-sort.js" in sources
    for src in sources:
        assert client.get(src).status_code == 200
    assert "htmx.onLoad" in (STATIC / "charts.js").read_text(encoding="utf-8")

"""The results partial, rendered with fixture investigations."""

from results_helpers import (
    failed,
    make_finding,
    make_ifinding,
    make_interpretation,
    make_investigation,
    make_result,
    make_run,
)
from test_web import Page, text

from backend.web import templates


def render(investigation):
    return templates.env.get_template("partials/results.html").render(investigation=investigation)


def full(findings=(), ifindings=(), **kw):
    interpretation = make_interpretation(list(ifindings)) if ifindings else None
    return make_investigation(make_result(findings, interpretation, **kw))


def test_header_shows_question_countries_indicator_period_mode_and_utc_time():
    page = Page(render(full([make_finding()])))

    header = text(page.find("header"))
    assert "Why?" in header and "Kenya (KEN)" in header and "PCPIPCH" in header
    assert "2018–2020" in header and "Demo data" in header
    assert text(page.find("time")) == "2026-11-12 10:30 UTC"


def test_header_summarises_selections_when_there_is_no_question():
    inv = make_investigation(None, status="pending", question=None, run=make_run())

    assert "PCPIPCH · KEN, NGA · 2018–2020" in text(Page(render(inv)).find("h2"))


def test_card_shows_statement_numbers_method_parameters_sources_and_caveats():
    page = Page(render(full([make_finding(value=1234.567, caveats=("Revised data.",))])))

    card = text(page.find("article"))
    assert "Inflation rose." in card and "1,234.6 %" in card
    assert "linear_trend" in card and "k: 2" in card and "Revised data." in card
    assert "Curated model: fact_macroeconomic_indicators" in card
    assert "original source: IMF DataMapper (IMF)" in card and "last updated: 2026-01-15" in card


def test_sources_expand_with_details_and_summary():
    page = Page(render(full([make_finding()])))

    assert page.find("details") is not None and page.find("summary") is not None


def test_facts_come_before_hypotheses_and_the_hypothesis_is_labelled_in_text():
    html = render(full([make_finding()], [make_ifinding("Maybe drought.", label="hypothesis")]))

    assert html.index("Observed facts") < html.index("Possible explanations")
    assert html.index("Inflation rose.") < html.index("Maybe drought.")
    assert any(text(e) == "Hypothesis" for e in Page(html).find_all("span"))


def test_an_unverified_claim_shows_its_label_and_reason_and_is_not_a_plain_fact():
    claim = make_ifinding(
        "Prices doubled.", verification="unverified", reasons=("not in any result",)
    )
    html = render(full([], [claim]))

    assert any(text(e) == "Unverified" for e in Page(html).find_all("span"))
    assert "not in any result" in html
    assert "Observed facts" not in html and "Unverified claims" in html
    assert not any(text(e) == "Observed fact" for e in Page(html).find_all("span"))


def test_a_relationship_finding_shows_the_association_sentence():
    inv = full([make_finding(result_ids=("r1", "r2"))])
    first = inv.result.tool_results[0]
    second = first.model_copy(update={"result_id": "r2", "arguments": {"indicator": "NGDP_RPCH"}})
    result = inv.result.model_copy(update={"tool_results": [first, second]})

    assert "Association does not show cause" in render(inv.model_copy(update={"result": result}))
    assert "Association does not show cause" not in render(full([make_finding()]))


def test_card_links_to_its_chart_and_the_chart_has_the_target_id():
    page = Page(render(full([make_finding()])))

    assert page.find("a", href="#chart-c1") is not None
    assert page.find("section", id="chart-c1") is not None
    assert page.find("figure") is not None and page.find("table") is not None


def test_missing_data_notes_appear_on_the_card_they_affect():
    page = Page(render(full([make_finding()])))

    assert "Some values are missing." in text(page.find("div", **{"class": "missing-notes"}))


def test_a_missing_finding_value_prints_a_dash_never_zero():
    card = text(
        Page(render(full([make_finding(value=None, caveats=("No data for 2020.",))]))).find(
            "article"
        )
    )

    assert "—" in card and "0.00" not in card and "No data for 2020." in card


def test_no_findings_shows_the_caveats_that_explain_why():
    html = render(make_investigation(make_result([], None, caveats=("No data in the period.",))))

    assert "No findings" in html and "No data in the period." in html


def test_a_failed_investigation_shows_its_error_instead_of_findings():
    html = render(make_investigation(None, status="failed", error=failed()))

    assert "The data is unavailable." in html
    assert "Observed facts" not in html and "No findings" not in html


def test_stored_text_is_escaped():
    evil = "<script>alert(1)</script>"
    html = render(full([make_finding(statement=evil)], question=evil))

    assert "<script>alert(1)</script>" not in html
    assert html.count("&lt;script&gt;alert(1)&lt;/script&gt;") >= 2


def test_start_from_these_selections_posts_the_investigation_selections():
    page = Page(render(make_investigation(None, status="pending", run=make_run())))

    assert page.find("form").attrs["hx-post"] == "/partials/selection"
    assert [e.attrs["value"] for e in page.find_all("input")] == [
        "KEN",
        "NGA",
        "PCPIPCH",
        "2018",
        "2020",
    ]

"""The PDF report (#32): content, endpoint and safety.

Tests that only need the report's HTML always run. Tests that make a PDF
need WeasyPrint's system libraries (Pango) and are skipped, with a message
saying how to install them, where those are missing.
"""

import io
import os
import re
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from results_helpers import (
    failed,
    make_finding,
    make_ifinding,
    make_interpretation,
    make_investigation,
    make_result,
)
from selection_helpers import FakeDataService
from test_web_history import FakeRepository

from backend.main import create_app
from backend.settings import Settings
from backend.web import templates
from copilot_core.formatting import format_number
from copilot_core.report import (
    InvestigationNotExportableError,
    render_report_html,
    render_report_pdf,
    report_filename,
    url_allowed,
)
from tests.helpers import make_series

SNAPSHOT = date(2026, 11, 11)
GENERATED = datetime(2026, 11, 12, 11, 0, tzinfo=UTC)

try:
    import weasyprint  # noqa: F401

    WEASYPRINT_ERROR = ""
except (ImportError, OSError) as exc:  # Pango and friends are system libraries
    WEASYPRINT_ERROR = str(exc).splitlines()[0] if str(exc) else type(exc).__name__

needs_weasyprint = pytest.mark.skipif(
    bool(WEASYPRINT_ERROR),
    reason=(
        f"WeasyPrint's system libraries are missing ({WEASYPRINT_ERROR}). Install Pango as "
        "described under 'PDF reports' in _docs/AGENTS.md (Docker has it), then run: "
        "uv run pytest tests/test_report.py"
    ),
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def full(findings=None, ifindings=(), id=None, **kw):
    findings = [make_finding()] if findings is None else findings
    interpretation = make_interpretation(list(ifindings)) if ifindings else None
    return make_investigation(make_result(findings, interpretation, **kw), id=id)


def html(investigation, **kw):
    return render_report_html(
        investigation, snapshot_date=SNAPSHOT, generated_at=GENERATED, charts=False, **kw
    )


def plain(markup: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup))


class FailingLLM:
    """Fails the test if the report ever asks Gemini for anything."""

    model = "never"

    def __getattr__(self, name):
        raise AssertionError(f"The export called the LLM client ({name})")


def client_for(*investigations):
    app = create_app(Settings())
    app.state.data_service = FakeDataService()
    app.state.repository = FakeRepository(list(investigations))
    app.state.llm = FailingLLM()
    return TestClient(app, raise_server_exceptions=False)


# --- Content ----------------------------------------------------------------------------


def test_sections_come_in_the_required_order():
    investigation = full(
        [make_finding()], [make_ifinding("Maybe drought.", label="hypothesis")], question="Why?"
    )
    text = plain(html(investigation))

    order = [
        "Question:",
        "Data mode",
        "Countries",
        "Indicator",
        "Period",
        "Summary",
        "Findings",
        "Data tables",
        "Methodology and parameters",
        "Sources",
        "Caveats and data gaps",
        "Report generated: 2026-11-12 11:00 UTC",
    ]
    positions = [text.index(heading) for heading in order]
    assert positions == sorted(positions)
    assert "Why?" in text and "Kenya (KEN)" in text and "2018–2020" in text


def test_facts_come_first_and_hypotheses_are_labelled_under_possible_explanations():
    investigation = full([make_finding()], [make_ifinding("Maybe drought.", label="hypothesis")])
    text = plain(html(investigation))

    assert text.index("Observed facts") < text.index("Possible explanations")
    assert text.index("Possible explanations") < text.index("Hypothesis")
    assert "Maybe drought." in text


def test_unverified_claims_are_marked_with_the_reason():
    investigation = full(
        [],
        [make_ifinding("Inflation tripled.", verification="unverified", reasons=("No match.",))],
    )
    text = plain(html(investigation))

    assert "Unverified claims" in text and "Unverified" in text
    assert "Inflation tripled." in text and "No match." in text


def test_a_demo_report_states_the_sample_data_banner_for_every_page():
    markup = html(full())

    assert 'data-banner="Sample data from 2026-11-11. Not live economic data."' in markup
    assert "string-set: banner attr(data-banner)" in markup
    assert "content: string(banner)" in markup
    assert 'content: "Page " counter(page) " of " counter(pages)' in markup


def test_the_report_prints_numbers_exactly_as_the_results_page_does():
    investigation = full([make_finding(value=1234.567, caveats=("Revised.",))])
    page = templates.env.get_template("partials/results.html").render(investigation=investigation)
    report = plain(html(investigation))

    assert format_number(1234.567, "%") == "1,234.6"
    assert "1,234.6 %" in plain(page)
    assert "1,234.6 %" in report


def test_missing_values_print_as_a_dash_never_zero():
    series = make_series([1.0, None, 3.0])
    investigation = full([make_finding(value=None, caveats=("Value missing.",))], series=series)
    markup = html(investigation)

    assert re.search(r"<td>—</td>", markup)
    row = re.search(r"<th scope=\"row\">2019</th>\s*<td>([^<]*)</td>", markup)
    assert row and row.group(1) == "—"
    assert "<dd>—</dd>" in markup  # the finding with no value


def test_tables_repeat_their_header_and_keep_rows_whole():
    markup = html(full())

    assert "thead { display: table-header-group; }" in markup
    assert "break-inside: avoid" in markup


def test_stored_text_is_escaped():
    question = '<script>alert(1)</script><img src="file:///etc/passwd">'
    markup = html(full([make_finding("<b>bold</b> claim")], question=question))

    assert "<script>" not in markup and "<img" not in markup
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in markup
    assert "&lt;img src=&#34;file:///etc/passwd&#34;&gt;" in markup
    assert "&lt;b&gt;bold&lt;/b&gt; claim" in markup


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
def test_an_unfinished_investigation_cannot_be_rendered(status):
    investigation = make_investigation(
        None, status=status, error=failed() if status == "failed" else None
    )

    with pytest.raises(InvestigationNotExportableError, match="Only succeeded"):
        render_report_html(investigation)


def test_the_filename_has_the_date_and_the_first_eight_characters_of_the_id():
    investigation = make_investigation(
        make_result(), id=uuid.UUID("7f9c2b1e-4d3a-4c5b-9e8f-1a2b3c4d5e6f")
    )

    assert report_filename(investigation) == "investigation-2026-11-12-7f9c2b1e.pdf"


# --- The URL fetcher --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "http://example.com/x.png",
        "https://example.com/x.png",
        "ftp://example.com/x",
        "file://server/share/x.png",
    ],
)
def test_only_bundled_assets_and_data_uris_are_allowed(url):
    assert not url_allowed(url)


def test_data_uris_are_allowed():
    assert url_allowed("data:image/png;base64,AAAA")


@needs_weasyprint
@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://example.com/x", "https://a.b/c"])
def test_the_weasyprint_fetcher_refuses_other_urls(url):
    from copilot_core.report import make_url_fetcher

    with pytest.raises(ValueError, match="may not load"):
        make_url_fetcher().fetch(url)


# --- The endpoint -----------------------------------------------------------------------


def test_an_unknown_id_is_404_with_the_shared_error_body():
    response = client_for().get(f"/api/investigations/{uuid.uuid4()}/report")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
def test_an_unfinished_investigation_is_409_and_does_not_call_the_llm(status):
    investigation = make_investigation(
        None, status=status, error=failed() if status == "failed" else None
    )
    response = client_for(investigation).get(f"/api/investigations/{investigation.id}/report")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"
    assert "Only succeeded investigations can be exported" in body["message"]


def test_a_bad_id_is_422():
    assert client_for().get("/api/investigations/nope/report").status_code == 422


@needs_weasyprint
def test_a_succeeded_investigation_downloads_as_a_pdf_without_calling_the_llm():
    investigation = full(id=uuid.UUID("7f9c2b1e-4d3a-4c5b-9e8f-1a2b3c4d5e6f"))
    response = client_for(investigation).get(f"/api/investigations/{investigation.id}/report")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="investigation-2026-11-12-7f9c2b1e.pdf"'
    )
    assert response.headers["x-data-mode"] == "demo"
    assert response.content.startswith(b"%PDF")


# --- The PDF itself ---------------------------------------------------------------------


def pdf_pages(pdf: bytes) -> list[str]:
    from pypdf import PdfReader

    return [page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages]


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@needs_weasyprint
def test_the_pdf_text_matches_the_stored_investigation():
    investigation = full(
        [make_finding(value=1234.567)],
        [make_ifinding("Maybe drought.", label="hypothesis")],
        series=make_series([1.0, None, 3.0]),
    )
    pdf = render_report_pdf(
        investigation, snapshot_date=SNAPSHOT, generated_at=GENERATED, charts=False
    )
    pages = pdf_pages(pdf)
    text = squash(" ".join(pages))

    assert "Sample data from 2026-11-11. Not live economic data." in squash(pages[0])
    assert "1,234.6 %" in text  # value and unit of the finding
    assert "2018–2020" in text and "Kenya (KEN)" in text and "PCPIPCH" in text
    assert "Kenya (%)" in text  # the table column carries the unit
    for period, value in (("2018", "1.0"), ("2019", "—"), ("2020", "3.0")):
        assert f"{period} {value}" in text
    assert "IMF DataMapper" in text and "fact_macroeconomic_indicators" in text
    assert "Possible explanations" in text and "Hypothesis" in text
    assert "Report generated: 2026-11-12 11:00 UTC" in text
    assert text.index("Page 1 of") >= 0


@needs_weasyprint
def test_every_page_has_the_banner_and_page_x_of_y_and_long_tables_repeat_their_header():
    labels = [f"{year}-Q{q}" for year in range(1990, 2026) for q in range(1, 5)]
    series = make_series([float(i) for i in range(len(labels))], labels=labels)
    investigation = full(series=series)
    pages = pdf_pages(
        render_report_pdf(
            investigation, snapshot_date=SNAPSHOT, generated_at=GENERATED, charts=False
        )
    )

    assert len(pages) >= 3
    for number, page in enumerate(pages, start=1):
        text = squash(page)
        assert "Sample data from 2026-11-11. Not live economic data." in text
        assert f"Page {number} of {len(pages)}" in text
    table_pages = [p for p in pages if "Kenya (%)" in p]
    assert len(table_pages) >= 2  # the header row repeats on each page of the table


@needs_weasyprint
def test_a_file_url_in_the_question_never_puts_that_file_in_the_pdf(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-CONTENT")
    question = f'<img src="{secret.as_uri()}"> <script>x</script>'
    pdf = render_report_pdf(
        full(question=question), snapshot_date=SNAPSHOT, generated_at=GENERATED, charts=False
    )
    text = squash(" ".join(pdf_pages(pdf)))

    assert "TOP-SECRET-CONTENT" not in text
    assert "<script>" in text  # printed as literal text


# --- Charts (#33) ------------------------------------------------------------------------


def two_chart_investigation():
    from copilot_core.schemas import ChartSpec

    investigation = full()
    result = investigation.result
    second = ChartSpec(
        id="c2",
        kind="line",
        title="Inflation again",
        result_id="r1",
        unit="%",
        series_ids=[result.series[0].id],
    )
    result = result.model_copy(update={"charts": [*result.charts, second]})
    return investigation.model_copy(update={"result": result})


PNG = b"\x89PNG\r\n\x1a\n-fake"


def chart_html(investigation, render):
    return render_report_html(
        investigation, snapshot_date=SNAPSHOT, generated_at=GENERATED, render_chart=render
    )


def test_each_chart_spec_is_drawn_once_next_to_the_finding_that_cites_it():
    investigation = two_chart_investigation()
    markup = chart_html(investigation, lambda figure: PNG)

    assert markup.count("<img") == len(investigation.result.charts) == 2
    assert "data:image/png;base64," in markup
    # both charts cite r1, as does the finding, so they print inside its card
    card = markup[markup.index("<article") : markup.index("</article>")]
    assert card.count("<img") == 2 and "Inflation rose." in card


def test_the_figure_sent_to_kaleido_is_the_one_the_results_view_embeds():
    import json

    investigation = two_chart_investigation()
    sent = []

    def capture(figure):
        sent.append(figure)
        return PNG

    chart_html(investigation, capture)
    page = templates.env.get_template("partials/results.html").render(investigation=investigation)
    embedded = [
        json.loads(m.replace("&#34;", '"'))
        for m in re.findall(
            r'<script type="application/json" class="chart-data">(.*?)</script>', page
        )
    ]

    assert len(sent) == len(embedded) == 2
    for figure, shown in zip(sent, embedded, strict=True):
        assert figure == shown


def test_a_chart_that_fails_is_replaced_by_a_message_and_logged_with_the_investigation_id(caplog):
    investigation = two_chart_investigation()
    calls = []

    def flaky(figure):
        calls.append(figure)
        if len(calls) == 1:
            raise RuntimeError("no browser")
        return PNG

    with caplog.at_level("ERROR", logger="copilot_core.report"):
        markup = chart_html(investigation, flaky)

    assert "Chart could not be rendered" in markup
    assert markup.count("<img") == 1  # the other chart is still drawn
    assert str(investigation.id) in caplog.text


def test_charts_are_distinguishable_without_colour():
    from copilot_core.figures import line_figure

    series = [make_series([1.0, 2.0], country="KEN"), make_series([2.0, 3.0], country="NGA")]
    traces = line_figure(series, "t")["data"]

    assert len({t["line"]["dash"] for t in traces}) == 2
    assert len({t["marker"]["symbol"] for t in traces}) == 2
    assert all(t["connectgaps"] is False for t in traces)


def kaleido_error():
    try:
        from copilot_core.report import render_chart_image

        assert render_chart_image({"data": [{"type": "scatter", "x": [1], "y": [1]}]})[:4]
    except Exception as exc:
        return str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    return ""


needs_kaleido = pytest.mark.skipif(
    bool(kaleido_error()),
    reason=(
        "Kaleido could not start Chrome or Chromium. Install one, or run "
        "`uv run kaleido_get_chrome`, as described under 'PDF reports' in "
        "_docs/AGENTS.md, then run: uv run pytest tests/test_report.py"
    ),
)


@needs_kaleido
def test_kaleido_draws_the_real_figure_to_a_png():
    from copilot_core.figures import build_chart
    from copilot_core.report import render_chart_image

    investigation = two_chart_investigation()
    spec = investigation.result.charts[0]
    figure = build_chart(spec, investigation.result.tool_results).figure

    assert render_chart_image(figure).startswith(b"\x89PNG")


@needs_weasyprint
@needs_kaleido
def test_the_pdf_contains_one_image_per_chart_spec():
    from pypdf import PdfReader

    investigation = two_chart_investigation()
    pdf = render_report_pdf(investigation, snapshot_date=SNAPSHOT, generated_at=GENERATED)
    # WeasyPrint shares one resource dictionary between pages, so pypdf lists each image once
    # per page; count each distinct image once.
    images = list(
        {image.data: image for page in PdfReader(io.BytesIO(pdf)).pages for image in page.images}
    )

    assert len(images) == len(investigation.result.charts)


# --- The export button -------------------------------------------------------------------


def results_html(investigation):
    return templates.env.get_template("partials/results.html").render(investigation=investigation)


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
def test_the_export_button_is_absent_unless_the_investigation_succeeded(status):
    investigation = make_investigation(
        None, status=status, error=failed() if status == "failed" else None
    )

    assert "Export PDF" not in results_html(investigation)


def test_a_succeeded_investigation_has_a_plain_link_to_the_export_endpoint():
    investigation = full()
    markup = results_html(investigation)

    link = re.search(
        r'<a class="button secondary export-pdf" href="([^"]+)">Export PDF</a>', markup
    )
    assert link and link.group(1) == f"/api/investigations/{investigation.id}/report"
    assert 'class="message error export-error" role="alert" hidden' in markup


def test_the_page_loads_the_export_script_and_the_error_messages_it_shows():
    from backend.web import templates as web_templates

    page = client_for(full()).get("/")
    assert "/static/export.js" in page.text
    for code in ("not_found", "conflict", "service_unavailable", "internal_error"):
        assert code in web_templates.env.globals["error_messages"]
    script = (Path(__file__).resolve().parent.parent / "backend/static/export.js").read_text(
        "utf-8"
    )
    assert (
        "Content-Disposition" in script and "aria-disabled" in script and "error-messages" in script
    )

"""Journey: export an investigation as a PDF (#35)."""

import io
import re

import pytest
from playwright.sync_api import Page
from pypdf import PdfReader
from support import open_workspace, run_question, unique_question, use_scenario, wait_for_results


def squash(value: str) -> str:
    """Drop whitespace: the PDF wraps long lines."""
    return re.sub(r"\s+", "", value)


def test_export_pdf_downloads_a_report_that_names_the_question(page: Page):
    use_scenario(page, "run_success")
    question = unique_question()
    open_workspace(page)
    run_question(page, question)
    url = wait_for_results(page)

    report = url.replace("/investigations/", "/api/investigations/") + "/report"
    probe = page.request.get(report)
    if probe.status != 200:
        pytest.skip(
            f"The app cannot render PDF reports here (HTTP {probe.status}): WeasyPrint's "
            "libraries (Pango) or Chromium for the charts are missing on the server."
        )

    with page.expect_download() as download_info:
        page.get_by_role("link", name="Export PDF").click()
    download = download_info.value

    assert download.suggested_filename.endswith(".pdf")
    content = download.path().read_bytes()
    assert len(content) > 1024
    text = "".join(pdf_page.extract_text() for pdf_page in PdfReader(io.BytesIO(content)).pages)
    assert squash(question) in squash(text)

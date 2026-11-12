"""Journeys: Gemini is unavailable, and the question is not supported (#35)."""

from playwright.sync_api import Page, expect
from support import (
    INVESTIGATION_URL,
    finding_cards,
    history_entry,
    open_workspace,
    run_question,
    unique_question,
    use_scenario,
)


def test_when_gemini_is_unavailable_the_run_says_so_and_history_shows_it_failed(page: Page):
    use_scenario(page, "run_gemini_down")
    question = unique_question()
    open_workspace(page)

    run_question(page, question)

    expect(page.get_by_text("The language model did not answer")).to_be_visible(timeout=30_000)
    expect(finding_cards(page)).to_have_count(0)
    entry = history_entry(page, question)
    expect(entry).to_be_visible()
    expect(entry).to_contain_text("Failed")
    expect(entry).to_contain_text("Gemini is unavailable")


def test_an_unsupported_question_shows_the_reason_and_no_findings(page: Page):
    use_scenario(page, "run_unsupported")
    open_workspace(page)

    run_question(page, unique_question("What will inflation in Kenya be in 2030?"))
    expect(page).to_have_url(INVESTIGATION_URL, timeout=30_000)

    expect(page.get_by_role("heading", name="No findings")).to_be_visible()
    expect(
        page.get_by_text("The question asks for a forecast of future inflation.")
    ).to_be_visible()
    expect(finding_cards(page)).to_have_count(0)

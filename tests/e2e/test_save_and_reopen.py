"""Journey: a run is saved and can be reopened from the history or its URL (#35)."""

from playwright.sync_api import Page, expect
from support import (
    finding_cards,
    finding_texts,
    history_entry,
    open_workspace,
    run_question,
    unique_question,
    use_scenario,
    wait_for_results,
)


def test_a_saved_investigation_reopens_from_the_history_and_from_its_address(page: Page):
    use_scenario(page, "run_success")
    question = unique_question()
    open_workspace(page)
    run_question(page, question)
    url = wait_for_results(page)
    original = finding_texts(page)
    assert original

    page.get_by_role("link", name="New investigation").click()
    expect(page.get_by_text("Ask a question or pick a selection")).to_be_visible()
    history_entry(page, question).click()
    expect(page.get_by_role("heading", name=question)).to_be_visible()
    expect(finding_cards(page)).to_have_count(len(original))
    assert finding_texts(page) == original

    page.goto(url)
    expect(page.get_by_role("heading", name=question)).to_be_visible()
    expect(finding_cards(page)).to_have_count(len(original))
    assert finding_texts(page) == original

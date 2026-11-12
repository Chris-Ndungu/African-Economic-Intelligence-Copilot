"""Journey: ask a question and see findings that cite the stub's numbers (#35)."""

from playwright.sync_api import Page, expect
from support import (
    finding_cards,
    open_workspace,
    run_question,
    unique_question,
    use_scenario,
    wait_for_results,
)


def test_a_question_runs_and_its_findings_cite_the_computed_numbers(page: Page):
    use_scenario(page, "run_success")
    question = unique_question()
    open_workspace(page)

    run_question(page, question)
    wait_for_results(page)

    expect(page.get_by_role("heading", name=question)).to_be_visible()
    cards = finding_cards(page)
    expect(cards).to_have_count(3)
    expect(cards.nth(0)).to_contain_text("Kenya's inflation rose by 1.1 percentage points")
    expect(cards.nth(1)).to_contain_text("Nigeria's inflation trended up by 1.24")

"""Journey: run an investigation from selections and see the results (#34)."""

from playwright.sync_api import Page, expect
from support import (
    BANNER,
    finding_cards,
    open_workspace,
    run_button,
    select_kenya_inflation,
    use_scenario,
    wait_for_results,
)


def test_an_analyst_runs_an_investigation_from_selections_and_sees_the_results(page: Page):
    # A two-second Gemini reply keeps the progress steps on screen long enough to see.
    use_scenario(page, "run_slow")
    open_workspace(page)

    select_kenya_inflation(page)
    expect(run_button(page)).to_be_enabled()
    run_button(page).click()

    expect(page.get_by_role("heading", name="Running the investigation")).to_be_visible()
    expect(page.get_by_text("Starting the investigation")).to_be_visible()

    wait_for_results(page)
    expect(finding_cards(page).first).to_be_visible()
    expect(page.get_by_role("img", name="Trend").first).to_be_visible()
    expect(page.get_by_role("table").first).to_be_visible()
    expect(page.get_by_text(BANNER)).to_be_visible()

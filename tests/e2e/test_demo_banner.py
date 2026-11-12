"""Journey: demo data is identifiable on every page (#35)."""

import uuid

from playwright.sync_api import Page, expect
from support import (
    BANNER,
    open_workspace,
    run_question,
    unique_question,
    use_scenario,
    wait_for_results,
)


def test_the_sample_data_banner_with_its_date_shows_on_every_page(page: Page):
    use_scenario(page, "run_success")
    open_workspace(page)
    expect(page.get_by_text(BANNER)).to_be_visible()

    run_question(page, unique_question())
    wait_for_results(page)
    expect(page.get_by_text(BANNER)).to_be_visible()

    page.goto(f"/investigations/{uuid.uuid4()}")
    expect(page.get_by_role("heading", name="Not found")).to_be_visible()
    expect(page.get_by_text(BANNER)).to_be_visible()

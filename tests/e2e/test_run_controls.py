"""Journeys: the run form's controls (#30) and history navigation (#23), end to end (#35)."""

import json

from playwright.sync_api import Page, expect
from support import (
    INVESTIGATION_URL,
    ask,
    history_entry,
    open_workspace,
    run_button,
    run_question,
    token,
    unique_question,
    use_scenario,
    wait_for_results,
)


def saved_with(page: Page, question: str) -> list[dict]:
    """The saved investigations whose title carries this test's token, from the API."""
    body = json.loads(page.request.get("/api/investigations?limit=100").text())
    return [item for item in body["items"] if token(question) in item["title"]]


def test_enter_submits_the_question(page: Page):
    use_scenario(page, "run_success")
    open_workspace(page)

    ask(page, unique_question())
    page.get_by_label("Ask a question").press("Enter")

    wait_for_results(page)


def test_shift_enter_adds_a_new_line_without_submitting(page: Page):
    open_workspace(page)
    box = page.get_by_label("Ask a question")

    box.fill("first line")
    box.press("Shift+Enter")
    box.press_sequentially("second line")

    expect(box).to_have_value("first line\nsecond line")
    expect(page).not_to_have_url(INVESTIGATION_URL)
    expect(page.get_by_role("heading", name="Running the investigation")).to_have_count(0)


def test_the_run_button_is_disabled_with_a_hint_until_there_is_a_question_or_selection(page: Page):
    open_workspace(page)
    hint = page.get_by_text("Type a question, or choose an indicator, countries and a period")

    expect(run_button(page)).to_be_disabled()
    expect(hint).to_be_visible()

    ask(page, "How did inflation change in Kenya?")
    expect(run_button(page)).to_be_enabled()
    expect(hint).to_be_hidden()

    ask(page, "   ")
    expect(run_button(page)).to_be_disabled()
    expect(hint).to_be_visible()


def test_double_clicking_run_creates_exactly_one_investigation(page: Page):
    use_scenario(page, "run_slow")
    question = unique_question()
    open_workspace(page)

    ask(page, question)
    run_button(page).dblclick()
    wait_for_results(page)

    assert len(saved_with(page, question)) == 1


def test_cancel_shows_cancelled_and_the_history_shows_the_run_as_failed(page: Page):
    use_scenario(page, "run_slow")
    question = unique_question()
    open_workspace(page)

    run_question(page, question)
    page.get_by_role("button", name="Cancel").click()

    expect(page.get_by_text("The investigation was stopped before it finished")).to_be_visible()
    # The server notices the closed stream and saves the run as failed; wait for that.
    page.wait_for_function(
        """async (token) => {
            const response = await fetch("/api/investigations?limit=100");
            const items = (await response.json()).items;
            return items.some((i) => i.title.includes(token) && i.status === "failed");
        }""",
        arg=token(question),
    )
    page.reload()
    entry = history_entry(page, question)
    expect(entry).to_be_visible()
    expect(entry).to_contain_text("Failed")
    expect(entry).to_contain_text("Cancelled")


def test_back_returns_to_the_first_investigation_with_its_address(page: Page):
    use_scenario(page, "run_success")
    first, second = unique_question(), unique_question()
    open_workspace(page)
    run_question(page, first)
    first_url = wait_for_results(page)
    page.get_by_role("link", name="New investigation").click()
    run_question(page, second)
    wait_for_results(page)
    page.get_by_role("link", name="New investigation").click()
    expect(page.get_by_text("Ask a question or pick a selection")).to_be_visible()

    history_entry(page, first).click()
    expect(page.get_by_role("heading", name=first)).to_be_visible()
    history_entry(page, second).click()
    expect(page.get_by_role("heading", name=second)).to_be_visible()
    page.go_back()

    expect(page.get_by_role("heading", name=first)).to_be_visible()
    expect(page).to_have_url(first_url)

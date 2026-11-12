"""Helpers shared by the end-to-end tests: how an analyst drives the workspace."""

import re
import uuid

from playwright.sync_api import Page, expect

BANNER = re.compile(r"Sample data from \d{4}-\d{2}-\d{2}\. Not live economic data\.")
INVESTIGATION_URL = re.compile(r"/investigations/[0-9a-f-]{36}$")
INFLATION = "Inflation, end of period consumer prices (Annual % change) (%, annual)"
QUESTION = "How did inflation change in Kenya and Nigeria from 2015 to 2023?"


def use_scenario(page: Page, scenario: str) -> None:
    """Make the stubbed Gemini replay ``scenario`` for every request this page sends."""
    page.context.set_extra_http_headers({"X-Stub-Scenario": scenario})


def unique_question(text: str = QUESTION) -> str:
    """A question no other test uses, so a test finds its own history entry."""
    return f"[{uuid.uuid4().hex[:8]}] {text}"


def token(question: str) -> str:
    return question.split("]")[0].strip("[")


def open_workspace(page: Page) -> None:
    page.goto("/")
    expect(page.get_by_role("heading", name="History")).to_be_visible()


def ask(page: Page, question: str) -> None:
    page.get_by_label("Ask a question").fill(question)


def run_button(page: Page):
    return page.get_by_role("button", name="Run investigation")


def run_question(page: Page, question: str) -> None:
    """Type ``question`` and click Run investigation."""
    ask(page, question)
    run_button(page).click()


def select_kenya_inflation(page: Page, start: str = "2015", end: str = "2023") -> None:
    """Pick one country, one indicator and a period in the selection panel."""
    page.get_by_label("Indicator", exact=True).select_option(label=INFLATION)
    page.get_by_role("checkbox", name="Kenya (KEN)").check()
    expect(page.get_by_label("From", exact=True)).to_be_enabled()
    page.get_by_label("From", exact=True).select_option(start)
    expect(page.get_by_label("From", exact=True)).to_have_value(start)
    page.get_by_label("To", exact=True).select_option(end)
    expect(page.get_by_label("To", exact=True)).to_have_value(end)


def wait_for_results(page: Page) -> str:
    """Wait until the results page for a saved investigation is open; returns its URL."""
    expect(page).to_have_url(INVESTIGATION_URL, timeout=30_000)
    expect(page.get_by_role("heading", name="Observed facts")).to_be_visible()
    return page.url


def finding_cards(page: Page):
    """The finding cards on the results page; each is an article."""
    return page.get_by_role("article")


def finding_texts(page: Page) -> list[str]:
    return [" ".join(text.split()) for text in finding_cards(page).all_inner_texts()]


def history_entry(page: Page, question: str):
    """The sidebar link of the investigation asked as ``question``."""
    return page.get_by_role("link", name=token(question))

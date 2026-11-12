"""The selection panel pages, rendered with a fake ``DataService``."""

import os
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from selection_helpers import COUNTRIES, EXTRA, FakeDataService, entry
from test_web import Page, text

from backend.main import create_app
from backend.settings import Settings
from copilot_core.schemas import Country


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def make_client(service=None):
    app = create_app(Settings())
    app.state.data_service = service or FakeDataService()
    return TestClient(app)


def post(client, fields):
    return client.post(
        "/partials/selection",
        content=urlencode(fields, doseq=True),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )


def test_workspace_renders_the_panel_in_the_selection_aside():
    page = Page(make_client().get("/").text)

    aside = page.find("aside", aria_label="Selection")
    form = page.find("form", id="selection-form")
    assert "Indicator" in text(aside)
    assert form.attrs["hx-post"] == "/partials/selection"
    assert form.attrs["hx-trigger"] == "change"
    assert "hx-get" not in form.attrs
    assert page.find("input", id="country-KEN").attrs["name"] == "country"
    assert [text(o) for o in page.find_all("option") if o.attrs["value"] == "INF"] == [
        "Inflation (%, annual)"
    ]


def test_every_control_has_a_label():
    page = Page(make_client().get("/").text)
    labelled = {label.attrs.get("for") for label in page.find_all("label")}

    for control in page.elements:
        if control.tag in {"select", "input"} and control.attrs.get("type") != "hidden":
            assert control.attrs["id"] in labelled, control.attrs


def test_a_disabled_country_shows_its_reason_as_text():
    page = Page(post(make_client(), {"indicator": "INF"}).text)

    assert "disabled" in page.find("input", id="country-SSD").attrs
    assert text(page.find("span", id="reason-SSD")) == "No data for Inflation"
    assert page.find("input", id="country-SSD").attrs["aria-describedby"] == "reason-SSD"


def test_the_ninth_country_leaves_eight_checked_and_shows_the_limit():
    many = [*COUNTRIES, *EXTRA]
    coverage = [entry(c.code, "INF", "2000", "2020") for c in many]
    client = make_client(FakeDataService(countries=many, coverage=coverage))

    response = post(client, {"indicator": "INF", "country": [c.code for c in many[:9]]})

    page = Page(response.text)
    checked = [e for e in page.find_all("input", type="checkbox") if "checked" in e.attrs]
    assert len(checked) == 8
    assert "At most 8 countries can be selected" in response.text


def test_period_options_are_limited_by_coverage():
    page = Page(post(make_client(), {"indicator": "INF", "country": ["GHA"]}).text)

    years = [text(o) for o in page.find_all("option") if o.attrs["value"].isdigit()]
    assert set(years) == {str(y) for y in range(2000, 2023)}


def test_the_limiting_country_is_named():
    page = Page(post(make_client(), {"indicator": "INF", "country": ["EGY", "GHA"]}).text)

    assert "Ghana limits the start to 2000." in text(page.find("form"))


def test_removed_countries_are_named():
    response = post(make_client(), {"indicator": "INF", "country": ["KEN", "SSD"], "start": "2000"})

    assert "Removed South Sudan: no data for Inflation." in response.text
    assert "checked" not in Page(response.text).find("input", id="country-SSD").attrs


def test_start_after_end_shows_an_error():
    response = post(
        make_client(), {"indicator": "INF", "country": ["KEN"], "start": "2010", "end": "2005"}
    )

    assert "The start period (2010) is after the end period (2005)." in response.text
    assert "data-valid-selection" not in response.text


def test_a_valid_selection_is_marked_and_held_in_the_fields():
    response = post(
        make_client(), {"indicator": "INF", "country": ["KEN"], "start": "2000", "end": "2010"}
    )
    page = Page(response.text)

    assert page.find("form").attrs["data-valid-selection"] == "true"
    option = [o for o in page.find_all("option") if o.attrs["value"] == "2010"][-1]
    assert "selected" in option.attrs


def test_an_incomplete_selection_says_what_is_missing():
    page = Page(post(make_client(), {}).text)

    assert "Choose at least one country." in text(page.find("form"))


def test_coverage_error_shows_a_retry_button_and_the_page_still_renders():
    client = make_client(FakeDataService(fail=True))

    response = client.get("/")

    assert response.status_code == 200
    page = Page(response.text)
    assert "data service is unavailable" in text(page.find("aside", aria_label="Selection"))
    retry = [b for b in page.find_all("button") if text(b) == "Retry"]
    assert retry[0].attrs["hx-post"] == "/partials/selection"
    assert page.find("main", aria_label="Workspace")


def test_submitted_script_in_a_field_is_escaped():
    payload = "<script>alert(1)</script>"
    response = post(make_client(), {"indicator": payload, "country": [payload], "start": payload})
    assert payload not in response.text

    named = FakeDataService(countries=[Country(code="KEN", name=payload, region=None)])
    response = make_client(named).get("/")
    assert payload not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_the_panel_is_not_in_the_openapi_schema():
    assert "/partials/selection" not in make_client().app.openapi()["paths"]


def test_the_demo_data_serves_the_panel():
    page = Page(TestClient(create_app(Settings())).get("/").text)

    assert page.find("input", id="country-KEN")

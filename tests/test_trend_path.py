"""The thin end-to-end path: select country and indicator -> trend -> chart -> saved.

Runs on the tiny fixture with no Gemini. Saving needs Postgres and is skipped
without ``DATABASE_URL``.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.main import create_app
from backend.settings import Settings
from backend.web import chart_points
from tests.helpers import make_series

TINY = Path(__file__).resolve().parent / "fixtures" / "tiny"
SELECTION = {"country": "KEN", "indicator": "PCPIPCH", "start": "2018", "end": "2025"}


@pytest.fixture
def client():
    return TestClient(create_app(Settings(data_dir=TINY, database_url=None)))


def test_workspace_offers_countries_and_supported_indicators(client):
    page = client.get("/").text
    assert '<option value="TZA"' in page
    assert '<option value="PCPIPCH">' in page
    assert "NY.GDP.MKTP.CD" not in page


def test_trend_partial_shows_chart_numbers_caveats_and_save_form(client):
    response = client.get("/partials/trend", params=SELECTION)
    assert response.status_code == 200
    html = response.text
    assert "<svg" in html and "<polyline" in html
    assert "percentage points per year" in html
    assert "2023: the source row has no value" in html
    assert 'hx-post="/partials/investigations"' in html
    assert "Demo mode uses a bundled sample snapshot" in html


def test_trend_partial_reports_bad_input(client):
    response = client.get("/partials/trend", params={**SELECTION, "country": "XXX"})
    assert response.status_code == 422
    assert "Unknown country code: &#39;XXX&#39;" in response.text


def test_missing_values_break_the_chart_line():
    lines = chart_points(make_series([1.0, 2.0, None, 3.0, 4.0]))
    assert len(lines) == 2 and all(len(line) == 2 for line in lines)


def test_save_without_a_database_reports_503(client):
    response = client.post("/partials/investigations", data={**SELECTION, "title": "Kenya"})
    assert response.status_code == 503
    assert "database is unavailable" in response.text


def test_select_trend_chart_and_save(empty_table):
    url = SecretStr(empty_table.render_as_string(hide_password=False))
    client = TestClient(create_app(Settings(data_dir=TINY, database_url=url)))

    assert client.get("/partials/trend", params=SELECTION).status_code == 200
    saved = client.post("/partials/investigations", data={**SELECTION, "title": "Kenya CPI"})
    assert saved.status_code == 200
    assert "Saved “Kenya CPI”" in saved.text

    (item,) = client.get("/api/investigations").json()["items"]
    investigation = client.get(f"/api/investigations/{item['id']}").json()
    assert investigation["title"] == "Kenya CPI"
    assert investigation["status"] == "succeeded"
    assert investigation["result"]["series"][0]["points"][5] == {"period": "2023", "value": None}
    assert investigation["result"]["findings"][0]["kind"] == "trend"
    assert investigation["result"]["interpretation"] is None

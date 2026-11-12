"""Tests for the server-rendered workspace, static files and the contract."""

import hashlib
import os
import re
import socket
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

from backend.main import create_app
from backend.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "backend" / "static"
VENDOR = STATIC / "vendor"
CONTRACT = ROOT / "api" / "openapi.yaml"
PRODUCT_NAME = "African Economic Intelligence Copilot"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    # Isolate settings from the developer's shell and any local .env file.
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def client():
    return TestClient(create_app(Settings()))


class Element:
    def __init__(self, tag: str, attrs: dict[str, str | None]):
        self.tag = tag
        self.attrs = attrs
        self.text = ""


class Page(HTMLParser):
    """Collects every element with its attributes and the text inside it."""

    VOID = {"meta", "link", "br", "img", "input", "hr", "source"}

    def __init__(self, html: str):
        super().__init__()
        self.elements: list[Element] = []
        self._open: list[Element] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = Element(tag, dict(attrs))
        self.elements.append(element)
        if tag not in self.VOID:
            self._open.append(element)

    def handle_endtag(self, tag):
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i].tag == tag:
                del self._open[i:]
                break

    def handle_data(self, data):
        for element in self._open:
            element.text += data

    def find_all(self, tag: str, **attrs: str) -> list[Element]:
        return [
            e
            for e in self.elements
            if e.tag == tag and all(e.attrs.get(k.replace("_", "-")) == v for k, v in attrs.items())
        ]

    def find(self, tag: str, **attrs: str) -> Element:
        found = self.find_all(tag, **attrs)
        assert len(found) == 1, f"expected one <{tag} {attrs}>, found {len(found)}"
        return found[0]


def text(element: Element) -> str:
    return " ".join(element.text.split())


# The shell


def test_workspace_returns_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"


def test_workspace_has_header_sidebar_and_main(client):
    page = Page(client.get("/").text)

    header = page.find("header")
    assert PRODUCT_NAME in text(header)
    assert text(page.find("h1")) == PRODUCT_NAME

    link = page.find("a", href="/")
    assert text(link) == "New investigation"
    assert "button" in link.attrs["class"].split()
    assert "New investigation" in text(header)

    sidebar = page.find("aside", aria_label="Selection")
    for label in ("Countries", "Indicator", "From", "To"):
        assert label in text(sidebar)

    main = page.find("main", aria_label="Workspace")
    assert "Sample data from 2026-11-11. Not live economic data." in text(
        page.find("div", id=None, **{"data-mode": "demo"})
    )
    assert "Ask a question or pick a selection to start an investigation." in text(main)


def test_workspace_loads_vendored_htmx(client):
    page = Page(client.get("/").text)
    sources = [s.attrs["src"] for s in page.find_all("script") if s.attrs.get("src")]

    htmx = [
        src for src in sources if re.fullmatch(r"/static/vendor/htmx-2\.\d+\.\d+\.min\.js", src)
    ]
    assert len(htmx) == 1, sources

    response = client.get(htmx[0])
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.content == (VENDOR / htmx[0].rsplit("/", 1)[1]).read_bytes()


def test_workspace_loads_its_stylesheet(client):
    page = Page(client.get("/").text)
    stylesheet = page.find("link", rel="stylesheet")

    response = client.get(stylesheet.attrs["href"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_workspace_loads_nothing_from_another_origin(client):
    page = Page(client.get("/").text)

    for element in page.elements:
        for name in ("src", "href", "action", "hx-get", "hx-post"):
            url = element.attrs.get(name)
            if url is None:
                continue
            assert url.startswith("/") and not url.startswith("//"), (element.tag, name, url)


def test_layout_stacks_the_sidebar_below_768px():
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    assert re.search(r"\.layout\s*\{[^}]*flex-direction:\s*row", css)
    media = re.search(r"@media \(max-width: 767\.98px\) \{(.*?)\n\}", css, re.S)
    assert media, "no narrow-screen media query"
    assert re.search(r"\.layout\s*\{[^}]*flex-direction:\s*column", media.group(1))


def test_workspace_renders_without_database_gemini_or_network(monkeypatch):
    connect = socket.socket.connect

    def loopback_only(sock, address, *args, **kwargs):
        # The event loop opens a loopback socket pair on Windows; anything
        # else would be a call to Postgres, Gemini or the internet.
        if not (isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}):
            raise AssertionError(f"the page tried to connect to {address!r}")
        return connect(sock, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    settings = Settings()
    assert settings.database_url is None
    assert not any("GEMINI" in name or "GOOGLE" in name for name in os.environ)

    response = TestClient(create_app(settings)).get("/")

    assert response.status_code == 200
    assert PRODUCT_NAME in response.text


def test_rendered_settings_are_escaped():
    payload = "<script>alert(1)</script>"
    response = TestClient(create_app(Settings(app_name=payload))).get("/")
    page = Page(response.text)

    assert response.status_code == 200
    assert payload not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert text(page.find("h1")) == payload
    inline = [s for s in page.find_all("script") if not s.attrs.get("src")]
    assert all(s.attrs.get("type") == "application/json" for s in inline)  # data, not code


def test_unknown_static_file_returns_404(client):
    assert client.get("/static/does-not-exist.js").status_code == 404


# The contract


def test_html_routes_and_static_files_stay_out_of_the_schema(client):
    paths = client.app.openapi()["paths"]

    assert paths, "the schema has no paths"
    leaked = [p for p in paths if p != "/health" and not p.startswith("/api/")]
    assert leaked == []


def test_openapi_contract_is_valid():
    spec, _ = read_from_filename(str(CONTRACT))

    validate(spec)


def test_contract_validator_rejects_an_invalid_contract():
    spec, _ = read_from_filename(str(CONTRACT))
    del spec["info"]

    with pytest.raises(OpenAPIValidationError):
        validate(spec)


# Vendored files


VENDOR_ROW = re.compile(
    r"^\| `(?P<file>[^`]+)` \| (?P<version>[^|]+?) \| (?P<url>https://\S+) \| `(?P<sha>[0-9a-f]{64})` \|$",
    re.M,
)
NOT_VENDORED = {"README.md", ".gitattributes"}


def vendor_entries() -> dict[str, dict[str, str]]:
    readme = (VENDOR / "README.md").read_text(encoding="utf-8")
    return {m["file"]: m.groupdict() for m in VENDOR_ROW.finditer(readme)}


def test_every_vendored_file_has_an_entry():
    files = {p.name for p in VENDOR.iterdir() if p.is_file() and p.name not in NOT_VENDORED}
    entries = vendor_entries()

    assert files, "no vendored files"
    assert files - entries.keys() == set(), "vendored files without an entry"
    assert entries.keys() - files == set(), "entries without a vendored file"


@pytest.mark.parametrize("name", sorted(vendor_entries()))
def test_vendored_file_matches_its_recorded_checksum(name):
    entry = vendor_entries()[name]
    digest = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()

    assert digest == entry["sha"], f"{name} differs from its entry in vendor/README.md"
    # The exact version is in the file name and the source URL is pinned.
    version = re.search(r"\d+\.\d+\.\d+", name).group(0)
    assert version in entry["version"]
    assert version in entry["url"]

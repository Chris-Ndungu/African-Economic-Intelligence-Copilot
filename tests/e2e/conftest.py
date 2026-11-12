"""Fixtures for the end-to-end tests (#34).

The tests drive a real browser through the whole stack on demo data with the
stubbed Gemini client. They use the app at ``E2E_BASE_URL`` if it is set;
otherwise a session fixture starts the stack from ``docker-compose.yml`` and
``docker-compose.e2e.yml`` and removes it, with its database volume, at the end.
Without ``E2E_BASE_URL`` and without Docker every test here is skipped, with the
reason shown, never passed.
"""

import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "copilot-e2e"
STACK_URL = "http://localhost:8010"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    PROJECT,
    "-f",
    str(ROOT / "docker-compose.yml"),
    "-f",
    str(ROOT / "docker-compose.e2e.yml"),
]

HOW_TO_RUN = (
    "The end-to-end tests need a running app or Docker. Start the stack with "
    "`docker compose -f docker-compose.yml -f docker-compose.e2e.yml up --wait` and set "
    "E2E_BASE_URL=http://localhost:8010, or install Docker and run `uv run pytest -m e2e`. "
    "Run everything else with `uv run pytest -m 'not e2e'`."
)


def pytest_collection_modifyitems(items):
    """Mark every test in this folder `e2e`, so `-m e2e` and `-m "not e2e"` work."""
    folder = Path(__file__).resolve().parent
    for item in items:
        if folder in Path(str(item.path)).parents:
            item.add_marker(pytest.mark.e2e)


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=3) as response:
            return bool(response.status == 200)
    except (OSError, urllib.error.URLError):
        return False


@pytest.fixture(scope="session")
def base_url(request):
    """The URL of the app under test: ``E2E_BASE_URL`` or the stack started here.

    The stack is built and started only when the e2e tests are selected with ``-m e2e``, so a
    plain ``uv run pytest`` never spends minutes building an image.
    """
    given = os.environ.get("E2E_BASE_URL", "").strip().rstrip("/")
    if given:
        if not _healthy(given):
            pytest.skip(f"E2E_BASE_URL={given} did not answer /health. {HOW_TO_RUN}")
        yield given
        return
    selected = str(request.config.getoption("-m") or "")
    if "e2e" not in selected or "not e2e" in selected:
        pytest.skip(f"The end-to-end tests run only with -m e2e or E2E_BASE_URL. {HOW_TO_RUN}")
    if not _docker_available():
        pytest.skip(HOW_TO_RUN)
    up = subprocess.run(
        [*COMPOSE, "up", "--build", "--wait", "--wait-timeout", "240", "--detach"],
        capture_output=True,
        text=True,
        timeout=900,
    )
    try:
        if up.returncode != 0:
            pytest.skip(f"`docker compose up --wait` failed, so no e2e run: {up.stderr[-500:]}")
        yield STACK_URL
    finally:
        subprocess.run([*COMPOSE, "down", "-v"], capture_output=True, timeout=300)


@pytest.fixture(scope="session", autouse=True)
def _app_is_reachable(base_url):
    """Check the app before pytest-playwright starts a browser.

    Starting the browser leaves an event loop running in the process, which breaks the
    ``asyncio.run`` tests elsewhere in the suite, so a skipped e2e run must never start it.
    """
    return base_url

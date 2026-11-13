"""Rate limits on investigation runs (#60).

The route tests use an in-memory repository and attempt store with a fake
clock; the shared Postgres counts are checked on a real database and skipped,
with the reason, when ``DATABASE_URL`` is not set.
"""

import os
import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from memory_repository import MemoryRepository
from sqlalchemy import text

from backend.main import create_app
from backend.settings import Settings
from copilot_core.llm import StubLLMClient
from copilot_core.rate_limit import (
    MemoryAttemptStore,
    PostgresAttemptStore,
    RateLimitedError,
    RateLimits,
    RunLimiter,
    client_key,
)

QUESTION = {"question": "How did inflation change in Kenya from 2015 to 2023?"}
FORM = {"Content-Type": "application/x-www-form-urlencoded"}
FORM_BODY = "question=How+did+inflation+change+in+Kenya+from+2015+to+2023"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Spy:
    """Counts every call made to the language model client."""

    def __init__(self, inner) -> None:
        self.inner, self.calls = inner, 0

    def __getattr__(self, name):
        attribute = getattr(self.inner, name)
        if not callable(attribute):
            return attribute

        def counted(*args, **kwargs):
            self.calls += 1
            return attribute(*args, **kwargs)

        return counted


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("COPILOT_") or name == "DATABASE_URL":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def make_app(per_client=2, daily=100, hops=0, clock=None, **settings):
    app = create_app(Settings(gemini_api_key="test-key", trusted_proxy_hops=hops, **settings))
    app.state.repository = MemoryRepository()
    app.state.llm = Spy(StubLLMClient("run_success"))
    app.state.run_limiter = RunLimiter(
        MemoryAttemptStore(),
        RateLimits(per_client_limit=per_client, daily_limit=daily),
        clock or Clock(),
    )
    return app


def test_a_run_over_the_per_ip_limit_is_429_with_retry_after_and_no_gemini_call():
    app = make_app(per_client=1)
    with TestClient(app) as client:
        assert client.post("/api/investigations/run", json=QUESTION).status_code == 200
        calls = app.state.llm.calls
        assert calls > 0
        refused = client.post("/api/investigations/run", json=QUESTION)
    assert refused.status_code == 429
    body = refused.json()
    assert body["code"] == "rate_limited"
    assert body["service"] is None and body["details"] == []
    assert "limit of 1 investigations per hour" in body["message"]
    assert int(refused.headers["retry-after"]) >= 1
    assert app.state.llm.calls == calls


def test_the_streamed_run_endpoint_is_limited_too():
    app = make_app(per_client=1)
    with TestClient(app) as client:
        assert client.post("/api/investigations/runs", json=QUESTION).status_code == 202
        refused = client.post("/api/investigations/runs", json=QUESTION)
    assert refused.status_code == 429
    assert "retry-after" in refused.headers
    assert len(app.state.repository.items) == 1


def test_the_html_run_route_applies_the_same_limit_and_shows_the_message():
    app = make_app(per_client=1)
    with TestClient(app) as client:
        assert (
            client.post("/partials/investigations/run", content=FORM_BODY, headers=FORM).status_code
            == 200
        )
        refused = client.post("/partials/investigations/run", content=FORM_BODY, headers=FORM)
        # The JSON API shares the count: neither path bypasses the other.
        via_api = client.post("/api/investigations/runs", json=QUESTION)
    assert refused.status_code == 429
    assert "You have reached the limit of 1 investigations per hour" in refused.text
    assert int(refused.headers["retry-after"]) >= 1
    assert via_api.status_code == 429
    assert len(app.state.repository.items) == 1


def test_the_daily_total_limit_applies_across_clients():
    app = make_app(per_client=50, daily=3, hops=1)
    with TestClient(app) as client:
        for number in range(3):
            headers = {"X-Forwarded-For": f"10.0.0.{number}"}
            assert (
                client.post("/api/investigations/runs", json=QUESTION, headers=headers).status_code
                == 202
            )
        refused = client.post(
            "/api/investigations/runs", json=QUESTION, headers={"X-Forwarded-For": "10.0.0.99"}
        )
        html = client.post(
            "/partials/investigations/run",
            content=FORM_BODY,
            headers={**FORM, "X-Forwarded-For": "10.0.0.98"},
        )
    assert refused.status_code == 429 and "daily limit of 3" in refused.json()["message"]
    assert html.status_code == 429 and "daily limit of 3" in html.text


def test_the_limit_resets_after_the_window():
    clock = Clock()
    app = make_app(per_client=1, clock=clock)
    with TestClient(app) as client:
        assert client.post("/api/investigations/runs", json=QUESTION).status_code == 202
        refused = client.post("/api/investigations/runs", json=QUESTION)
        assert refused.status_code == 429
        wait = int(refused.headers["retry-after"])
        clock.advance(wait - 1)
        assert client.post("/api/investigations/runs", json=QUESTION).status_code == 429
        clock.advance(2)
        assert client.post("/api/investigations/runs", json=QUESTION).status_code == 202


def test_a_client_supplied_forwarded_header_cannot_bypass_the_limit():
    # Behind Google's front end (one hop) the last entry is the real client;
    # the entries before it are whatever the client sent.
    app = make_app(per_client=1, hops=1)
    with TestClient(app) as client:
        first = client.post(
            "/api/investigations/runs",
            json=QUESTION,
            headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"},
        )
        spoofed = client.post(
            "/api/investigations/runs",
            json=QUESTION,
            headers={"X-Forwarded-For": "2.2.2.2, 9.9.9.9"},
        )
        other = client.post(
            "/api/investigations/runs",
            json=QUESTION,
            headers={"X-Forwarded-For": "1.1.1.1, 8.8.8.8"},
        )
    assert first.status_code == 202
    assert spoofed.status_code == 429
    assert other.status_code == 202


def test_without_a_trusted_proxy_the_header_is_ignored():
    app = make_app(per_client=1, hops=0)
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/investigations/runs", json=QUESTION, headers={"X-Forwarded-For": "1.1.1.1"}
            ).status_code
            == 202
        )
        spoofed = client.post(
            "/api/investigations/runs", json=QUESTION, headers={"X-Forwarded-For": "2.2.2.2"}
        )
    assert spoofed.status_code == 429


def test_reading_listing_and_exporting_are_not_limited():
    app = make_app(per_client=1)
    with TestClient(app) as client:
        created = client.post("/api/investigations/runs", json=QUESTION).json()
        assert client.post("/api/investigations/runs", json=QUESTION).status_code == 429
        for _ in range(5):
            assert client.get("/api/investigations").status_code == 200
            assert client.get(f"/api/investigations/{created['id']}").status_code == 200
            assert client.get(f"/investigations/{created['id']}").status_code == 200
            assert client.get("/partials/history").status_code == 200
            # A pending run cannot be exported (409), which is not a rate limit.
            assert client.get(f"/api/investigations/{created['id']}/report").status_code == 409


def test_a_malformed_forwarded_entry_falls_back_to_the_peer():
    app = make_app(per_client=1, hops=1)
    with TestClient(app) as client:
        headers = {"X-Forwarded-For": "not-an-ip"}
        assert (
            client.post("/api/investigations/runs", json=QUESTION, headers=headers).status_code
            == 202
        )
        assert (
            client.post("/api/investigations/runs", json=QUESTION, headers=headers).status_code
            == 429
        )


def test_the_stored_key_is_a_hash_not_the_address():
    key = client_key("203.0.113.7", "salt")
    assert "203.0.113.7" not in key and re.fullmatch(r"[0-9a-f]{64}", key)
    assert client_key("203.0.113.7", "other") != key


def test_the_authenticated_tier_has_a_higher_limit():
    limiter = RunLimiter(
        MemoryAttemptStore(), RateLimits(per_client_limit=1, authenticated_limit=3, daily_limit=50)
    )
    limiter.check("user", "authenticated")
    limiter.check("user", "authenticated")
    limiter.check("user", "authenticated")
    with pytest.raises(RateLimitedError):
        limiter.check("user", "authenticated")
    limiter.check("anon", "anonymous")
    with pytest.raises(RateLimitedError):
        limiter.check("anon", "anonymous")


def test_postgres_counts_are_shared_between_instances_and_old_rows_are_purged(migrated):
    clock = Clock()
    limits = RateLimits(per_client_limit=2, daily_limit=3)
    instance_a = RunLimiter(PostgresAttemptStore(migrated), limits, clock)
    instance_b = RunLimiter(PostgresAttemptStore(migrated), limits, clock)
    ip_key = client_key("203.0.113.7", "s")
    instance_a.check(ip_key)
    instance_b.check(ip_key)
    with pytest.raises(RateLimitedError) as hit:
        instance_a.check(ip_key)
    assert hit.value.kind == "client" and hit.value.retry_after == 3600
    instance_b.check(client_key("198.51.100.2", "s"))
    with pytest.raises(RateLimitedError) as daily:
        instance_a.check(client_key("192.0.2.9", "s"))
    assert daily.value.kind == "daily"
    with migrated.connect() as connection:
        stored = connection.execute(text("select client_hash from run_attempts")).scalars().all()
    assert len(stored) == 3 and all(len(v) == 64 for v in stored)
    assert not any("203.0.113" in v for v in stored)
    clock.advance(86400 + 1)
    instance_a.check(ip_key)
    with migrated.connect() as connection:
        assert connection.execute(text("select count(*) from run_attempts")).scalar() == 1

"""Sliding-window boundaries, IP isolation, test bypass and cross-host errors."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.rate_limit import RateLimitMiddleware, SlidingWindowLimiter


@pytest.fixture
def clock() -> list[float]:
    return [100.0]


def make_app(
    monkeypatch: pytest.MonkeyPatch, clock: list[float], *, enabled: bool | None = True
) -> FastAPI:
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    app = FastAPI()

    @app.api_route("/api/work", methods=["GET", "POST"])
    def work() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(RateLimitMiddleware, enabled=enabled, clock=lambda: clock[0])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://studio.example"],
        allow_methods=["GET", "POST"],
        expose_headers=["Retry-After"],
    )
    return app


def test_limit_returns_retry_after_and_cors(
    monkeypatch: pytest.MonkeyPatch, clock: list[float]
) -> None:
    with TestClient(make_app(monkeypatch, clock)) as client:
        assert client.get("/api/work").status_code == 200
        assert client.post("/api/work").status_code == 200
        response = client.get("/api/work", headers={"Origin": "https://studio.example"})
        assert response.status_code == 429
        assert response.json() == {"error": {
            "code": "RATE_LIMITED",
            "message": "Too many requests. Please wait a moment and try again.",
        }}
        assert response.headers["Retry-After"] == "60"
        assert response.headers["Access-Control-Allow-Origin"] == "https://studio.example"
        assert "Retry-After" in response.headers["Access-Control-Expose-Headers"]
        clock[0] += 60
        assert client.get("/api/work").status_code == 200


def test_window_slides_and_rejections_do_not_extend_it(clock: list[float]) -> None:
    limiter = SlidingWindowLimiter(2, clock=lambda: clock[0])
    assert limiter.retry_after("a") == 0
    clock[0] += 10
    assert limiter.retry_after("a") == 0
    clock[0] += 49.5
    assert limiter.retry_after("a") == 1
    clock[0] += 0.5
    assert limiter.retry_after("a") == 0
    assert limiter.retry_after("a") == 10
    clock[0] += 10
    assert limiter.retry_after("a") == 0


def test_ips_have_separate_budgets_and_stale_entries_expire(clock: list[float]) -> None:
    limiter = SlidingWindowLimiter(1, clock=lambda: clock[0])
    assert limiter.retry_after("a") == 0
    clock[0] += 10
    assert limiter.retry_after("b") == 0
    assert limiter.retry_after("a") == 50
    clock[0] += 50
    assert limiter.retry_after("c") == 0
    assert "a" not in limiter.windows
    assert limiter.retry_after("b") == 10
    clock[0] += 60
    assert limiter.retry_after("d") == 0
    assert list(limiter.windows) == ["d"]


def test_concurrent_requests_share_one_budget() -> None:
    limiter = SlidingWindowLimiter(3, clock=lambda: 100.0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(limiter.retry_after, ["a"] * 20))
    assert results.count(0) == 3
    assert results.count(60) == 17


def test_forwarded_headers_cannot_bypass_client_ip(
    monkeypatch: pytest.MonkeyPatch, clock: list[float]
) -> None:
    app = make_app(monkeypatch, clock)
    with TestClient(app, client=("192.0.2.1", 50000)) as first:
        for ip in ("198.51.100.1", "198.51.100.2"):
            assert first.get("/api/work", headers={"X-Forwarded-For": ip}).status_code == 200
        assert first.get("/api/work", headers={"X-Forwarded-For": "198.51.100.3"}).status_code == 429
    with TestClient(app, client=("192.0.2.2", 50000)) as second:
        assert second.get("/api/work").status_code == 200


def test_health_and_preflight_do_not_consume_budget(
    monkeypatch: pytest.MonkeyPatch, clock: list[float]
) -> None:
    with TestClient(make_app(monkeypatch, clock)) as client:
        for _ in range(4):
            assert client.get("/api/health").status_code == 200
            assert client.options("/api/work", headers={
                "Origin": "https://studio.example",
                "Access-Control-Request-Method": "POST",
            }).status_code == 200
        assert client.get("/api/work").status_code == 200
        assert client.get("/api/work").status_code == 200
        assert client.get("/api/work").status_code == 429
        assert client.get("/api/health").status_code == 200


def test_disabled_under_pytest_by_default(
    monkeypatch: pytest.MonkeyPatch, clock: list[float]
) -> None:
    with TestClient(make_app(monkeypatch, clock, enabled=None)) as client:
        for _ in range(5):
            assert client.get("/api/work").status_code == 200


def test_default_and_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    assert Settings(_env_file=None).rate_limit_per_minute == 30
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "7")
    assert Settings(_env_file=None).rate_limit_per_minute == 7

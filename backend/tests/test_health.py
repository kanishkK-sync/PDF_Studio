"""Tests for GET /api/health and configured CORS origins."""

from runpy import run_path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.core.config import get_settings
from app.main import app

client = TestClient(app)


def test_health_returns_status_and_version() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": get_settings().app_version,
    }


def test_cors_allows_only_the_frontend_origin() -> None:
    allowed = client.get(
        "/api/health", headers={"Origin": "http://localhost:3000"}
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"

    blocked = client.get(
        "/api/health", headers={"Origin": "http://evil.example"}
    )
    assert "access-control-allow-origin" not in blocked.headers


@pytest.mark.parametrize("origins", [
    "https://pdf-studio.example,https://preview.example,http://localhost:3000",
    " , https://pdf-studio.example, ,https://preview.example, http://localhost:3000, ",
])
def test_cors_allows_comma_separated_frontend_origins(
    monkeypatch: pytest.MonkeyPatch, origins: str
) -> None:
    monkeypatch.setenv("FRONTEND_ORIGIN", origins)
    get_settings.cache_clear()
    try:
        # Execute the real app configuration in isolation, without reloading the
        # shared app or starting its lifespan (which would purge real storage).
        configured_client = TestClient(run_path(main.__file__)["app"])
        for origin in (
            "https://pdf-studio.example",
            "https://preview.example",
            "http://localhost:3000",
        ):
            preflight = configured_client.options("/api/health", headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            })
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == origin
            assert "Origin" in preflight.headers["vary"]
            assert set(preflight.headers["access-control-allow-methods"].split(", ")) == {
                "GET", "POST", "DELETE",
            }
            response = configured_client.get("/api/health", headers={"Origin": origin})
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin
            assert "Retry-After" in response.headers["access-control-expose-headers"]

        for origin in ("https://evil.example", "https://preview.example.evil.example", "null"):
            preflight = configured_client.options("/api/health", headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            })
            assert preflight.status_code == 400
            assert "access-control-allow-origin" not in preflight.headers
            response = configured_client.get("/api/health", headers={"Origin": origin})
            assert "access-control-allow-origin" not in response.headers
    finally:
        get_settings.cache_clear()

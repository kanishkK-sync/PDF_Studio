"""Tests for GET /api/health."""

from app.core.config import get_settings
from app.main import app
from fastapi.testclient import TestClient

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
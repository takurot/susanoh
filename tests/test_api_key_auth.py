import pytest
import asyncio
from fastapi.testclient import TestClient

from backend.main import app, reset_runtime_state


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state_and_auth(monkeypatch):
    asyncio.run(reset_runtime_state())
    monkeypatch.delenv("SUSANOH_API_KEYS", raising=False)
    yield


def test_api_access_without_configured_keys_is_allowed():
    response = client.get("/api/v1/stats")
    assert response.status_code == 200


def test_api_access_requires_key_when_configured(monkeypatch):
    monkeypatch.setenv("SUSANOH_API_KEYS", "dev-key")

    response = client.get("/api/v1/stats")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-API-KEY header"


def test_api_access_rejects_invalid_key(monkeypatch):
    monkeypatch.setenv("SUSANOH_API_KEYS", "dev-key")

    response = client.get("/api/v1/stats", headers={"X-API-KEY": "invalid"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


def test_api_access_allows_valid_key(monkeypatch):
    monkeypatch.setenv("SUSANOH_API_KEYS", "dev-key,prod-key")

    response = client.get("/api/v1/stats", headers={"X-API-KEY": "prod-key"})
    assert response.status_code == 200


def test_health_endpoint_is_public_even_when_auth_is_enabled(monkeypatch):
    monkeypatch.setenv("SUSANOH_API_KEYS", "dev-key")

    response = client.get("/")
    assert response.status_code == 200


def test_preflight_options_is_allowed_when_auth_is_enabled(monkeypatch):
    monkeypatch.setenv("SUSANOH_API_KEYS", "dev-key")

    response = client.options(
        "/api/v1/stats",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-methods" in response.headers

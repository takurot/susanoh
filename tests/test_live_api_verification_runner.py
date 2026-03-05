import pytest

from backend.live_api_verification import (
    LiveAPIVerificationConfig,
    load_live_api_verification_config,
    run_live_api_verification,
)


def test_load_live_api_verification_config_requires_base_url():
    with pytest.raises(ValueError, match="SUSANOH_STAGING_BASE_URL"):
        load_live_api_verification_config(
            {
                "SUSANOH_STAGING_PASSWORD": "secret",
            }
        )


def test_load_live_api_verification_config_defaults_username_and_optional_api_key():
    config = load_live_api_verification_config(
        {
            "SUSANOH_STAGING_BASE_URL": "https://staging.example.com",
            "SUSANOH_STAGING_PASSWORD": "secret",
        }
    )
    assert config.username == "admin"
    assert config.api_key is None
    assert config.timeout_seconds == 10.0


@pytest.mark.asyncio
async def test_run_live_api_verification_happy_path(monkeypatch):
    class _Response:
        def __init__(self, payload: dict):
            self._payload = payload
            self.status_code = 200
            self.text = str(payload)

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    client_box = {}

    class _Client:
        def __init__(self, base_url: str, timeout: float):
            self.base_url = base_url
            self.timeout = timeout
            self.calls = []
            client_box["client"] = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, path: str, data=None, json=None, headers=None):
            self.calls.append(
                {"path": path, "data": data, "json": json, "headers": headers or {}}
            )
            if path == "/api/v1/auth/token":
                return _Response({"access_token": "jwt-token", "token_type": "bearer"})
            if path == "/api/v1/analyze":
                return _Response(
                    {
                        "target_id": "live_check_target",
                        "is_fraud": True,
                        "risk_score": 64,
                        "fraud_type": "MONEY_LAUNDERING",
                        "recommended_action": "UNDER_SURVEILLANCE",
                        "reasoning": "Periodic staging live API verification",
                        "evidence_event_ids": ["evt_live_probe"],
                        "confidence": 0.7,
                    }
                )
            raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("backend.live_api_verification.httpx.AsyncClient", _Client)

    config = LiveAPIVerificationConfig(
        base_url="https://staging.example.com/",
        username="admin",
        password="secret",
        api_key="staging-key",
        timeout_seconds=12.5,
    )
    result = await run_live_api_verification(config)

    assert result["ok"] is True
    assert result["target_id"] == "live_check_target"
    assert result["risk_score"] == 64
    analyze_call = client_box["client"].calls[1]
    assert analyze_call["headers"]["Authorization"] == "Bearer jwt-token"
    assert analyze_call["headers"]["X-API-KEY"] == "staging-key"


@pytest.mark.asyncio
async def test_run_live_api_verification_rejects_invalid_response(monkeypatch):
    class _Response:
        def __init__(self, payload: dict):
            self._payload = payload
            self.status_code = 200
            self.text = str(payload)

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def __init__(self, base_url: str, timeout: float):
            self.base_url = base_url
            self.timeout = timeout

        async def post(self, path: str, data=None, json=None, headers=None):
            if path == "/api/v1/auth/token":
                return _Response({"access_token": "jwt-token"})
            if path == "/api/v1/analyze":
                return _Response(
                    {
                        "target_id": "live_check_target",
                        "is_fraud": True,
                        "risk_score": 999,
                        "fraud_type": "MONEY_LAUNDERING",
                        "recommended_action": "BANNED",
                        "reasoning": "invalid score for test",
                        "evidence_event_ids": ["evt_bad"],
                        "confidence": 0.9,
                    }
                )
            raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("backend.live_api_verification.httpx.AsyncClient", _Client)

    config = LiveAPIVerificationConfig(
        base_url="https://staging.example.com/",
        username="admin",
        password="secret",
        api_key=None,
        timeout_seconds=12.5,
    )
    with pytest.raises(RuntimeError, match="risk_score"):
        await run_live_api_verification(config)

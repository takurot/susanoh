import random

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
import backend.mock_server as mock_server

client = TestClient(main_module.app)


@pytest.fixture(autouse=True)
def reset_runtime_state(monkeypatch):
    main_module.reset_runtime_state()
    random.seed(42)
    monkeypatch.setattr(mock_server.random, "choice", lambda seq: seq[0])
    yield


def test_showcase_smurfing_returns_summary():
    resp = client.post("/api/v1/demo/showcase/smurfing")
    assert resp.status_code == 200

    data = resp.json()
    assert data["target_user"] == "user_boss_01"
    assert isinstance(data["triggered_rules"], list)
    assert data["triggered_rules"]
    assert data["withdraw_status_code"] in (423, 403)
    assert data["latest_state"] in ("UNDER_SURVEILLANCE", "BANNED")
    assert isinstance(data["latest_risk_score"], int)
    assert isinstance(data["latest_reasoning"], str)


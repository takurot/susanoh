import random
import asyncio

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
import backend.mock_server as mock_server
from backend.models import ActionDetails, ContextMetadata, GameEventLog

client = TestClient(main_module.app)


@pytest.fixture(autouse=True)
def reset_runtime_state(monkeypatch):
    asyncio.run(main_module.reset_runtime_state())
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
    assert data["analysis_error"] is None


def test_showcase_does_not_increment_blocked_withdrawals():
    resp1 = client.post("/api/v1/demo/showcase/smurfing")
    resp2 = client.post("/api/v1/demo/showcase/smurfing")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert main_module.sm.blocked_withdrawals == 0


def test_showcase_handles_l2_failure(monkeypatch):
    async def _raise_error(_analysis_req):
        raise RuntimeError("forced-l2-failure")

    monkeypatch.setattr(main_module.l2, "analyze", _raise_error)

    resp = client.post("/api/v1/demo/showcase/smurfing")
    assert resp.status_code == 200

    data = resp.json()
    assert data["latest_risk_score"] is None
    assert "L2 analysis failed" in (data["latest_reasoning"] or "")
    assert "forced-l2-failure" in (data["analysis_error"] or "")


def test_showcase_handles_missing_target_event(monkeypatch):
    monkeypatch.setattr(
        main_module.mock,
        "generate_smurfing_events",
        lambda: [
            GameEventLog(
                event_id="evt_missing_target",
                actor_id="user_mule_99",
                target_id="user_other_01",
                action_details=ActionDetails(currency_amount=1234, market_avg_price=100),
                context_metadata=ContextMetadata(recent_chat_log="normal chat"),
            ),
        ],
    )

    resp = client.post("/api/v1/demo/showcase/smurfing")
    assert resp.status_code == 200

    data = resp.json()
    assert data["target_user"] == "user_boss_01"
    assert data["latest_risk_score"] is None
    assert data["latest_state"] == "NORMAL"
    assert "L2 analysis skipped" in (data["analysis_error"] or "")

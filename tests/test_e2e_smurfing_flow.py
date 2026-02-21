import asyncio

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
import backend.mock_server as mock_server
from backend.models import AccountState

client = TestClient(main_module.app)


@pytest.fixture(autouse=True)
def reset_runtime_state(monkeypatch):
    main_module.reset_runtime_state()

    # Make smurfing scenario deterministic for stable E2E assertions.
    mock_server.random.seed(42)
    monkeypatch.setattr(mock_server.random, "choice", lambda seq: seq[0])
    yield


def test_e2e_smurfing_isolation_and_l2_verdict():
    response = client.post("/api/v1/demo/scenario/rmt-smurfing")
    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "rmt-smurfing"
    assert payload["events_sent"] == 8

    target_user = "user_boss_01"
    initial_user_resp = client.get(f"/api/v1/users/{target_user}")
    assert initial_user_resp.status_code == 200
    assert initial_user_resp.json()["state"] == AccountState.RESTRICTED_WITHDRAWAL.value

    trigger_event, screening_result = next(
        (event, result)
        for event, result in reversed(main_module.l1.recent_events)
        if event.target_id == target_user
    )
    analysis_req = main_module.l1.build_analysis_request(
        target_user,
        trigger_event,
        screening_result.triggered_rules,
        main_module.sm.get_or_create(target_user),
    )
    asyncio.run(main_module._run_l2(analysis_req))

    analyses_resp = client.get("/api/v1/analyses")
    assert analyses_resp.status_code == 200
    analyses = analyses_resp.json()
    assert analyses, "L2 analysis result was not stored"

    user_resp = client.get(f"/api/v1/users/{target_user}")
    assert user_resp.status_code == 200
    state = user_resp.json()["state"]
    assert state in {AccountState.UNDER_SURVEILLANCE.value, AccountState.BANNED.value}

    withdraw_resp = client.post(
        "/api/v1/withdraw",
        json={"user_id": target_user, "amount": 1000},
    )
    assert withdraw_resp.status_code in (423, 403)

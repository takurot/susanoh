import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.models import GameEventLog, AccountState, ScreeningResult, AnalysisRequest, UserProfile

@pytest.fixture
def mock_arq_pool(monkeypatch):
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    # Mock app.state.arq_pool
    monkeypatch.setattr(main_module.app.state, "arq_pool", pool)
    return pool

@pytest.fixture(autouse=True)
def reset_state():
    asyncio.run(main_module.sm.reset())
    yield

def test_event_enqueues_l2_task_when_pool_exists(mock_arq_pool, monkeypatch):
    # Mock L1 screening to force it to return a result that needs L2
    mock_result = ScreeningResult(
        screened=True,
        triggered_rules=["R1"],
        recommended_action=AccountState.RESTRICTED_WITHDRAWAL,
        needs_l2=True
    )
    monkeypatch.setattr(main_module.l1, "screen", AsyncMock(return_value=mock_result))
    
    # Mock AnalysisRequest building
    mock_analysis_req = AnalysisRequest(
        trigger_event=GameEventLog(event_id="e_test_async", actor_id="a1", target_id="u1"),
        user_profile=UserProfile(user_id="u1", current_state=AccountState.RESTRICTED_WITHDRAWAL)
    )
    monkeypatch.setattr(main_module.l1, "build_analysis_request", AsyncMock(return_value=mock_analysis_req))
    
    client = TestClient(main_module.app)
    event_data = {
        "event_id": "e_test_async",
        "actor_id": "sender_1",
        "target_id": "target_1",
        "event_type": "TRADE",
        "action_details": {"currency_amount": 1000000},
        "context_metadata": {"actor_level": 1}
    }
    
    response = client.post("/api/v1/events", json=event_data)
    assert response.status_code == 200
    
    # Check if enqueue_job was called
    assert mock_arq_pool.enqueue_job.called
    args, kwargs = mock_arq_pool.enqueue_job.call_args
    assert args[0] == "analyze_l2_task"
    assert args[1] == mock_analysis_req

def test_event_falls_back_to_local_task_when_pool_is_missing(monkeypatch):
    # Ensure arq_pool is None
    monkeypatch.setattr(main_module.app.state, "arq_pool", None)
    
    # Mock _run_l2 to see if it's called
    mock_run_l2 = AsyncMock()
    monkeypatch.setattr(main_module, "_run_l2", mock_run_l2)
    
    client = TestClient(main_module.app)
    # Using a large amount to naturally trigger L1 if it's working
    event_data = {
        "event_id": "e_test_fallback",
        "actor_id": "sender_2",
        "target_id": "target_2",
        "event_type": "TRADE",
        "action_details": {"currency_amount": 2000000},
        "context_metadata": {"actor_level": 1}
    }
    
    response = client.post("/api/v1/events", json=event_data)
    assert response.status_code == 200
    
    # Verify the state changed to RESTRICTED_WITHDRAWAL by L1
    user_resp = client.get("/api/v1/users/target_2")
    assert user_resp.json()["state"] == AccountState.RESTRICTED_WITHDRAWAL.value
    
    # Since we mocked _run_l2, it should have been called (via create_task)
    assert mock_run_l2.called

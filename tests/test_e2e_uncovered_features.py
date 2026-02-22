import asyncio

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
import backend.mock_server as mock_server
from backend.persistence import PersistenceStore


client = TestClient(main_module.app)


def _event_payload(
    *,
    event_id: str,
    actor_id: str,
    target_id: str,
    amount: int,
    market_avg_price: int | None = None,
    recent_chat_log: str | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "event_type": "TRADE",
        "actor_id": actor_id,
        "target_id": target_id,
        "action_details": {
            "currency_amount": amount,
            "market_avg_price": market_avg_price,
        },
        "context_metadata": {
            "actor_level": 2,
            "account_age_days": 1,
            "recent_chat_log": recent_chat_log,
        },
    }


@pytest.fixture
def sqlite_store(tmp_path):
    store = PersistenceStore(f"sqlite:///{tmp_path / 'e2e-uncovered.db'}")
    store.init_schema()
    return store


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch, sqlite_store):
    monkeypatch.setattr(main_module, "persistence_store", sqlite_store)
    main_module.reset_runtime_state()

    # Keep random-based demo behavior deterministic.
    mock_server.random.seed(42)
    monkeypatch.setattr(mock_server.random, "choice", lambda seq: seq[0])
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SUSANOH_API_KEYS", raising=False)
    yield

    if main_module.streamer and main_module.streamer.running:
        asyncio.run(main_module.streamer.stop())
    main_module.streamer = None


def test_e2e_core_api_flow_covers_events_users_release_and_read_models():
    health = client.get("/")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    actor_id = "user_e2e_actor"
    target_id = "user_e2e_target"
    event_id = "evt_e2e_core_001"
    event_response = client.post(
        "/api/v1/events",
        json=_event_payload(
            event_id=event_id,
            actor_id=actor_id,
            target_id=target_id,
            amount=2_000_000,
            market_avg_price=100,
        ),
    )
    assert event_response.status_code == 200
    event_result = event_response.json()
    assert event_result["screened"] is True
    assert set(event_result["triggered_rules"]) >= {"R1", "R3"}

    recent = client.get("/api/v1/events/recent")
    assert recent.status_code == 200
    recent_events = recent.json()
    assert any(event["event_id"] == event_id for event in recent_events)

    user = client.get(f"/api/v1/users/{target_id}")
    assert user.status_code == 200
    current_state = user.json()["state"]
    assert current_state in {"RESTRICTED_WITHDRAWAL", "UNDER_SURVEILLANCE"}

    users = client.get("/api/v1/users")
    assert users.status_code == 200
    user_ids = {row["user_id"] for row in users.json()}
    assert {actor_id, target_id}.issubset(user_ids)

    users_by_state = client.get("/api/v1/users", params={"state": current_state})
    assert users_by_state.status_code == 200
    state_filtered_ids = {row["user_id"] for row in users_by_state.json()}
    assert target_id in state_filtered_ids

    stats = client.get("/api/v1/stats")
    assert stats.status_code == 200
    stats_payload = stats.json()
    assert stats_payload["total_events"] >= 1
    assert stats_payload["l1_flags"] >= 1

    transitions = client.get("/api/v1/transitions")
    assert transitions.status_code == 200
    transition_logs = transitions.json()
    assert any(log["user_id"] == target_id for log in transition_logs)

    graph = client.get("/api/v1/graph")
    assert graph.status_code == 200
    graph_payload = graph.json()
    node_ids = {node["id"] for node in graph_payload["nodes"]}
    assert {actor_id, target_id}.issubset(node_ids)
    assert any(link["source"] == actor_id and link["target"] == target_id for link in graph_payload["links"])

    release = client.post(f"/api/v1/users/{target_id}/release")
    assert release.status_code == 200
    assert release.json()["state"] == "NORMAL"


def test_e2e_analyze_endpoint_and_analysis_listing():
    target_id = "user_e2e_analyze_target"
    analyze_response = client.post(
        "/api/v1/analyze",
        json=_event_payload(
            event_id="evt_e2e_analyze_001",
            actor_id="user_e2e_analyze_actor",
            target_id=target_id,
            amount=500_000,
            market_avg_price=10,
            recent_chat_log="Dで確認しました",
        ),
    )
    assert analyze_response.status_code == 200
    verdict = analyze_response.json()
    assert verdict["target_id"] == target_id
    assert verdict["recommended_action"] in {"NORMAL", "UNDER_SURVEILLANCE", "BANNED"}
    assert 0 <= verdict["risk_score"] <= 100

    analyses = client.get("/api/v1/analyses")
    assert analyses.status_code == 200
    rows = analyses.json()
    assert any(row["target_id"] == target_id for row in rows)


def test_e2e_demo_scenario_variants():
    normal = client.post("/api/v1/demo/scenario/normal")
    assert normal.status_code == 200
    assert normal.json()["scenario"] == "normal"
    assert normal.json()["events_sent"] == 10

    layering = client.post("/api/v1/demo/scenario/layering")
    assert layering.status_code == 200
    assert layering.json()["scenario"] == "layering"
    assert layering.json()["events_sent"] == 3

    unknown = client.post("/api/v1/demo/scenario/does-not-exist")
    assert unknown.status_code == 400
    assert "Unknown scenario" in unknown.json()["detail"]


def test_e2e_demo_streamer_start_and_stop():
    started = client.post("/api/v1/demo/start")
    assert started.status_code == 200
    assert started.json()["status"] == "started"

    already_running = client.post("/api/v1/demo/start")
    assert already_running.status_code == 200
    assert already_running.json()["status"] == "already_running"

    stopped = client.post("/api/v1/demo/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"

    stopped_again = client.post("/api/v1/demo/stop")
    assert stopped_again.status_code == 200
    assert stopped_again.json()["status"] == "stopped"


def test_e2e_api_key_auth_middleware_flow(monkeypatch):
    monkeypatch.setenv("SUSANOH_API_KEYS", "dev-key,prod-key")

    missing = client.get("/api/v1/stats")
    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing X-API-KEY header"

    invalid = client.get("/api/v1/stats", headers={"X-API-KEY": "invalid"})
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Invalid API key"

    valid = client.get("/api/v1/stats", headers={"X-API-KEY": "prod-key"})
    assert valid.status_code == 200

    preflight = client.options(
        "/api/v1/stats",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert "access-control-allow-methods" in preflight.headers

    health = client.get("/")
    assert health.status_code == 200

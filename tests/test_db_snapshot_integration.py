import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.persistence import EventLogRecord, PersistenceStore, UserRecord


client = TestClient(main_module.app)


@pytest.fixture
def sqlite_store(tmp_path):
    store = PersistenceStore(f"sqlite:///{tmp_path / 'integration.db'}")
    store.init_schema()
    return store


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch, sqlite_store):
    main_module.reset_runtime_state()
    monkeypatch.setattr(main_module, "persistence_store", sqlite_store)
    yield


def test_post_event_persists_users_and_event_logs():
    payload = {
        "event_id": "evt_integration_001",
        "event_type": "TRADE",
        "actor_id": "user_actor",
        "target_id": "user_target",
        "action_details": {
            "currency_amount": 2_000_000,
            "market_avg_price": 100,
        },
        "context_metadata": {
            "actor_level": 1,
            "account_age_days": 3,
            "recent_chat_log": "Dで確認",
        },
    }
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code == 200

    with main_module.persistence_store.session() as session:
        assert session.query(UserRecord).count() == 2
        assert session.query(EventLogRecord).count() == 1

        event_row = session.query(EventLogRecord).filter_by(event_id="evt_integration_001").one()
        assert event_row.screened is True
        assert "R1" in event_row.triggered_rules


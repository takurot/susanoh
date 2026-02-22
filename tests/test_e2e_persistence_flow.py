import asyncio
import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
import backend.mock_server as mock_server
from backend.persistence import (
    AnalysisResultRecord,
    AuditLogRecord,
    EventLogRecord,
    PersistenceStore,
    UserRecord,
)


client = TestClient(main_module.app)


@pytest.fixture
def sqlite_store(tmp_path):
    store = PersistenceStore(f"sqlite:///{tmp_path / 'e2e-persistence.db'}")
    store.init_schema()
    return store


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch, sqlite_store):
    monkeypatch.setattr(main_module, "persistence_store", sqlite_store)
    asyncio.run(main_module.reset_runtime_state())

    # Keep scenario generation deterministic for stable E2E assertions.
    mock_server.random.seed(42)
    monkeypatch.setattr(mock_server.random, "choice", lambda seq: seq[0])
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SUSANOH_API_KEYS", raising=False)
    yield


def test_e2e_showcase_smurfing_persists_runtime_snapshot():
    response = client.post("/api/v1/demo/showcase/smurfing")
    assert response.status_code == 200

    payload = response.json()
    assert payload["target_user"] == "user_boss_01"
    assert payload["latest_state"] in {"UNDER_SURVEILLANCE", "BANNED"}
    assert payload["latest_risk_score"] is not None
    assert payload["withdraw_status_code"] in {403, 423}
    assert set(payload["triggered_rules"]) >= {"R1", "R3"}

    with main_module.persistence_store.session() as session:
        assert session.query(UserRecord).count() == 9
        assert session.query(EventLogRecord).count() == 8
        assert session.query(AnalysisResultRecord).count() == 1
        assert session.query(AuditLogRecord).count() >= 2

        target_user = session.query(UserRecord).filter_by(user_id="user_boss_01").one()
        assert target_user.state == payload["latest_state"]

        latest_analysis = session.query(AnalysisResultRecord).filter_by(target_id="user_boss_01").one()
        assert latest_analysis.risk_score == payload["latest_risk_score"]

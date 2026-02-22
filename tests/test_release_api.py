import pytest
from fastapi.testclient import TestClient

from backend.main import app, sm
from backend.models import AccountState


@pytest.fixture(autouse=True)
def reset_state():
    sm.reset()
    yield


client = TestClient(app)


def test_release_restricted_200():
    sm.accounts["u1"] = AccountState.RESTRICTED_WITHDRAWAL
    resp = client.post("/api/v1/users/u1/release")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "u1", "state": AccountState.NORMAL.value}


def test_release_surveillance_200():
    sm.accounts["u1"] = AccountState.UNDER_SURVEILLANCE
    resp = client.post("/api/v1/users/u1/release")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "u1", "state": AccountState.NORMAL.value}


def test_release_normal_400():
    sm.accounts["u1"] = AccountState.NORMAL
    resp = client.post("/api/v1/users/u1/release")
    assert resp.status_code == 400
    assert "current: NORMAL" in resp.json()["detail"]


def test_release_banned_400():
    sm.accounts["u1"] = AccountState.BANNED
    resp = client.post("/api/v1/users/u1/release")
    assert resp.status_code == 400
    assert "current: BANNED" in resp.json()["detail"]

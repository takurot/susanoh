import pytest
from fastapi.testclient import TestClient
from backend.main import app, sm
from backend.models import AccountState


@pytest.fixture(autouse=True)
def reset_state():
    sm.reset()
    yield


client = TestClient(app)


def test_withdraw_normal_200():
    sm.accounts["u1"] = AccountState.NORMAL
    resp = client.post("/api/v1/withdraw", json={"user_id": "u1", "amount": 100})
    assert resp.status_code == 200


def test_withdraw_restricted_423():
    sm.accounts["u1"] = AccountState.RESTRICTED_WITHDRAWAL
    resp = client.post("/api/v1/withdraw", json={"user_id": "u1", "amount": 100})
    assert resp.status_code == 423


def test_withdraw_surveillance_423():
    sm.accounts["u1"] = AccountState.UNDER_SURVEILLANCE
    resp = client.post("/api/v1/withdraw", json={"user_id": "u1", "amount": 100})
    assert resp.status_code == 423


def test_withdraw_banned_403():
    sm.accounts["u1"] = AccountState.BANNED
    resp = client.post("/api/v1/withdraw", json={"user_id": "u1", "amount": 100})
    assert resp.status_code == 403

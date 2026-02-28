import asyncio
import os

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app, reset_runtime_state
from backend.models import AccountState


async def _get_jwt_token(client: AsyncClient) -> str:
    """Obtain a JWT token for admin user to access RBAC-protected endpoints."""
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "password123"},
    )
    assert resp.status_code == 200, f"Failed to get JWT token: {resp.text}"
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_concurrent_event_processing():
    """
    Verify that massively concurrent events for the same target user 
    do not cause duplicate state transitions or corrupt L1 logic.
    """
    await reset_runtime_state()
    user_id = "target_concurrency_01"

    api_key = os.environ.get("SUSANOH_API_KEYS", "test").split(",")[0].strip() or "test"
    headers = {"X-API-KEY": api_key}

    # Send 50 requests concurrently
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as client:
        tasks = []
        for i in range(50):
            payload = {
                "event_id": f"event_concurrent_{i}",
                "timestamp": "2026-02-28T10:00:00Z",
                "event_type": "TRADE",
                "actor_id": f"actor_concurrent_{i}",
                "target_id": user_id,
                "action_details": {
                    "item_id": "gold",
                    "currency_amount": 500_000,
                    "market_avg_price": 5000
                },
                "context_metadata": {
                    "client_ip": "1.1.1.1",
                    "device_id": f"device_{i}",
                    "recent_chat_log": ""
                },
                "risk_score": 0
            }
            tasks.append(client.post("/api/v1/events", json=payload))

        responses = await asyncio.gather(*tasks)

    # Assert they all succeeded
    for resp in responses:
        assert resp.status_code == 200, f"Event post failed: {resp.text}"

    # RBAC-protected endpoints need JWT auth
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as client:
        token = await _get_jwt_token(client)
        auth_headers = {**headers, "Authorization": f"Bearer {token}"}

        # Check the final state
        resp = await client.get(f"/api/v1/users/{user_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["state"] == AccountState.RESTRICTED_WITHDRAWAL.value

        # Check transitions
        resp_trans = await client.get("/api/v1/transitions", headers=auth_headers)
        assert resp_trans.status_code == 200

        transitions = [t for t in resp_trans.json() if t["user_id"] == user_id]

        # There should only be exactly ONE transition for the target user from NORMAL to RESTRICTED_WITHDRAWAL
        assert len(transitions) == 1
        assert transitions[0]["from_state"] == AccountState.NORMAL.value
        assert transitions[0]["to_state"] == AccountState.RESTRICTED_WITHDRAWAL.value

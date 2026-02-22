import pytest
import asyncio

from backend.main import sm
from backend.models import AccountState


@pytest.fixture(autouse=True)
def reset_state():
    asyncio.run(sm.reset())
    yield


@pytest.mark.asyncio
async def test_low_risk_verdict_auto_recovers_to_normal():
    user_id = "u1"
    await sm.get_or_create(user_id)
    await sm.transition(user_id, AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")

    await sm.apply_l2_verdict(user_id, AccountState.NORMAL, risk_score=10)

    assert await sm.get_or_create(user_id) == AccountState.NORMAL


@pytest.mark.asyncio
async def test_low_risk_verdict_auto_recovers_surveillance_to_normal():
    user_id = "u1"
    await sm.get_or_create(user_id)
    await sm.transition(user_id, AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    await sm.transition(user_id, AccountState.UNDER_SURVEILLANCE, "L2", "GEMINI")

    await sm.apply_l2_verdict(user_id, AccountState.NORMAL, risk_score=25)

    assert await sm.get_or_create(user_id) == AccountState.NORMAL

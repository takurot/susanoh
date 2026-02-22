import pytest
from backend.models import AccountState
from backend.state_machine import StateMachine


@pytest.fixture
def sm():
    return StateMachine()


@pytest.mark.asyncio
async def test_get_or_create_default_normal(sm):
    assert await sm.get_or_create("u1") == AccountState.NORMAL


@pytest.mark.asyncio
async def test_valid_transition_normal_to_restricted(sm):
    await sm.get_or_create("u1")
    assert await sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1") is True
    assert await sm.get_or_create("u1") == AccountState.RESTRICTED_WITHDRAWAL


@pytest.mark.asyncio
async def test_valid_transition_full_path(sm):
    await sm.get_or_create("u1")
    assert await sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    assert await sm.transition("u1", AccountState.UNDER_SURVEILLANCE, "L2", "GEMINI")
    assert await sm.transition("u1", AccountState.BANNED, "L2", "GEMINI")
    assert await sm.get_or_create("u1") == AccountState.BANNED


@pytest.mark.asyncio
async def test_invalid_transition_normal_to_banned(sm):
    await sm.get_or_create("u1")
    assert await sm.transition("u1", AccountState.BANNED, "L1", "R1") is False
    assert await sm.get_or_create("u1") == AccountState.NORMAL


@pytest.mark.asyncio
async def test_manual_release(sm):
    await sm.get_or_create("u1")
    await sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    await sm.transition("u1", AccountState.UNDER_SURVEILLANCE, "L2", "GEMINI")
    assert await sm.transition("u1", AccountState.NORMAL, "MANUAL", "OP") is True
    assert await sm.get_or_create("u1") == AccountState.NORMAL


@pytest.mark.asyncio
async def test_auto_recovery_from_restricted_to_normal(sm):
    await sm.get_or_create("u1")
    await sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")

    assert await sm.transition("u1", AccountState.NORMAL, "L2_ANALYSIS", "GEMINI_LOW_RISK") is True
    assert await sm.get_or_create("u1") == AccountState.NORMAL


@pytest.mark.asyncio
async def test_can_withdraw(sm):
    assert await sm.can_withdraw("u1") is True
    await sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    assert await sm.can_withdraw("u1") is False


@pytest.mark.asyncio
async def test_get_stats(sm):
    await sm.get_or_create("u1")
    await sm.get_or_create("u2")
    await sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    stats = await sm.get_stats()
    assert stats["NORMAL"] == 1
    assert stats["RESTRICTED_WITHDRAWAL"] == 1
    assert stats["total_accounts"] == 2


@pytest.mark.asyncio
async def test_transition_log_recorded(sm):
    await sm.get_or_create("u1")
    await sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1", "test")
    logs = await sm.get_transitions()
    assert len(logs) == 1
    assert logs[0].user_id == "u1"
    assert logs[0].to_state == AccountState.RESTRICTED_WITHDRAWAL


@pytest.mark.asyncio
async def test_reset_clears_runtime_state(sm):
    await sm.get_or_create("u1")
    await sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    sm.blocked_withdrawals = 1

    await sm.reset()

    assert await sm.get_all_users() == []
    assert await sm.get_transitions() == []
    assert (await sm.get_stats())["blocked_withdrawals"] == 0

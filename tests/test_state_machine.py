import pytest
from backend.models import AccountState
from backend.state_machine import StateMachine


@pytest.fixture
def sm():
    return StateMachine()


def test_get_or_create_default_normal(sm):
    assert sm.get_or_create("u1") == AccountState.NORMAL


def test_valid_transition_normal_to_restricted(sm):
    sm.get_or_create("u1")
    assert sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1") is True
    assert sm.accounts["u1"] == AccountState.RESTRICTED_WITHDRAWAL


def test_valid_transition_full_path(sm):
    sm.get_or_create("u1")
    assert sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    assert sm.transition("u1", AccountState.UNDER_SURVEILLANCE, "L2", "GEMINI")
    assert sm.transition("u1", AccountState.BANNED, "L2", "GEMINI")
    assert sm.accounts["u1"] == AccountState.BANNED


def test_invalid_transition_normal_to_banned(sm):
    sm.get_or_create("u1")
    assert sm.transition("u1", AccountState.BANNED, "L1", "R1") is False
    assert sm.accounts["u1"] == AccountState.NORMAL


def test_manual_release(sm):
    sm.get_or_create("u1")
    sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    sm.transition("u1", AccountState.UNDER_SURVEILLANCE, "L2", "GEMINI")
    assert sm.transition("u1", AccountState.NORMAL, "MANUAL", "OP") is True
    assert sm.accounts["u1"] == AccountState.NORMAL


def test_auto_recovery_from_restricted_to_normal(sm):
    sm.get_or_create("u1")
    sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")

    assert sm.transition("u1", AccountState.NORMAL, "L2_ANALYSIS", "GEMINI_LOW_RISK") is True
    assert sm.accounts["u1"] == AccountState.NORMAL


def test_can_withdraw(sm):
    assert sm.can_withdraw("u1") is True
    sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    assert sm.can_withdraw("u1") is False


def test_get_stats(sm):
    sm.get_or_create("u1")
    sm.get_or_create("u2")
    sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    stats = sm.get_stats()
    assert stats["NORMAL"] == 1
    assert stats["RESTRICTED_WITHDRAWAL"] == 1
    assert stats["total_accounts"] == 2


def test_transition_log_recorded(sm):
    sm.get_or_create("u1")
    sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1", "test")
    logs = sm.get_transitions()
    assert len(logs) == 1
    assert logs[0].user_id == "u1"
    assert logs[0].to_state == AccountState.RESTRICTED_WITHDRAWAL


def test_reset_clears_runtime_state(sm):
    sm.get_or_create("u1")
    sm.transition("u1", AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")
    sm.blocked_withdrawals = 1

    sm.reset()

    assert sm.accounts == {}
    assert sm.transition_logs == []
    assert sm.blocked_withdrawals == 0

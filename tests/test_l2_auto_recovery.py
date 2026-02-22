from backend.main import _apply_l2_verdict, sm
from backend.models import AccountState


def test_low_risk_verdict_auto_recovers_to_normal():
    sm.reset()
    user_id = "u1"
    sm.get_or_create(user_id)
    sm.transition(user_id, AccountState.RESTRICTED_WITHDRAWAL, "L1", "R1")

    _apply_l2_verdict(user_id, AccountState.NORMAL, risk_score=10)

    assert sm.get_or_create(user_id) == AccountState.NORMAL


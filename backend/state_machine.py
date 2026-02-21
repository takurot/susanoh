from __future__ import annotations

from datetime import datetime

from backend.models import AccountState, TransitionLog

ALLOWED_TRANSITIONS: dict[AccountState, set[AccountState]] = {
    AccountState.NORMAL: {AccountState.RESTRICTED_WITHDRAWAL},
    AccountState.RESTRICTED_WITHDRAWAL: {AccountState.UNDER_SURVEILLANCE},
    AccountState.UNDER_SURVEILLANCE: {AccountState.BANNED, AccountState.NORMAL},
    AccountState.BANNED: set(),
}


class StateMachine:
    def __init__(self) -> None:
        self.accounts: dict[str, AccountState] = {}
        self.transition_logs: list[TransitionLog] = []
        self.blocked_withdrawals: int = 0

    def get_or_create(self, user_id: str) -> AccountState:
        if user_id not in self.accounts:
            self.accounts[user_id] = AccountState.NORMAL
        return self.accounts[user_id]

    def transition(
        self,
        user_id: str,
        new_state: AccountState,
        trigger: str,
        rule: str,
        evidence_summary: str = "",
    ) -> bool:
        current = self.get_or_create(user_id)
        if new_state not in ALLOWED_TRANSITIONS.get(current, set()):
            return False

        log = TransitionLog(
            user_id=user_id,
            from_state=current,
            to_state=new_state,
            trigger=trigger,
            triggered_by_rule=rule,
            timestamp=datetime.utcnow().isoformat() + "Z",
            evidence_summary=evidence_summary,
        )
        self.accounts[user_id] = new_state
        self.transition_logs.append(log)
        return True

    def can_withdraw(self, user_id: str) -> bool:
        return self.get_or_create(user_id) == AccountState.NORMAL

    def get_stats(self) -> dict:
        stats = {s.value: 0 for s in AccountState}
        for state in self.accounts.values():
            stats[state.value] += 1
        stats["total_accounts"] = len(self.accounts)
        stats["total_transitions"] = len(self.transition_logs)
        stats["blocked_withdrawals"] = self.blocked_withdrawals
        return stats

    def get_transitions(self, limit: int = 50) -> list[TransitionLog]:
        return list(reversed(self.transition_logs[-limit:]))

    def get_all_users(self, state_filter: AccountState | None = None) -> list[dict]:
        users = []
        for uid, st in self.accounts.items():
            if state_filter and st != state_filter:
                continue
            users.append({"user_id": uid, "state": st.value})
        return users

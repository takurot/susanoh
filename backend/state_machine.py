from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from redis.exceptions import RedisError

from backend.models import AccountState, TransitionLog

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS: dict[AccountState, set[AccountState]] = {
    AccountState.NORMAL: {AccountState.RESTRICTED_WITHDRAWAL},
    AccountState.RESTRICTED_WITHDRAWAL: {AccountState.UNDER_SURVEILLANCE, AccountState.NORMAL},
    AccountState.UNDER_SURVEILLANCE: {AccountState.BANNED, AccountState.NORMAL},
    AccountState.BANNED: set(),
}


class StateMachine:
    def __init__(self, redis_client: Optional[Redis] = None) -> None:
        self.redis = redis_client
        self._accounts: dict[str, AccountState] = {}
        self._transition_logs: list[TransitionLog] = []
        self._blocked_withdrawals: int = 0

    @property
    def accounts(self) -> dict[str, AccountState]:
        """Returns in-memory accounts. Use resolve_accounts for full state including Redis."""
        return self._accounts

    @property
    def transition_logs(self) -> list[TransitionLog]:
        return self._transition_logs

    @property
    def blocked_withdrawals(self) -> int:
        return self._blocked_withdrawals

    @blocked_withdrawals.setter
    def blocked_withdrawals(self, value: int) -> None:
        self._blocked_withdrawals = value

    async def reset(self) -> None:
        self._accounts.clear()
        self._transition_logs.clear()
        self._blocked_withdrawals = 0
        if self.redis:
            try:
                await self.redis.delete("susanoh:accounts", "susanoh:transitions", "susanoh:blocked_withdrawals")
            except RedisError as e:
                logger.warning("Redis reset failed: %s", e)

    async def get_or_create(self, user_id: str) -> AccountState:
        # Always check in-memory first as a cache/fallback
        in_mem = self._accounts.get(user_id)
        
        if self.redis:
            try:
                val = await self.redis.hget("susanoh:accounts", user_id)
                if val:
                    st = AccountState(val)
                    self._accounts[user_id] = st
                    return st
                
                await self.redis.hset("susanoh:accounts", user_id, AccountState.NORMAL.value)
                self._accounts[user_id] = AccountState.NORMAL
                return AccountState.NORMAL
            except RedisError as e:
                logger.error("Redis get_or_create failed for %s: %s. Using in-memory.", user_id, e)

        if user_id not in self._accounts:
            self._accounts[user_id] = AccountState.NORMAL
        return self._accounts[user_id]

    async def transition(
        self,
        user_id: str,
        new_state: AccountState,
        trigger: str,
        rule: str,
        evidence_summary: str = "",
    ) -> bool:
        current = await self.get_or_create(user_id)
        if new_state not in ALLOWED_TRANSITIONS.get(current, set()):
            return False

        log = TransitionLog(
            user_id=user_id,
            from_state=current,
            to_state=new_state,
            trigger=trigger,
            triggered_by_rule=rule,
            timestamp=datetime.now(UTC).isoformat() + "Z",
            evidence_summary=evidence_summary,
        )

        # Update in-memory
        self._accounts[user_id] = new_state
        self._transition_logs.append(log)

        if self.redis:
            try:
                await self.redis.hset("susanoh:accounts", user_id, new_state.value)
                await self.redis.rpush("susanoh:transitions", log.model_dump_json())
            except RedisError as e:
                logger.error("Redis transition failed for %s: %s", user_id, e)
        
        return True

    async def can_withdraw(self, user_id: str) -> bool:
        return await self.get_or_create(user_id) == AccountState.NORMAL

    async def get_stats(self) -> dict:
        if self.redis:
            try:
                all_accounts = await self.redis.hgetall("susanoh:accounts")
                stats = {s.value: 0 for s in AccountState}
                for state_val in all_accounts.values():
                    stats[state_val] += 1
                stats["total_accounts"] = len(all_accounts)
                stats["total_transitions"] = await self.redis.llen("susanoh:transitions")
                stats["blocked_withdrawals"] = int(await self.redis.get("susanoh:blocked_withdrawals") or 0)
                return stats
            except RedisError as e:
                logger.warning("Redis get_stats failed: %s. Using in-memory.", e)

        stats = {s.value: 0 for s in AccountState}
        for state in self._accounts.values():
            stats[state.value] += 1
        stats["total_accounts"] = len(self._accounts)
        stats["total_transitions"] = len(self._transition_logs)
        stats["blocked_withdrawals"] = self._blocked_withdrawals
        return stats

    async def get_transitions(self, limit: int = 50) -> list[TransitionLog]:
        if self.redis:
            try:
                raw_logs = await self.redis.lrange("susanoh:transitions", -limit, -1)
                logs = [TransitionLog.model_validate_json(l) for l in raw_logs]
                return list(reversed(logs))
            except RedisError as e:
                logger.warning("Redis get_transitions failed: %s. Using in-memory.", e)

        return list(reversed(self._transition_logs[-limit:]))

    async def get_all_users(self, state_filter: AccountState | None = None) -> list[dict]:
        if self.redis:
            try:
                all_accounts = await self.redis.hgetall("susanoh:accounts")
                users = []
                for uid, st_val in all_accounts.items():
                    if state_filter and st_val != state_filter.value:
                        continue
                    users.append({"user_id": uid, "state": st_val})
                return users
            except RedisError as e:
                logger.warning("Redis get_all_users failed: %s. Using in-memory.", e)

        users = []
        for uid, st in self._accounts.items():
            if state_filter and st != state_filter:
                continue
            users.append({"user_id": uid, "state": st.value})
        return users

    async def resolve_accounts(self, user_ids: list[str]) -> dict[str, AccountState]:
        """Resolves states for a list of users, fetching from Redis if available."""
        results = {}
        if self.redis:
            try:
                # Batch fetch from Redis
                vals = await self.redis.hmget("susanoh:accounts", user_ids)
                for uid, val in zip(user_ids, vals):
                    if val:
                        st = AccountState(val)
                        results[uid] = st
                        self._accounts[uid] = st
                    else:
                        results[uid] = self._accounts.get(uid, AccountState.NORMAL)
                return results
            except RedisError:
                pass
        
        for uid in user_ids:
            results[uid] = self._accounts.get(uid, AccountState.NORMAL)
        return results

    async def increment_blocked_withdrawals(self) -> None:
        self._blocked_withdrawals += 1
        if self.redis:
            try:
                await self.redis.incr("susanoh:blocked_withdrawals")
            except RedisError:
                pass

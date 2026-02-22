from __future__ import annotations

import re
import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

from redis.exceptions import RedisError

from backend.models import (
    AnalysisRequest,
    GameEventLog,
    ScreeningResult,
    AccountState,
    UserProfile,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 300  # 5 min

SLANG_PATTERN = re.compile(
    r"振[り込]?込|D[でにて]確認|[0-9]+[kK千万]|りょ[。.]|PayPa[ly]|銀行|口座|送金|入金確認"
)

AMOUNT_THRESHOLD = 1_000_000
TX_COUNT_THRESHOLD = 10
MARKET_AVG_MULTIPLIER = 100


@dataclass
class UserWindow:
    events: deque = field(default_factory=deque)

    def add_event(self, event: GameEventLog) -> None:
        self.events.append(event)
        self._purge()

    def _purge(self, cutoff: Optional[datetime] = None) -> None:
        if cutoff is None:
            cutoff = datetime.now(UTC)
        window_limit = cutoff - timedelta(seconds=WINDOW_SECONDS)
        while self.events:
            try:
                ts = datetime.fromisoformat(self.events[0].timestamp.replace("Z", "+00:00"))
            except Exception:
                ts = cutoff
            if ts < window_limit:
                self.events.popleft()
            else:
                break

    def total_amount(self) -> int:
        return sum(e.action_details.currency_amount for e in self.events)

    def transaction_count(self) -> int:
        return len(self.events)

    def unique_senders(self) -> int:
        return len({e.actor_id for e in self.events})


class L1Engine:
    def __init__(self, redis_client: Optional[Redis] = None) -> None:
        self.redis = redis_client
        self.user_windows: dict[str, UserWindow] = defaultdict(UserWindow)
        self._recent_events: deque[tuple[GameEventLog, ScreeningResult]] = deque(maxlen=200)
        self._l1_flag_count: int = 0

    @property
    def recent_events(self) -> list[tuple[GameEventLog, ScreeningResult]]:
        return list(self._recent_events)

    @property
    def l1_flag_count(self) -> int:
        return self._l1_flag_count

    async def reset(self) -> None:
        self.user_windows.clear()
        self._recent_events.clear()
        self._l1_flag_count = 0
        if self.redis:
            try:
                keys = await self.redis.keys("susanoh:window:*")
                if keys:
                    await self.redis.delete(*keys)
                await self.redis.delete("susanoh:recent_events", "susanoh:l1_flag_count")
            except RedisError as e:
                logger.warning("Redis reset failed: %s. Using in-memory fallback.", e)

    async def screen(self, event: GameEventLog) -> ScreeningResult:
        target_id = event.target_id
        
        total_amount = 0
        tx_count = 0
        
        # In-memory always tracks for fallback/snapshot
        window = self.user_windows[target_id]
        window.add_event(event)

        if self.redis:
            try:
                key = f"susanoh:window:{target_id}"
                # Use event timestamp as score for consistency (Finding 3)
                try:
                    event_ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00")).timestamp()
                except Exception:
                    event_ts = datetime.now(UTC).timestamp()
                
                cutoff_ts = event_ts - WINDOW_SECONDS
                
                # Add current event
                await self.redis.zadd(key, {event.model_dump_json(): event_ts})
                # Purge old events
                await self.redis.zremrangebyscore(key, "-inf", cutoff_ts)
                # Set TTL
                await self.redis.expire(key, WINDOW_SECONDS + 60)
                
                # Get window stats
                raw_events = await self.redis.zrange(key, 0, -1)
                events_in_window = [GameEventLog.model_validate_json(e) for e in raw_events]
                total_amount = sum(e.action_details.currency_amount for e in events_in_window)
                tx_count = len(events_in_window)
            except RedisError as e:
                logger.error("Redis screening failed: %s. Degraded to in-memory.", e)
                # Fail open to in-memory mode
                total_amount = window.total_amount()
                tx_count = window.transaction_count()
        else:
            total_amount = window.total_amount()
            tx_count = window.transaction_count()

        triggered: list[str] = []

        if total_amount >= AMOUNT_THRESHOLD:
            triggered.append("R1")
        if tx_count >= TX_COUNT_THRESHOLD:
            triggered.append("R2")
        if (
            event.action_details.market_avg_price
            and event.action_details.market_avg_price > 0
            and event.action_details.currency_amount
            >= event.action_details.market_avg_price * MARKET_AVG_MULTIPLIER
        ):
            triggered.append("R3")

        needs_l2 = False
        chat = event.context_metadata.recent_chat_log or ""
        if self._check_slang(chat):
            triggered.append("R4")
            needs_l2 = True

        if triggered:
            self._l1_flag_count += 1
            if self.redis:
                try:
                    await self.redis.incr("susanoh:l1_flag_count")
                except RedisError:
                    pass

        result = ScreeningResult(
            screened=bool(triggered),
            triggered_rules=triggered,
            recommended_action=AccountState.RESTRICTED_WITHDRAWAL if triggered else None,
            needs_l2=needs_l2,
        )
        
        self._recent_events.append((event, result))
        if self.redis:
            try:
                data = json.dumps({
                    "event": event.model_dump(),
                    "result": result.model_dump()
                })
                await self.redis.lpush("susanoh:recent_events", data)
                await self.redis.ltrim("susanoh:recent_events", 0, 199)
            except RedisError:
                pass

        return result

    @staticmethod
    def _check_slang(chat_log: str) -> bool:
        return bool(SLANG_PATTERN.search(chat_log))

    async def build_analysis_request(self, user_id: str, event: GameEventLog, triggered_rules: list[str], current_state: AccountState) -> AnalysisRequest:
        total_amount = 0
        tx_count = 0
        unique_senders = 0
        related_events = []

        if self.redis:
            try:
                key = f"susanoh:window:{user_id}"
                try:
                    event_ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00")).timestamp()
                except Exception:
                    event_ts = datetime.now(UTC).timestamp()
                cutoff_ts = event_ts - WINDOW_SECONDS
                await self.redis.zremrangebyscore(key, "-inf", cutoff_ts)
                raw_events = await self.redis.zrange(key, 0, -1)
                related_events = [GameEventLog.model_validate_json(e) for e in raw_events]
                total_amount = sum(e.action_details.currency_amount for e in related_events)
                tx_count = len(related_events)
                unique_senders = len({e.actor_id for e in related_events})
            except RedisError:
                # Fallback to in-memory
                window = self.user_windows.get(user_id, UserWindow())
                related_events = list(window.events)
                total_amount = window.total_amount()
                tx_count = window.transaction_count()
                unique_senders = window.unique_senders()
        else:
            window = self.user_windows.get(user_id, UserWindow())
            related_events = list(window.events)
            total_amount = window.total_amount()
            tx_count = window.transaction_count()
            unique_senders = window.unique_senders()

        return AnalysisRequest(
            trigger_event=event,
            related_events=related_events,
            triggered_rules=triggered_rules,
            user_profile=UserProfile(
                user_id=user_id,
                current_state=current_state,
                total_received_5min=total_amount,
                transaction_count_5min=tx_count,
                unique_senders_5min=unique_senders,
            ),
        )

    async def get_recent_events(self, limit: int = 20) -> list[dict]:
        if self.redis:
            try:
                raw = await self.redis.lrange("susanoh:recent_events", 0, limit - 1)
                results = []
                for item in raw:
                    data = json.loads(item)
                    results.append({
                        **data["event"],
                        "screened": data["result"]["screened"],
                        "triggered_rules": data["result"]["triggered_rules"],
                    })
                return results
            except RedisError:
                pass

        events = list(self._recent_events)
        return [
            {
                **event.model_dump(),
                "screened": result.screened,
                "triggered_rules": result.triggered_rules,
            }
            for event, result in reversed(events[-limit:])
        ]

    async def get_graph_data(self, accounts: dict[str, AccountState]) -> dict:
        node_ids: set[str] = set()
        link_map: dict[tuple[str, str], dict] = {}

        events_to_process = []
        if self.redis:
            try:
                raw = await self.redis.lrange("susanoh:recent_events", 0, -1)
                for item in raw:
                    data = json.loads(item)
                    events_to_process.append(GameEventLog.model_validate(data["event"]))
            except RedisError:
                events_to_process = [e for e, _ in self._recent_events]
        else:
            events_to_process = [e for e, _ in self._recent_events]

        for event in events_to_process:
            node_ids.add(event.actor_id)
            node_ids.add(event.target_id)
            key = (event.actor_id, event.target_id)
            if key not in link_map:
                link_map[key] = {"source": event.actor_id, "target": event.target_id, "amount": 0, "count": 0}
            link_map[key]["amount"] += event.action_details.currency_amount
            link_map[key]["count"] += 1

        nodes = []
        for nid in node_ids:
            state = accounts.get(nid, AccountState.NORMAL)
            nodes.append({"id": nid, "state": state.value, "label": nid})

        return {"nodes": nodes, "links": list(link_map.values())}

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.models import (
    AnalysisRequest,
    GameEventLog,
    ScreeningResult,
    AccountState,
    UserProfile,
)

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

    def _purge(self) -> None:
        cutoff = datetime.utcnow() - timedelta(seconds=WINDOW_SECONDS)
        while self.events:
            try:
                ts = datetime.fromisoformat(self.events[0].timestamp.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                ts = datetime.utcnow()
            if ts < cutoff:
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
    def __init__(self) -> None:
        self.user_windows: dict[str, UserWindow] = defaultdict(UserWindow)
        self.recent_events: deque[GameEventLog] = deque(maxlen=200)
        self.l1_flag_count: int = 0

    def screen(self, event: GameEventLog) -> ScreeningResult:
        target_id = event.target_id
        window = self.user_windows[target_id]
        window.add_event(event)
        self.recent_events.append(event)

        triggered: list[str] = []

        if window.total_amount() >= AMOUNT_THRESHOLD:
            triggered.append("R1")
        if window.transaction_count() >= TX_COUNT_THRESHOLD:
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
            self.l1_flag_count += 1

        return ScreeningResult(
            screened=bool(triggered),
            triggered_rules=triggered,
            recommended_action=AccountState.RESTRICTED_WITHDRAWAL if triggered else None,
            needs_l2=needs_l2,
        )

    @staticmethod
    def _check_slang(chat_log: str) -> bool:
        return bool(SLANG_PATTERN.search(chat_log))

    def build_analysis_request(self, user_id: str, event: GameEventLog, triggered_rules: list[str], current_state: AccountState) -> AnalysisRequest:
        window = self.user_windows.get(user_id, UserWindow())
        return AnalysisRequest(
            trigger_event=event,
            related_events=list(window.events),
            triggered_rules=triggered_rules,
            user_profile=UserProfile(
                user_id=user_id,
                current_state=current_state,
                total_received_5min=window.total_amount(),
                transaction_count_5min=window.transaction_count(),
                unique_senders_5min=window.unique_senders(),
            ),
        )

    def get_recent_events(self, limit: int = 20) -> list[GameEventLog]:
        events = list(self.recent_events)
        return list(reversed(events[-limit:]))

    def get_graph_data(self, accounts: dict[str, AccountState]) -> dict:
        node_ids: set[str] = set()
        link_map: dict[tuple[str, str], dict] = {}

        for event in self.recent_events:
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

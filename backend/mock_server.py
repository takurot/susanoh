from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime

from backend.models import ActionDetails, ContextMetadata, GameEventLog

NORMAL_PLAYERS = [f"user_player_{i:02d}" for i in range(1, 21)]
MULE_ACCOUNTS = [f"user_mule_{i:02d}" for i in range(1, 9)]
BOSS_ACCOUNT = "user_boss_01"
LAYER_CHAIN = ["user_layer_A", "user_layer_B", "user_layer_C", "user_layer_D"]


def _eid() -> str:
    return f"evt_{uuid.uuid4().hex[:8]}"


def _ts() -> str:
    return datetime.utcnow().isoformat() + "Z"


class MockGameServer:
    def generate_normal_event(self) -> GameEventLog:
        actor, target = random.sample(NORMAL_PLAYERS, 2)
        return GameEventLog(
            event_id=_eid(),
            timestamp=_ts(),
            event_type="TRADE",
            actor_id=actor,
            target_id=target,
            action_details=ActionDetails(
                currency_amount=random.randint(100, 50_000),
                item_id=f"itm_{random.choice(['sword', 'shield', 'potion', 'gem', 'ore'])}_{random.randint(1,20):02d}",
                market_avg_price=random.randint(500, 5000),
            ),
            context_metadata=ContextMetadata(
                actor_level=random.randint(10, 80),
                account_age_days=random.randint(30, 365),
                recent_chat_log=random.choice([
                    "よろしく！",
                    "ありがとう！",
                    "GG!",
                    "いい取引だったね",
                    "また交換しよう",
                    None,
                ]),
            ),
        )

    def generate_smurfing_events(self) -> list[GameEventLog]:
        events = []
        for mule in MULE_ACCOUNTS:
            events.append(GameEventLog(
                event_id=_eid(),
                timestamp=_ts(),
                event_type="TRADE",
                actor_id=mule,
                target_id=BOSS_ACCOUNT,
                action_details=ActionDetails(
                    currency_amount=random.randint(150_000, 300_000),
                    item_id="itm_wood_stick_01",
                    market_avg_price=10,
                ),
                context_metadata=ContextMetadata(
                    actor_level=random.randint(1, 5),
                    account_age_days=random.randint(1, 3),
                    recent_chat_log=random.choice([
                        "Dで確認しました",
                        "振り込み完了",
                        "入金確認お願いします",
                        None,
                    ]),
                ),
            ))
        return events

    def generate_rmt_slang_event(self) -> GameEventLog:
        return GameEventLog(
            event_id=_eid(),
            timestamp=_ts(),
            event_type="TRADE",
            actor_id="user_rmt_seller_01",
            target_id="user_rmt_buyer_01",
            action_details=ActionDetails(
                currency_amount=500_000,
                item_id="itm_wood_stick_01",
                market_avg_price=10,
            ),
            context_metadata=ContextMetadata(
                actor_level=2,
                account_age_days=1,
                recent_chat_log="3kで振込お願いします。PayPal可。口座番号送ります。",
            ),
        )

    def generate_layering_events(self) -> list[GameEventLog]:
        events = []
        amount = random.randint(200_000, 500_000)
        for i in range(len(LAYER_CHAIN) - 1):
            events.append(GameEventLog(
                event_id=_eid(),
                timestamp=_ts(),
                event_type="TRADE",
                actor_id=LAYER_CHAIN[i],
                target_id=LAYER_CHAIN[i + 1],
                action_details=ActionDetails(
                    currency_amount=amount,
                    item_id=f"itm_rare_gem_{i+1:02d}",
                    market_avg_price=random.randint(1000, 5000),
                ),
                context_metadata=ContextMetadata(
                    actor_level=random.randint(5, 15),
                    account_age_days=random.randint(5, 20),
                ),
            ))
            amount = int(amount * 0.95)
        return events


class DemoStreamer:
    def __init__(self, event_callback) -> None:
        self.running = False
        self._task: asyncio.Task | None = None
        self._callback = event_callback
        self._server = MockGameServer()

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._stream())

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _stream(self) -> None:
        while self.running:
            r = random.random()
            if r < 0.90:
                events = [self._server.generate_normal_event()]
            elif r < 0.95:
                events = self._server.generate_smurfing_events()
            elif r < 0.98:
                events = [self._server.generate_rmt_slang_event()]
            else:
                events = self._server.generate_layering_events()

            for event in events:
                await self._callback(event)

            await asyncio.sleep(random.uniform(0.1, 0.5))

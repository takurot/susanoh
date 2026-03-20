#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.l1_screening import (
    AMOUNT_THRESHOLD,
    MARKET_AVG_MULTIPLIER,
    TX_COUNT_THRESHOLD,
)

DEFAULT_MAX_P95_MS = 5000
DATASET_VERSION = "v0.6.0"
DATASET_CHANGELOG = [
    {
        "version": "v0.6.0",
        "released_at": "2026-03-19",
        "summary": "Add LLM-specific fault scenarios for malformed JSON, context length exceeded, and token limit exceeded.",
        "changes": [
            "Add fault scenarios for llm_malformed_json, llm_context_length_exceeded, and llm_token_limit.",
            "Validate that all three LLM fault types produce the expected UNDER_SURVEILLANCE/BANNED fallback.",
        ],
        "previous_version": "v0.5.0",
    },
    {
        "version": "v0.5.0",
        "released_at": "2026-03-19",
        "summary": "Expand regression fault injection coverage to Redis, Gemini 429, and DB persistence degradation.",
        "changes": [
            "Add regression scenarios for gemini_429, redis_timeout, and db_connection_degraded.",
            "Document the expanded dependency-fault catalog in the generated dataset README.",
        ],
        "previous_version": "v0.4.0",
    },
    {
        "version": "v0.4.0",
        "released_at": "2026-03-14",
        "summary": "Introduce explicit dataset version metadata and release changelog for fixture comparisons.",
        "changes": [
            "Add dataset_version and changelog metadata to generated fixture manifests.",
            "Surface the current release notes in runner artifacts for cross-run comparisons.",
        ],
        "previous_version": "v0.3.0",
    },
    {
        "version": "v0.3.0",
        "released_at": "2026-03-13",
        "summary": "Add timeline variation replay cases for out-of-order, delayed, and duplicate event delivery.",
        "changes": [
            "Generate timeline_variations.json from canonical scenarios.",
            "Validate timeline variation fixtures against the generator output.",
        ],
        "previous_version": "v0.2.0",
    },
    {
        "version": "v0.2.0",
        "released_at": "2026-03-13",
        "summary": "Refresh the dataset with threshold-boundary fixtures for rules R1-R4.",
        "changes": [
            "Add just_below, at_threshold, and just_above coverage for each L1 rule.",
            "Validate boundary fixtures against the live L1Engine thresholds.",
        ],
        "previous_version": "v0.1.0",
    },
    {
        "version": "v0.1.0",
        "released_at": "2026-03-05",
        "summary": "Seed the initial operational testbench scenario catalog and replay stream.",
        "changes": [
            "Create 15 baseline scenarios and the flattened events.jsonl replay stream.",
        ],
        "previous_version": None,
    },
]


@dataclass
class EventFactory:
    started_at: datetime
    step_seconds: int = 8
    counter: int = 0

    def make(
        self,
        *,
        actor_id: str,
        target_id: str,
        currency_amount: int,
        market_avg_price: int,
        recent_chat_log: str | None,
        actor_level: int,
        account_age_days: int,
        item_id: str,
    ) -> dict[str, Any]:
        timestamp = self.started_at + timedelta(seconds=self.counter * self.step_seconds)
        event_id = f"evt_tb_{self.counter:06d}"
        self.counter += 1
        return {
            "event_id": event_id,
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "event_type": "TRADE",
            "actor_id": actor_id,
            "target_id": target_id,
            "action_details": {
                "currency_amount": currency_amount,
                "item_id": item_id,
                "market_avg_price": market_avg_price,
            },
            "context_metadata": {
                "actor_level": actor_level,
                "account_age_days": account_age_days,
                "recent_chat_log": recent_chat_log,
            },
        }


def _build_scenarios(factory: EventFactory, rng: random.Random) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []

    def event(
        actor_id: str,
        target_id: str,
        amount: int,
        *,
        market_avg: int = 1800,
        chat: str | None = None,
        actor_level: int = 35,
        account_age_days: int = 220,
        item_id: str = "itm_trade_pack_01",
    ) -> dict[str, Any]:
        return factory.make(
            actor_id=actor_id,
            target_id=target_id,
            currency_amount=amount,
            market_avg_price=market_avg,
            recent_chat_log=chat,
            actor_level=actor_level,
            account_age_days=account_age_days,
            item_id=item_id,
        )

    # High-risk fraud scenarios
    target = "acct_boss_01"
    events = []
    for idx in range(1, 13):
        chat = None
        if idx in {3, 8, 11}:
            chat = f"confirm {10 + idx}k via PayPal"
        events.append(
            event(
                f"acct_mule_{idx:02d}",
                target,
                rng.randint(90_000, 130_000),
                market_avg=700 if idx == 8 else 1700,
                chat=chat,
                actor_level=rng.randint(2, 9),
                account_age_days=rng.randint(1, 12),
                item_id="itm_wood_stick_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "fraud_smurfing_fan_in",
            "title": "Smurfing fan-in to mule boss",
            "pattern_family": "RMT_SMURFING",
            "risk_tier": "high",
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R2", "R3", "R4"],
                "l2_fallback_action": "BANNED",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Many low-age senders rapidly transfer to one boss account.",
            },
            "events": events,
        }
    )

    target = "acct_buyer_01"
    events = [
        event(
            "acct_seller_01",
            target,
            480_000,
            market_avg=2000,
            chat="send 15k via PayPal and confirm",
            actor_level=4,
            account_age_days=3,
            item_id="itm_wood_stick_02",
        ),
        event(
            "acct_seller_01",
            target,
            330_000,
            market_avg=2500,
            chat="bank transfer done",
            actor_level=4,
            account_age_days=3,
            item_id="itm_wood_stick_03",
        ),
        event(
            "acct_seller_01",
            target,
            260_000,
            market_avg=2800,
            chat="final 12k chunk",
            actor_level=4,
            account_age_days=3,
            item_id="itm_wood_stick_04",
        ),
    ]
    scenarios.append(
        {
            "scenario_id": "fraud_direct_rmt_chat",
            "title": "Direct RMT negotiation in chat",
            "pattern_family": "RMT_DIRECT",
            "risk_tier": "high",
            "fault_injection": {
                "type": "gemini_timeout",
            },
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R3", "R4"],
                "l2_fallback_action": "BANNED",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Direct slang and disproportionate item pricing.",
            },
            "events": events,
        }
    )

    target = "acct_exit_01"
    events = []
    chain = [
        ("acct_layer_a1", "acct_layer_b1", 220_000),
        ("acct_layer_b1", "acct_layer_c1", 210_000),
        ("acct_layer_c1", "acct_layer_d1", 202_000),
        ("acct_layer_d1", target, 194_000),
        ("acct_layer_a2", "acct_layer_b2", 230_000),
        ("acct_layer_b2", "acct_layer_c2", 219_000),
        ("acct_layer_c2", target, 206_000),
        ("acct_layer_x", target, 208_000),
        ("acct_layer_y", target, 205_000),
        ("acct_layer_z", target, 207_000),
    ]
    for actor_id, target_id, amount in chain:
        events.append(
            event(
                actor_id,
                target_id,
                amount,
                market_avg=1600,
                chat=None,
                actor_level=rng.randint(6, 18),
                account_age_days=rng.randint(7, 45),
                item_id="itm_rare_gem_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "fraud_layering_chain_exit",
            "title": "Layering chain converging to exit wallet",
            "pattern_family": "MONEY_LAUNDERING",
            "risk_tier": "high",
            "fault_injection": {
                "type": "gemini_5xx",
            },
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R3"],
                "l2_fallback_action": "UNDER_SURVEILLANCE",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Multi-hop transfers converge into one exit account.",
            },
            "events": events,
        }
    )

    target = "acct_sink_01"
    events = []
    for idx in range(1, 15):
        events.append(
            event(
                f"acct_bot_{idx:02d}",
                target,
                rng.randint(72_000, 84_000),
                market_avg=1400,
                chat=None,
                actor_level=rng.randint(1, 8),
                account_age_days=rng.randint(1, 5),
                item_id="itm_low_tier_mat_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "fraud_microburst_bot_farm",
            "title": "Bot farm micro-burst funnel",
            "pattern_family": "MONEY_LAUNDERING",
            "risk_tier": "high",
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R2"],
                "l2_fallback_action": "UNDER_SURVEILLANCE",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "High transaction count and total amount with low-age senders.",
            },
            "events": events,
        }
    )

    target = "acct_market_abuser_01"
    events = []
    for idx in range(1, 9):
        chat = "rare skin sale" if idx % 3 else "confirm 9k item"
        events.append(
            event(
                f"acct_market_buyer_{idx:02d}",
                target,
                rng.randint(122_000, 138_000),
                market_avg=900,
                chat=chat,
                actor_level=rng.randint(12, 36),
                account_age_days=rng.randint(20, 240),
                item_id="itm_common_skin_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "fraud_market_price_abuse",
            "title": "Systematic market price abuse",
            "pattern_family": "RMT_DIRECT",
            "risk_tier": "high",
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R3", "R4"],
                "l2_fallback_action": "BANNED",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Repeated 100x+ price anomalies with coded chat hints.",
            },
            "events": events,
        }
    )

    target = "acct_bridge_hub_01"
    events = []
    for idx in range(1, 11):
        cluster = "north" if idx <= 5 else "south"
        chat = "" if idx not in {2, 9} else "settle 25k now"
        events.append(
            event(
                f"acct_{cluster}_ring_{idx:02d}",
                target,
                rng.randint(100_000, 113_000),
                market_avg=1800,
                chat=chat or None,
                actor_level=rng.randint(5, 14),
                account_age_days=rng.randint(3, 18),
                item_id="itm_transfer_token_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "fraud_cross_cluster_bridge",
            "title": "Cross-cluster bridge consolidation",
            "pattern_family": "MONEY_LAUNDERING",
            "risk_tier": "high",
            "fault_injection": {
                "type": "redis_timeout",
            },
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R2", "R4"],
                "l2_fallback_action": "BANNED",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Two clusters converge to bridge account before cashout.",
            },
            "events": events,
        }
    )

    target = "acct_cashout_01"
    events = []
    senders = ["acct_courier_01", "acct_courier_02", "acct_courier_03", "acct_courier_04"]
    for idx in range(1, 12):
        actor_id = senders[idx % len(senders)]
        chat = "final 18k" if idx in {4, 7, 11} else None
        events.append(
            event(
                actor_id,
                target,
                rng.randint(95_000, 120_000),
                market_avg=1600,
                chat=chat,
                actor_level=rng.randint(4, 20),
                account_age_days=rng.randint(5, 60),
                item_id="itm_bundle_ticket_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "fraud_cashout_prep_sequence",
            "title": "Cashout preparation sequence",
            "pattern_family": "RMT_SMURFING",
            "risk_tier": "high",
            "fault_injection": {
                "type": "gemini_429",
            },
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R2", "R4"],
                "l2_fallback_action": "BANNED",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Repeated staged transfers shortly before expected withdrawal.",
            },
            "events": events,
        }
    )

    target = "acct_sleeper_01"
    events = []
    for idx in range(1, 6):
        events.append(
            event(
                f"acct_new_device_{idx:02d}",
                target,
                rng.randint(235_000, 268_000),
                market_avg=1700,
                chat="reactivate route 11k" if idx == 5 else None,
                actor_level=rng.randint(1, 6),
                account_age_days=rng.randint(1, 4),
                item_id="itm_filler_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "fraud_sleeper_activation",
            "title": "Sleeper account sudden activation",
            "pattern_family": "MONEY_LAUNDERING",
            "risk_tier": "high",
            "fault_injection": {
                "type": "db_connection_degraded",
            },
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R3", "R4"],
                "l2_fallback_action": "BANNED",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Dormant target suddenly receives high-value bursts from fresh accounts.",
            },
            "events": events,
        }
    )

    # LLM-specific fault injection scenarios
    target = "acct_rmt_llm_json_01"
    events = [
        event(
            "acct_seller_llm_01",
            target,
            1_200_000,
            market_avg=10_000,
            chat="send 40k via PayPal final deal",
            actor_level=3,
            account_age_days=2,
            item_id="itm_rmt_token_01",
        ),
    ]
    scenarios.append(
        {
            "scenario_id": "fault_llm_malformed_response",
            "title": "LLM returns malformed JSON — fallback to rule-based arbitration",
            "pattern_family": "RMT_DIRECT",
            "risk_tier": "high",
            "fault_injection": {
                "type": "llm_malformed_json",
            },
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R3", "R4"],
                "l2_fallback_action": "BANNED",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Simulates Gemini returning unparseable JSON; system must fall back to rule-based BANNED verdict.",
            },
            "events": events,
        }
    )

    target = "acct_smurfing_llm_ctx_01"
    events = []
    for idx in range(1, 13):
        events.append(
            event(
                f"acct_ctx_sender_{idx:02d}",
                target,
                100_000,
                market_avg=800,
                chat=None,
                actor_level=rng.randint(2, 8),
                account_age_days=rng.randint(1, 6),
                item_id="itm_bulk_mat_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "fault_llm_context_length_exceeded",
            "title": "LLM context length exceeded by many-event smurfing — fallback arbitration",
            "pattern_family": "RMT_SMURFING",
            "risk_tier": "high",
            "fault_injection": {
                "type": "llm_context_length_exceeded",
            },
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R2", "R3"],
                "l2_fallback_action": "BANNED",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Simulates Gemini failing due to context overflow on a dense multi-sender scenario; rule-based fallback must produce BANNED.",
            },
            "events": events,
        }
    )

    target = "acct_rmt_llm_token_01"
    events = []
    for idx in range(1, 4):
        events.append(
            event(
                f"acct_token_seller_{idx:02d}",
                target,
                420_000,
                market_avg=3_000,
                chat=None,
                actor_level=rng.randint(4, 12),
                account_age_days=rng.randint(5, 20),
                item_id="itm_crafted_gear_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "fault_llm_token_limit",
            "title": "LLM token limit exceeded — fallback to UNDER_SURVEILLANCE",
            "pattern_family": "MONEY_LAUNDERING",
            "risk_tier": "high",
            "fault_injection": {
                "type": "llm_token_limit",
            },
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R3"],
                "l2_fallback_action": "UNDER_SURVEILLANCE",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Simulates Gemini failing due to token limit; rule-based fallback (R1+R3 only, <3 senders) must produce UNDER_SURVEILLANCE.",
            },
            "events": events,
        }
    )

    # Gray-zone scenarios (false-positive stress)
    target = "acct_guild_bank_01"
    events = []
    for idx in range(1, 13):
        events.append(
            event(
                f"acct_guild_member_{idx:02d}",
                target,
                rng.randint(82_000, 94_000),
                market_avg=2200,
                chat=f"guild dues cycle {idx}",
                actor_level=rng.randint(40, 72),
                account_age_days=rng.randint(300, 1400),
                item_id="itm_guild_token_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "gray_guild_treasury_collection",
            "title": "Guild treasury collection",
            "pattern_family": "LEGITIMATE_STRESS",
            "risk_tier": "medium",
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R2"],
                "l2_fallback_action": "UNDER_SURVEILLANCE",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Legitimate guild dues may look like fan-in smurfing.",
            },
            "events": events,
        }
    )

    target = "acct_market_maker_01"
    events = []
    for idx in range(1, 11):
        events.append(
            event(
                f"acct_flash_sale_user_{idx:02d}",
                target,
                rng.randint(96_000, 110_000),
                market_avg=1500,
                chat="limited event trade",
                actor_level=rng.randint(28, 67),
                account_age_days=rng.randint(120, 850),
                item_id="itm_event_ticket_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "gray_flash_sale_peak",
            "title": "Flash-sale peak traffic",
            "pattern_family": "LEGITIMATE_STRESS",
            "risk_tier": "medium",
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R2"],
                "l2_fallback_action": "UNDER_SURVEILLANCE",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Healthy market spikes should avoid hard bans.",
            },
            "events": events,
        }
    )

    target = "acct_streamer_01"
    events = []
    for idx in range(1, 12):
        events.append(
            event(
                f"acct_fan_{idx:02d}",
                target,
                rng.randint(90_000, 102_000),
                market_avg=1900,
                chat="community support drop",
                actor_level=rng.randint(18, 50),
                account_age_days=rng.randint(100, 720),
                item_id="itm_support_badge_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "gray_streamer_donation_spike",
            "title": "Streamer donation spike",
            "pattern_family": "LEGITIMATE_STRESS",
            "risk_tier": "medium",
            "expected": {
                "target_id": target,
                "l1_primary_rules": ["R1", "R2"],
                "l2_fallback_action": "UNDER_SURVEILLANCE",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Donation spikes should be reviewable without immediate ban.",
            },
            "events": events,
        }
    )

    # Legitimate baseline scenarios
    target = "acct_reward_receiver_01"
    events = [
        event("system_reward_pool", target, 45_000, market_avg=4000, chat="season reward A", actor_level=99, account_age_days=2000, item_id="itm_reward_crate_01"),
        event("system_reward_pool", target, 40_000, market_avg=4200, chat="season reward B", actor_level=99, account_age_days=2000, item_id="itm_reward_crate_02"),
        event("system_reward_pool", target, 38_000, market_avg=4300, chat="season reward C", actor_level=99, account_age_days=2000, item_id="itm_reward_crate_03"),
    ]
    scenarios.append(
        {
            "scenario_id": "legit_new_season_rewards",
            "title": "New season reward disbursement",
            "pattern_family": "LEGITIMATE",
            "risk_tier": "low",
            "expected": {
                "target_id": target,
                "l1_primary_rules": [],
                "l2_fallback_action": "NORMAL",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "System-origin periodic rewards.",
            },
            "events": events,
        }
    )

    target = "acct_friend_target_01"
    events = []
    for idx in range(1, 10):
        events.append(
            event(
                f"acct_friend_{idx:02d}",
                target,
                rng.randint(16_000, 24_000),
                market_avg=1600,
                chat="daily coop gift",
                actor_level=rng.randint(15, 42),
                account_age_days=rng.randint(90, 550),
                item_id="itm_friend_gift_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "legit_friend_gifts_low_value",
            "title": "Small daily friend gifts",
            "pattern_family": "LEGITIMATE",
            "risk_tier": "low",
            "expected": {
                "target_id": target,
                "l1_primary_rules": [],
                "l2_fallback_action": "NORMAL",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Regular low-value social transfers.",
            },
            "events": events,
        }
    )

    target = "acct_auction_house_01"
    events = [
        event("acct_whale_01", target, 280_000, market_avg=5000, chat="premium skin auction", actor_level=78, account_age_days=1200, item_id="itm_premium_skin_01"),
        event("acct_whale_02", target, 295_000, market_avg=5200, chat="premium skin auction", actor_level=81, account_age_days=1320, item_id="itm_premium_skin_02"),
        event("acct_whale_03", target, 270_000, market_avg=4800, chat="premium skin auction", actor_level=74, account_age_days=980, item_id="itm_premium_skin_03"),
    ]
    scenarios.append(
        {
            "scenario_id": "legit_whale_purchase_high_avg",
            "title": "Whale purchases with high market average",
            "pattern_family": "LEGITIMATE",
            "risk_tier": "low",
            "expected": {
                "target_id": target,
                "l1_primary_rules": [],
                "l2_fallback_action": "NORMAL",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "High absolute value but fair market ratio and low frequency.",
            },
            "events": events,
        }
    )

    target = "acct_tournament_champion_01"
    events = []
    for idx in range(1, 5):
        events.append(
            event(
                "system_tournament_pool",
                target,
                70_000,
                market_avg=5000,
                chat=f"tournament round {idx} prize",
                actor_level=99,
                account_age_days=2200,
                item_id="itm_trophy_token_01",
            )
        )
    scenarios.append(
        {
            "scenario_id": "legit_tournament_prize_batch",
            "title": "Tournament prize batch payout",
            "pattern_family": "LEGITIMATE",
            "risk_tier": "low",
            "expected": {
                "target_id": target,
                "l1_primary_rules": [],
                "l2_fallback_action": "NORMAL",
                "max_p95_ms": DEFAULT_MAX_P95_MS,
                "notes": "Burst payout from official system account.",
            },
            "events": events,
        }
    )

    return scenarios


def _build_rule_boundaries(factory: EventFactory) -> list[dict[str, Any]]:
    def event(
        *,
        actor_id: str,
        target_id: str,
        amount: int,
        market_avg: int,
        chat: str | None = None,
        item_id: str = "itm_boundary_probe_01",
    ) -> dict[str, Any]:
        return factory.make(
            actor_id=actor_id,
            target_id=target_id,
            currency_amount=amount,
            market_avg_price=market_avg,
            recent_chat_log=chat,
            actor_level=42,
            account_age_days=365,
            item_id=item_id,
        )

    cases: list[dict[str, Any]] = [
        {
            "rule_id": "R1",
            "variant": "just_below",
            "description": "Total received stays one unit below the cumulative amount threshold.",
            "expected_triggered_rules": [],
            "expected_screened": False,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id="acct_boundary_r1_just_below_sender",
                    target_id="acct_boundary_r1_just_below_target",
                    amount=AMOUNT_THRESHOLD - 1,
                    market_avg=20_000,
                )
            ],
        },
        {
            "rule_id": "R1",
            "variant": "at_threshold",
            "description": "Total received lands exactly on the cumulative amount threshold.",
            "expected_triggered_rules": ["R1"],
            "expected_screened": True,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id="acct_boundary_r1_at_threshold_sender",
                    target_id="acct_boundary_r1_at_threshold_target",
                    amount=AMOUNT_THRESHOLD,
                    market_avg=20_000,
                )
            ],
        },
        {
            "rule_id": "R1",
            "variant": "just_above",
            "description": "Total received exceeds the cumulative amount threshold by one unit.",
            "expected_triggered_rules": ["R1"],
            "expected_screened": True,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id="acct_boundary_r1_just_above_sender",
                    target_id="acct_boundary_r1_just_above_target",
                    amount=AMOUNT_THRESHOLD + 1,
                    market_avg=20_000,
                )
            ],
        },
        {
            "rule_id": "R2",
            "variant": "just_below",
            "description": "Transaction count stops one event short of the burst threshold.",
            "expected_triggered_rules": [],
            "expected_screened": False,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id=f"acct_boundary_r2_just_below_sender_{idx:02d}",
                    target_id="acct_boundary_r2_just_below_target",
                    amount=10_000,
                    market_avg=1_000,
                    item_id="itm_boundary_r2_just_below",
                )
                for idx in range(1, TX_COUNT_THRESHOLD)
            ],
        },
        {
            "rule_id": "R2",
            "variant": "at_threshold",
            "description": "Transaction count lands exactly on the burst threshold.",
            "expected_triggered_rules": ["R2"],
            "expected_screened": True,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id=f"acct_boundary_r2_at_threshold_sender_{idx:02d}",
                    target_id="acct_boundary_r2_at_threshold_target",
                    amount=10_000,
                    market_avg=1_000,
                    item_id="itm_boundary_r2_at_threshold",
                )
                for idx in range(1, TX_COUNT_THRESHOLD + 1)
            ],
        },
        {
            "rule_id": "R2",
            "variant": "just_above",
            "description": "Transaction count exceeds the burst threshold by one event.",
            "expected_triggered_rules": ["R2"],
            "expected_screened": True,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id=f"acct_boundary_r2_just_above_sender_{idx:02d}",
                    target_id="acct_boundary_r2_just_above_target",
                    amount=10_000,
                    market_avg=1_000,
                    item_id="itm_boundary_r2_just_above",
                )
                for idx in range(1, TX_COUNT_THRESHOLD + 2)
            ],
        },
        {
            "rule_id": "R3",
            "variant": "just_below",
            "description": "Trade amount stays one unit below the market-average multiplier threshold.",
            "expected_triggered_rules": [],
            "expected_screened": False,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id="acct_boundary_r3_just_below_sender",
                    target_id="acct_boundary_r3_just_below_target",
                    amount=(1_000 * MARKET_AVG_MULTIPLIER) - 1,
                    market_avg=1_000,
                )
            ],
        },
        {
            "rule_id": "R3",
            "variant": "at_threshold",
            "description": "Trade amount lands exactly on the market-average multiplier threshold.",
            "expected_triggered_rules": ["R3"],
            "expected_screened": True,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id="acct_boundary_r3_at_threshold_sender",
                    target_id="acct_boundary_r3_at_threshold_target",
                    amount=1_000 * MARKET_AVG_MULTIPLIER,
                    market_avg=1_000,
                )
            ],
        },
        {
            "rule_id": "R3",
            "variant": "just_above",
            "description": "Trade amount exceeds the market-average multiplier threshold by one unit.",
            "expected_triggered_rules": ["R3"],
            "expected_screened": True,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id="acct_boundary_r3_just_above_sender",
                    target_id="acct_boundary_r3_just_above_target",
                    amount=(1_000 * MARKET_AVG_MULTIPLIER) + 1,
                    market_avg=1_000,
                )
            ],
        },
        {
            "rule_id": "R4",
            "variant": "just_below",
            "description": "Chat text is one token short of the slang regex match.",
            "expected_triggered_rules": [],
            "expected_screened": False,
            "expected_needs_l2": False,
            "events": [
                event(
                    actor_id="acct_boundary_r4_just_below_sender",
                    target_id="acct_boundary_r4_just_below_target",
                    amount=50_000,
                    market_avg=1_000,
                    chat="PayPa",
                )
            ],
        },
        {
            "rule_id": "R4",
            "variant": "at_threshold",
            "description": "Chat text includes the minimum supported slang token.",
            "expected_triggered_rules": ["R4"],
            "expected_screened": True,
            "expected_needs_l2": True,
            "events": [
                event(
                    actor_id="acct_boundary_r4_at_threshold_sender",
                    target_id="acct_boundary_r4_at_threshold_target",
                    amount=50_000,
                    market_avg=1_000,
                    chat="PayPal",
                )
            ],
        },
        {
            "rule_id": "R4",
            "variant": "just_above",
            "description": "Chat text combines multiple slang markers beyond the minimum match.",
            "expected_triggered_rules": ["R4"],
            "expected_screened": True,
            "expected_needs_l2": True,
            "events": [
                event(
                    actor_id="acct_boundary_r4_just_above_sender",
                    target_id="acct_boundary_r4_just_above_target",
                    amount=50_000,
                    market_avg=1_000,
                    chat="PayPal 14k",
                )
            ],
        },
    ]

    return cases


def _build_timeline_variations(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenarios_by_id = {scenario["scenario_id"]: scenario for scenario in scenarios}

    def variation(
        *,
        variation_id: str,
        scenario_id: str,
        variation_type: str,
        title: str,
        description: str,
        arrival_order: list[int],
        duplicate_indices: list[int] | None = None,
        delayed_indices: list[int] | None = None,
    ) -> dict[str, Any]:
        base_scenario = scenarios_by_id[scenario_id]
        base_events = base_scenario["events"]

        replay_events = [base_events[index] for index in arrival_order]
        duplicate_event_ids = [
            base_events[index]["event_id"] for index in (duplicate_indices or [])
        ]
        delayed_event_ids = [
            base_events[index]["event_id"] for index in (delayed_indices or [])
        ]

        return {
            "variation_id": variation_id,
            "scenario_id": scenario_id,
            "title": title,
            "variation_type": variation_type,
            "description": description,
            "risk_tier": base_scenario["risk_tier"],
            "pattern_family": base_scenario["pattern_family"],
            "target_id": base_scenario["expected"]["target_id"],
            "canonical_event_ids": [event["event_id"] for event in base_events],
            "arrival_event_ids": [event["event_id"] for event in replay_events],
            "duplicate_event_ids": duplicate_event_ids,
            "delayed_event_ids": delayed_event_ids,
            "events": replay_events,
        }

    return [
        variation(
            variation_id="timeline_out_of_order_layering_chain",
            scenario_id="fraud_layering_chain_exit",
            variation_type="out_of_order_arrival",
            title="Layering chain with out-of-order arrival",
            description="Bridge-leg events arrive in a non-canonical order while preserving their original timestamps.",
            arrival_order=[0, 1, 3, 2, 4, 5, 7, 6, 8, 9],
            delayed_indices=[2, 6],
        ),
        variation(
            variation_id="timeline_delayed_flash_sale_peak",
            scenario_id="gray_flash_sale_peak",
            variation_type="delayed_arrival",
            title="Flash-sale burst with delayed arrivals",
            description="Two earlier sale events arrive after newer ones to simulate ingest lag and queue jitter.",
            arrival_order=[0, 1, 2, 5, 6, 3, 4, 7, 8, 9],
            delayed_indices=[3, 4],
        ),
        variation(
            variation_id="timeline_duplicate_friend_gifts",
            scenario_id="legit_friend_gifts_low_value",
            variation_type="duplicate_delivery",
            title="Friend gifts with duplicate delivery",
            description="The transport replays one gift event, reproducing at-least-once delivery against a legitimate baseline.",
            arrival_order=[0, 1, 2, 3, 4, 4, 5, 6, 7, 8],
            duplicate_indices=[4],
        ),
    ]


def _write_outputs(
    output_dir: Path,
    seed: int,
    scenarios: list[dict[str, Any]],
    rule_boundaries: list[dict[str, Any]],
    timeline_variations: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    if DATASET_CHANGELOG[0]["version"] != DATASET_VERSION:
        raise ValueError("DATASET_CHANGELOG must be ordered newest-first and match DATASET_VERSION")

    current_release = DATASET_CHANGELOG[0]

    flat_events: list[dict[str, Any]] = []
    for scenario in scenarios:
        for order, event in enumerate(scenario["events"], start=1):
            flat_events.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "scenario_risk_tier": scenario["risk_tier"],
                    "sequence": order,
                    "event": event,
                }
            )

    manifest = {
        "dataset": "susanoh-operational-testbench",
        "dataset_version": DATASET_VERSION,
        "version": DATASET_VERSION,  # kept for backward compat with older runners that read "version"
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "seed": seed,
        "scenario_count": len(scenarios),
        "event_count": len(flat_events),
        "changelog": DATASET_CHANGELOG,
        "scenarios": scenarios,
    }

    (output_dir / "scenarios.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    with (output_dir / "events.jsonl").open("w", encoding="utf-8") as fp:
        for row in flat_events:
            fp.write(json.dumps(row, ensure_ascii=True) + "\n")

    boundary_manifest = {
        "dataset": "susanoh-operational-testbench-boundaries",
        "dataset_version": manifest["dataset_version"],
        "version": manifest["version"],  # kept for backward compat
        "generated_at": manifest["generated_at"],
        "seed": seed,
        "case_count": len(rule_boundaries),
        "changelog": DATASET_CHANGELOG,
        "cases": rule_boundaries,
    }
    (output_dir / "rule_boundaries.json").write_text(
        json.dumps(boundary_manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    timeline_manifest = {
        "dataset": "susanoh-operational-testbench-timeline-variations",
        "dataset_version": manifest["dataset_version"],
        "version": manifest["version"],  # kept for backward compat
        "generated_at": manifest["generated_at"],
        "seed": seed,
        "case_count": len(timeline_variations),
        "changelog": DATASET_CHANGELOG,
        "cases": timeline_variations,
    }
    (output_dir / "timeline_variations.json").write_text(
        json.dumps(timeline_manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    summary_lines = [
        "# Operational Testbench Dataset (Seed)",
        "",
        f"- Dataset version: `{manifest['dataset_version']}`",
        f"- Seed: `{seed}`",
        f"- Scenario count: `{manifest['scenario_count']}`",
        f"- Event count: `{manifest['event_count']}`",
        f"- Rule boundary cases: `{boundary_manifest['case_count']}`",
        f"- Timeline variation cases: `{timeline_manifest['case_count']}`",
        f"- Released at: `{current_release['released_at']}`",
        f"- Current release summary: {current_release['summary']}",
        "",
        "## Risk-tier distribution",
    ]

    tier_counts: dict[str, int] = {}
    for scenario in scenarios:
        tier = scenario["risk_tier"]
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    for tier in sorted(tier_counts):
        summary_lines.append(f"- `{tier}`: {tier_counts[tier]} scenarios")

    summary_lines.extend(
        [
            "",
            "## Files",
            "- `scenarios.json`: scenario-level manifest, expectations (including `max_p95_ms`), and full event sequences.",
            "- `events.jsonl`: flattened stream for replay/soak test ingestion.",
            "- `rule_boundaries.json`: R1-R4 threshold boundary cases (`just_below`, `at_threshold`, `just_above`) validated against `L1Engine`.",
            "- `timeline_variations.json`: out-of-order arrival / delayed arrival / duplicate delivery replay cases derived from canonical scenarios.",
        ]
    )

    fault_scenarios = [
        scenario for scenario in scenarios if isinstance(scenario.get("fault_injection"), dict)
    ]
    if fault_scenarios:
        summary_lines.extend(["", "## Regression Fault Injection"])
        for scenario in fault_scenarios:
            summary_lines.append(
                "- "
                f"`{scenario['scenario_id']}`: "
                f"`{scenario['fault_injection']['type']}` "
                "(applies only to local regression mode)"
            )

    summary_lines.extend(["", "## Rule Boundaries"])
    for rule_id in ("R1", "R2", "R3", "R4"):
        variants = [
            case["variant"] for case in rule_boundaries if case["rule_id"] == rule_id
        ]
        summary_lines.append(
            f"- `{rule_id}`: {', '.join(f'`{variant}`' for variant in variants)}"
        )

    summary_lines.extend(["", "## Timeline Variations"])
    for case in timeline_variations:
        summary_lines.append(
            "- "
            f"`{case['variation_type']}`: "
            f"`{case['variation_id']}` -> `{case['scenario_id']}`"
        )

    summary_lines.extend(["", "## Changelog"])
    for release in DATASET_CHANGELOG:
        summary_lines.append(f"- `{release['version']}` ({release['released_at']}): {release['summary']}")
        previous_version = release.get("previous_version")
        if previous_version:
            summary_lines.append(f"  Compare from `{previous_version}`")
        for change in release["changes"]:
            summary_lines.append(f"  - {change}")

    summary_lines.extend(
        [
            "",
            "## Regeneration",
            "```bash",
            "python3 scripts/generate_testbench_dataset.py --seed 20260305 --output tests/fixtures/testbench",
            "```",
        ]
    )

    (output_dir / "README.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic Susanoh testbench fixtures.")
    parser.add_argument(
        "--seed",
        type=int,
        default=20260305,
        help="Pseudo-random seed for deterministic scenario generation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/testbench"),
        help="Output directory for scenarios.json/events.jsonl.",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    # Use a far-future timestamp so in-memory window purging (which relies on now())
    # does not drop fixture events during replay tests.
    factory = EventFactory(started_at=datetime(2099, 1, 1, 0, 0, tzinfo=UTC))
    scenarios = _build_scenarios(factory=factory, rng=rng)
    rule_boundaries = _build_rule_boundaries(factory=factory)
    timeline_variations = _build_timeline_variations(scenarios)

    _write_outputs(
        args.output,
        seed=args.seed,
        scenarios=scenarios,
        rule_boundaries=rule_boundaries,
        timeline_variations=timeline_variations,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(args.output),
                "seed": args.seed,
                "scenarios": len(scenarios),
                "events": sum(len(s["events"]) for s in scenarios),
                "rule_boundary_cases": len(rule_boundaries),
                "timeline_variation_cases": len(timeline_variations),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

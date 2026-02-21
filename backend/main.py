from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.models import (
    AccountState,
    GameEventLog,
    WithdrawRequest,
)
from backend.state_machine import StateMachine
from backend.l1_screening import L1Engine
from backend.l2_gemini import L2Engine
from backend.mock_server import MockGameServer, DemoStreamer

app = FastAPI(title="Susanoh", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sm = StateMachine()
l1 = L1Engine()
l2 = L2Engine()
mock = MockGameServer()
streamer: DemoStreamer | None = None


async def _process_event(event: GameEventLog) -> dict:
    sm.get_or_create(event.actor_id)
    sm.get_or_create(event.target_id)

    result = l1.screen(event)

    if result.screened and result.recommended_action:
        current = sm.get_or_create(event.target_id)
        if current == AccountState.NORMAL:
            sm.transition(
                event.target_id,
                AccountState.RESTRICTED_WITHDRAWAL,
                "L1_SCREENING",
                ",".join(result.triggered_rules),
                f"L1ルール発火: {result.triggered_rules}",
            )

    if result.needs_l2 or (
        result.screened
        and sm.get_or_create(event.target_id) != AccountState.NORMAL
    ):
        current_state = sm.get_or_create(event.target_id)
        analysis_req = l1.build_analysis_request(
            event.target_id, event, result.triggered_rules, current_state
        )
        asyncio.create_task(_run_l2(analysis_req))

    return {"screened": result.screened, "triggered_rules": result.triggered_rules}


async def _run_l2(analysis_req) -> None:
    try:
        verdict = await l2.analyze(analysis_req)
        current = sm.get_or_create(verdict.target_id)
        target_state = verdict.recommended_action

        if target_state == AccountState.BANNED:
            if current == AccountState.RESTRICTED_WITHDRAWAL:
                sm.transition(
                    verdict.target_id,
                    AccountState.UNDER_SURVEILLANCE,
                    "L2_ANALYSIS",
                    "GEMINI_VERDICT",
                    f"L2中間遷移 (risk_score: {verdict.risk_score})",
                )
            current = sm.get_or_create(verdict.target_id)
            if current == AccountState.UNDER_SURVEILLANCE:
                sm.transition(
                    verdict.target_id,
                    AccountState.BANNED,
                    "L2_ANALYSIS",
                    "GEMINI_VERDICT",
                    f"RMT確定 (risk_score: {verdict.risk_score})",
                )
        elif target_state == AccountState.UNDER_SURVEILLANCE:
            if current == AccountState.RESTRICTED_WITHDRAWAL:
                sm.transition(
                    verdict.target_id,
                    AccountState.UNDER_SURVEILLANCE,
                    "L2_ANALYSIS",
                    "GEMINI_VERDICT",
                    f"要監視 (risk_score: {verdict.risk_score})",
                )
    except Exception:
        pass


# --- Health ---
@app.get("/")
async def root():
    return {"status": "ok", "service": "Susanoh"}


# --- Events ---
@app.post("/api/v1/events")
async def post_event(event: GameEventLog):
    return await _process_event(event)


@app.get("/api/v1/events/recent")
async def get_recent_events(limit: int = Query(default=20, le=200)):
    return l1.get_recent_events(limit)


# --- Users ---
@app.get("/api/v1/users")
async def get_users(state: Optional[str] = None):
    state_filter = None
    if state:
        try:
            state_filter = AccountState(state)
        except ValueError:
            raise HTTPException(400, f"Invalid state: {state}")
    return sm.get_all_users(state_filter)


@app.get("/api/v1/users/{user_id}")
async def get_user(user_id: str):
    st = sm.get_or_create(user_id)
    return {"user_id": user_id, "state": st.value}


# --- Withdraw ---
@app.post("/api/v1/withdraw")
async def withdraw(req: WithdrawRequest):
    state = sm.get_or_create(req.user_id)
    if state == AccountState.NORMAL:
        return {"status": "ok", "message": "出金処理完了"}
    sm.blocked_withdrawals += 1
    if state == AccountState.BANNED:
        raise HTTPException(403, "アカウントは凍結されています")
    raise HTTPException(423, "出金が制限されています")


# --- Release ---
@app.post("/api/v1/users/{user_id}/release")
async def release_user(user_id: str):
    current = sm.get_or_create(user_id)
    if current != AccountState.UNDER_SURVEILLANCE:
        raise HTTPException(400, f"解除できるのはUNDER_SURVEILLANCE状態のみです（現在: {current.value}）")
    ok = sm.transition(user_id, AccountState.NORMAL, "MANUAL_RELEASE", "OPERATOR", "手動解除")
    if not ok:
        raise HTTPException(500, "遷移に失敗しました")
    return {"user_id": user_id, "state": AccountState.NORMAL.value}


# --- Stats ---
@app.get("/api/v1/stats")
async def get_stats():
    stats = sm.get_stats()
    stats["l1_flags"] = l1.l1_flag_count
    stats["l2_analyses"] = len(l2.analysis_results)
    stats["total_events"] = len(l1.recent_events)
    return stats


# --- Transitions ---
@app.get("/api/v1/transitions")
async def get_transitions(limit: int = Query(default=50, le=200)):
    return sm.get_transitions(limit)


# --- Graph ---
@app.get("/api/v1/graph")
async def get_graph():
    return l1.get_graph_data(sm.accounts)


# --- L2 Analyze ---
@app.post("/api/v1/analyze")
async def analyze(event: GameEventLog):
    current_state = sm.get_or_create(event.target_id)
    result = l1.screen(event)
    analysis_req = l1.build_analysis_request(
        event.target_id, event, result.triggered_rules, current_state
    )
    verdict = await l2.analyze(analysis_req)
    return verdict


@app.get("/api/v1/analyses")
async def get_analyses(limit: int = Query(default=20, le=100)):
    return l2.get_analyses(limit)


# --- Demo ---
@app.post("/api/v1/demo/scenario/{name}")
async def run_scenario(name: str):
    if name == "normal":
        events = [mock.generate_normal_event() for _ in range(10)]
    elif name == "rmt-smurfing":
        events = mock.generate_smurfing_events()
    elif name == "layering":
        events = mock.generate_layering_events()
    else:
        raise HTTPException(400, f"Unknown scenario: {name}")

    results = []
    for event in events:
        r = await _process_event(event)
        results.append(r)
    return {"scenario": name, "events_sent": len(events), "results": results}


@app.post("/api/v1/demo/start")
async def demo_start():
    global streamer
    if streamer and streamer.running:
        return {"status": "already_running"}
    streamer = DemoStreamer(_process_event)
    await streamer.start()
    return {"status": "started"}


@app.post("/api/v1/demo/stop")
async def demo_stop():
    global streamer
    if streamer:
        await streamer.stop()
        streamer = None
    return {"status": "stopped"}

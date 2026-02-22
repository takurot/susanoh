from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.models import (
    AccountState,
    GameEventLog,
    ShowcaseResult,
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


def reset_runtime_state() -> None:
    sm.reset()
    l1.reset()
    l2.reset()


async def _process_event(event: GameEventLog) -> dict:
    return await _process_event_with_options(event, schedule_l2=True)


async def _process_event_with_options(event: GameEventLog, schedule_l2: bool) -> dict:
    """Process one event and optionally schedule background L2.

    `schedule_l2=False` is used by showcase flow to keep L2 execution deterministic:
    the endpoint runs one explicit synchronous L2 call and returns the final summary.
    """
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
                f"L1 rule triggered: {result.triggered_rules}",
            )

    if schedule_l2 and (result.needs_l2 or (
        result.screened
        and sm.get_or_create(event.target_id) != AccountState.NORMAL
    )):
        current_state = sm.get_or_create(event.target_id)
        analysis_req = l1.build_analysis_request(
            event.target_id, event, result.triggered_rules, current_state
        )
        asyncio.create_task(_run_l2(analysis_req))

    return {"screened": result.screened, "triggered_rules": result.triggered_rules}


async def _run_l2(analysis_req) -> None:
    try:
        verdict = await l2.analyze(analysis_req)
        _apply_l2_verdict(verdict.target_id, verdict.recommended_action, verdict.risk_score)
    except Exception:
        pass


def _apply_l2_verdict(target_id: str, target_state: AccountState, risk_score: int) -> None:
    current = sm.get_or_create(target_id)
    if target_state == AccountState.BANNED:
        if current == AccountState.RESTRICTED_WITHDRAWAL:
            sm.transition(
                target_id,
                AccountState.UNDER_SURVEILLANCE,
                "L2_ANALYSIS",
                "GEMINI_VERDICT",
                f"L2 intermediate transition (risk_score: {risk_score})",
            )
        current = sm.get_or_create(target_id)
        if current == AccountState.UNDER_SURVEILLANCE:
            sm.transition(
                target_id,
                AccountState.BANNED,
                "L2_ANALYSIS",
                "GEMINI_VERDICT",
                f"RMT confirmed (risk_score: {risk_score})",
            )
    elif target_state == AccountState.UNDER_SURVEILLANCE:
        if current == AccountState.RESTRICTED_WITHDRAWAL:
            sm.transition(
                target_id,
                AccountState.UNDER_SURVEILLANCE,
                "L2_ANALYSIS",
                "GEMINI_VERDICT",
                f"Requires surveillance (risk_score: {risk_score})",
            )
    elif target_state == AccountState.NORMAL:
        if current in (AccountState.RESTRICTED_WITHDRAWAL, AccountState.UNDER_SURVEILLANCE):
            sm.transition(
                target_id,
                AccountState.NORMAL,
                "L2_ANALYSIS",
                "GEMINI_VERDICT",
                f"Low-risk auto recovery (risk_score: {risk_score})",
            )


def _withdraw_status(user_id: str) -> tuple[int, str]:
    """Return withdraw decision without mutating counters."""
    state = sm.get_or_create(user_id)
    if state == AccountState.NORMAL:
        return 200, "Withdrawal completed"
    if state == AccountState.BANNED:
        return 403, "Account is banned"
    return 423, "Withdrawal is restricted"


def _record_blocked_withdrawal(status_code: int) -> None:
    if status_code != 200:
        sm.blocked_withdrawals += 1


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
    status_code, message = _withdraw_status(req.user_id)
    _record_blocked_withdrawal(status_code)
    if status_code == 200:
        return {"status": "ok", "message": message}
    raise HTTPException(status_code, message)


# --- Release ---
@app.post("/api/v1/users/{user_id}/release")
async def release_user(user_id: str):
    current = sm.get_or_create(user_id)
    releasable_states = {AccountState.RESTRICTED_WITHDRAWAL, AccountState.UNDER_SURVEILLANCE}
    if current not in releasable_states:
        raise HTTPException(
            400,
            "Only RESTRICTED_WITHDRAWAL or UNDER_SURVEILLANCE accounts can be released "
            f"(current: {current.value})",
        )
    ok = sm.transition(user_id, AccountState.NORMAL, "MANUAL_RELEASE", "OPERATOR", "Manual release")
    if not ok:
        raise HTTPException(500, "State transition failed")
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


@app.post("/api/v1/demo/showcase/smurfing", response_model=ShowcaseResult)
async def run_showcase_smurfing():
    target_user = "user_boss_01"
    events = mock.generate_smurfing_events()

    scenario_results: list[dict] = []
    trigger_event: GameEventLog | None = None
    trigger_rules: list[str] = []
    analysis_error: str | None = None

    for event in events:
        result = await _process_event_with_options(event, schedule_l2=False)
        scenario_results.append(result)
        if event.target_id == target_user:
            trigger_event = event
            if result["triggered_rules"]:
                trigger_rules = result["triggered_rules"]

    latest_analysis = None
    if trigger_event:
        analysis_req = l1.build_analysis_request(
            target_user,
            trigger_event,
            trigger_rules,
            sm.get_or_create(target_user),
        )
        try:
            verdict = await l2.analyze(analysis_req)
            _apply_l2_verdict(verdict.target_id, verdict.recommended_action, verdict.risk_score)
            latest_analysis = verdict
        except Exception as exc:
            analysis_error = f"L2 analysis failed: {exc}"
    else:
        analysis_error = "L2 analysis skipped: no event matched target_user"

    status_code, _ = _withdraw_status(target_user)
    if latest_analysis is None:
        latest_analysis = next(
            (analysis for analysis in l2.get_analyses(limit=50) if analysis.target_id == target_user),
            None,
        )

    rules = sorted({rule for result in scenario_results for rule in result["triggered_rules"]})
    latest_reasoning = latest_analysis.reasoning if latest_analysis else None
    if analysis_error:
        latest_reasoning = f"{latest_reasoning} / {analysis_error}" if latest_reasoning else analysis_error

    return ShowcaseResult(
        target_user=target_user,
        triggered_rules=rules,
        withdraw_status_code=status_code,
        latest_state=sm.get_or_create(target_user),
        latest_risk_score=latest_analysis.risk_score if latest_analysis else None,
        latest_reasoning=latest_reasoning,
        analysis_error=analysis_error,
    )


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

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, HTTPException, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta

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
from backend.persistence import PersistenceStore
from backend.redis_client import RedisClient
from backend.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    MOCK_USERS_DB,
    Role,
    User,
    create_access_token,
    get_current_user,
    get_user,
    require_roles,
    verify_password,
)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup arq pool
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        app.state.arq_pool = await create_pool(RedisSettings.from_dsn(redis_url))
    except Exception as e:
        logger.warning(f"Failed to create arq pool (continuing without async worker): {e}")
        app.state.arq_pool = None
    
    yield
    # Shutdown logic
    if app.state.arq_pool:
        await app.state.arq_pool.close()
    await redis_client.close()

app = FastAPI(title="Susanoh", version="0.1.0", lifespan=lifespan)
app.state.arq_pool = None
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = RedisClient()
sm = StateMachine(redis_client.get_client())
l1 = L1Engine(redis_client.get_client())
l2 = L2Engine(redis_client=redis_client.get_client())
mock = MockGameServer()
streamer: DemoStreamer | None = None
persistence_store = PersistenceStore.from_env()
persistence_store.init_schema()


def _configured_api_keys() -> set[str]:
    raw = os.environ.get("SUSANOH_API_KEYS", "")
    return {key.strip() for key in raw.split(",") if key.strip()}


@app.middleware("http")
async def api_key_auth_middleware(request, call_next):
    if request.url.path.startswith("/api/v1"):
        if request.method.upper() == "OPTIONS":
            return await call_next(request)
        allowed_keys = _configured_api_keys()
        if allowed_keys:
            provided = request.headers.get("X-API-KEY")
            if not provided:
                return JSONResponse(status_code=401, content={"detail": "Missing X-API-KEY header"})
            if provided not in allowed_keys:
                return JSONResponse(status_code=401, content={"detail": "Invalid API key"})

    return await call_next(request)


async def reset_runtime_state() -> None:
    await sm.reset()
    await l1.reset()
    await l2.reset()
    persistence_store.clear_all()


def _persist_runtime_snapshot() -> None:
    # Snapshotting to DB is primarily for in-memory mode in this prototype.
    # However, we allow it even with Redis if DATABASE_URL is set (Finding 2).
    # Note that sm.accounts and l1.recent_events will contain the most recent 
    # data since StateMachine/L1Engine now maintain local caches.
    try:
        persistence_store.persist_runtime_snapshot(sm=sm, l1=l1, l2_results=l2.analysis_results)
    except Exception as exc:
        logger.warning("Failed to persist runtime snapshot: %s", exc)


async def _process_event(event: GameEventLog) -> dict:
    return await _process_event_with_options(event, schedule_l2=True)


async def _process_event_with_options(event: GameEventLog, schedule_l2: bool) -> dict:
    """Process one event and optionally schedule background L2.

    `schedule_l2=False` is used by showcase flow to keep L2 execution deterministic:
    the endpoint runs one explicit synchronous L2 call and returns the final summary.
    """
    await sm.get_or_create(event.actor_id)
    await sm.get_or_create(event.target_id)

    result = await l1.screen(event)

    if result.screened and result.recommended_action:
        current = await sm.get_or_create(event.target_id)
        if current == AccountState.NORMAL:
            await sm.transition(
                event.target_id,
                AccountState.RESTRICTED_WITHDRAWAL,
                "L1_SCREENING",
                ",".join(result.triggered_rules),
                f"L1 rule triggered: {result.triggered_rules}",
            )

    if schedule_l2 and (result.needs_l2 or (
        result.screened
        and await sm.get_or_create(event.target_id) != AccountState.NORMAL
    )):
        current_state = await sm.get_or_create(event.target_id)
        analysis_req = await l1.build_analysis_request(
            event.target_id, event, result.triggered_rules, current_state
        )
        if hasattr(app.state, "arq_pool") and app.state.arq_pool:
            await app.state.arq_pool.enqueue_job("analyze_l2_task", analysis_req)
        else:
            asyncio.create_task(_run_l2(analysis_req))

    _persist_runtime_snapshot()
    return {"screened": result.screened, "triggered_rules": result.triggered_rules}


async def _run_l2(analysis_req) -> None:
    try:
        verdict = await l2.analyze(analysis_req)
        await sm.apply_l2_verdict(verdict.target_id, verdict.recommended_action, verdict.risk_score)
        _persist_runtime_snapshot()
    except Exception as exc:
        logger.error(f"Synchronous L2 analysis task failed: {exc}", exc_info=True)


async def _withdraw_status(user_id: str) -> tuple[int, str]:
    """Return withdraw decision without mutating counters."""
    state = await sm.get_or_create(user_id)
    if state == AccountState.NORMAL:
        return 200, "Withdrawal completed"
    if state == AccountState.BANNED:
        return 403, "Account is banned"
    return 423, "Withdrawal is restricted"


async def _record_blocked_withdrawal(status_code: int) -> None:
    if status_code != 200:
        await sm.increment_blocked_withdrawals()


# --- Health ---
@app.get("/")
async def root():
    return {"status": "ok", "service": "Susanoh"}


# --- Auth ---
@app.post("/api/v1/auth/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user_dict = get_user(MOCK_USERS_DB, form_data.username)
    if not user_dict or not verify_password(form_data.password, user_dict["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_dict["username"], "role": user_dict["role"].value},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user_dict["role"].value}


# --- Events ---
@app.post("/api/v1/events")
async def post_event(event: GameEventLog):
    return await _process_event(event)


@app.get("/api/v1/events/recent")
async def get_recent_events(limit: int = Query(default=20, le=200)):
    return await l1.get_recent_events(limit)


# --- Users ---
@app.get("/api/v1/users", dependencies=[Depends(require_roles([Role.ADMIN, Role.OPERATOR, Role.VIEWER]))])
async def get_users(state: Optional[str] = None):
    state_filter = None
    if state:
        try:
            state_filter = AccountState(state)
        except ValueError:
            raise HTTPException(400, f"Invalid state: {state}")
    return await sm.get_all_users(state_filter)


@app.get("/api/v1/users/{user_id}", dependencies=[Depends(require_roles([Role.ADMIN, Role.OPERATOR, Role.VIEWER]))])
async def get_user_by_id(user_id: str):
    st = await sm.get_or_create(user_id)
    return {"user_id": user_id, "state": st.value}


# --- Withdraw ---
@app.post("/api/v1/withdraw")
async def withdraw(req: WithdrawRequest):
    status_code, message = await _withdraw_status(req.user_id)
    await _record_blocked_withdrawal(status_code)
    if status_code == 200:
        return {"status": "ok", "message": message}
    raise HTTPException(status_code, message)


# --- Release ---
@app.post("/api/v1/users/{user_id}/release", dependencies=[Depends(require_roles([Role.ADMIN, Role.OPERATOR]))])
async def release_user(user_id: str):
    current = await sm.get_or_create(user_id)
    releasable_states = {AccountState.RESTRICTED_WITHDRAWAL, AccountState.UNDER_SURVEILLANCE}
    if current not in releasable_states:
        raise HTTPException(
            400,
            "Only RESTRICTED_WITHDRAWAL or UNDER_SURVEILLANCE accounts can be released "
            f"(current: {current.value})",
        )
    ok = await sm.transition(user_id, AccountState.NORMAL, "MANUAL_RELEASE", "OPERATOR", "Manual release")
    if not ok:
        raise HTTPException(500, "State transition failed")
    _persist_runtime_snapshot()
    return {"user_id": user_id, "state": AccountState.NORMAL.value}


# --- Stats ---
@app.get("/api/v1/stats", dependencies=[Depends(require_roles([Role.ADMIN, Role.OPERATOR, Role.VIEWER]))])
async def get_stats():
    stats = await sm.get_stats()
    stats["l1_flags"] = l1.l1_flag_count
    stats["l2_analyses"] = len(l2.analysis_results)
    stats["total_events"] = len(l1.recent_events)
    return stats


# --- Transitions ---
@app.get("/api/v1/transitions", dependencies=[Depends(require_roles([Role.ADMIN, Role.OPERATOR, Role.VIEWER]))])
async def get_transitions(limit: int = Query(default=50, le=200)):
    return await sm.get_transitions(limit)


# --- Graph ---
@app.get("/api/v1/graph", dependencies=[Depends(require_roles([Role.ADMIN, Role.OPERATOR, Role.VIEWER]))])
async def get_graph():
    # Resolve node states from Redis if available (Finding 4)
    recent = await l1.get_recent_events(limit=200)
    user_ids = set()
    for e in recent:
        user_ids.add(e["actor_id"])
        user_ids.add(e["target_id"])
    resolved = await sm.resolve_accounts(list(user_ids))
    return await l1.get_graph_data(resolved)


# --- L2 Analyze ---
@app.post("/api/v1/analyze", dependencies=[Depends(require_roles([Role.ADMIN, Role.OPERATOR]))])
async def analyze(event: GameEventLog):
    current_state = await sm.get_or_create(event.target_id)
    result = await l1.screen(event)
    analysis_req = await l1.build_analysis_request(
        event.target_id, event, result.triggered_rules, current_state
    )
    verdict = await l2.analyze(analysis_req)
    _persist_runtime_snapshot()
    return verdict


@app.get("/api/v1/analyses", dependencies=[Depends(require_roles([Role.ADMIN, Role.OPERATOR, Role.VIEWER]))])
async def get_analyses(limit: int = Query(default=20, le=100)):
    return await l2.get_analyses(limit)


# --- Demo ---
@app.post("/api/v1/demo/scenario/{name}", dependencies=[Depends(require_roles([Role.ADMIN]))])
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


@app.post("/api/v1/demo/showcase/smurfing", response_model=ShowcaseResult, dependencies=[Depends(require_roles([Role.ADMIN]))])
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
        analysis_req = await l1.build_analysis_request(
            target_user,
            trigger_event,
            trigger_rules,
            await sm.get_or_create(target_user),
        )
        try:
            verdict = await l2.analyze(analysis_req)
            await sm.apply_l2_verdict(verdict.target_id, verdict.recommended_action, verdict.risk_score)
            latest_analysis = verdict
            _persist_runtime_snapshot()
        except Exception as exc:
            analysis_error = f"L2 analysis failed: {exc}"
    else:
        analysis_error = "L2 analysis skipped: no event matched target_user"

    status_code, _ = await _withdraw_status(target_user)
    if latest_analysis is None:
        latest_analysis = next(
            (analysis for analysis in await l2.get_analyses(limit=50) if analysis.target_id == target_user),
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
        latest_state=await sm.get_or_create(target_user),
        latest_risk_score=latest_analysis.risk_score if latest_analysis else None,
        latest_reasoning=latest_reasoning,
        analysis_error=analysis_error,
    )


@app.post("/api/v1/demo/start", dependencies=[Depends(require_roles([Role.ADMIN]))])
async def demo_start():
    global streamer
    if streamer and streamer.running:
        return {"status": "already_running"}
    streamer = DemoStreamer(_process_event)
    await streamer.start()
    return {"status": "started"}


@app.post("/api/v1/demo/stop", dependencies=[Depends(require_roles([Role.ADMIN]))])
async def demo_stop():
    global streamer
    if streamer:
        await streamer.stop()
        streamer = None
    return {"status": "stopped"}

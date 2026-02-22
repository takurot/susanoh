from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from backend.models import AccountState, AnalysisRequest, ArbitrationResult
from backend.state_machine import StateMachine
from backend.l2_gemini import L2Engine
from backend.persistence import PersistenceStore

logger = logging.getLogger(__name__)

# Re-use apply_l2_verdict logic from main.py, but need to be careful with sm
# We'll create a standalone version or import it.
# To avoid circular imports, let's define it here for now or move it to a shared place.

async def apply_l2_verdict(sm: StateMachine, target_id: str, target_state: AccountState, risk_score: int) -> None:
    current = await sm.get_or_create(target_id)
    if target_state == AccountState.BANNED:
        if current == AccountState.RESTRICTED_WITHDRAWAL:
            await sm.transition(
                target_id,
                AccountState.UNDER_SURVEILLANCE,
                "L2_ANALYSIS",
                "GEMINI_VERDICT",
                f"L2 intermediate transition (risk_score: {risk_score})",
            )
        current = await sm.get_or_create(target_id)
        if current == AccountState.UNDER_SURVEILLANCE:
            await sm.transition(
                target_id,
                AccountState.BANNED,
                "L2_ANALYSIS",
                "GEMINI_VERDICT",
                f"RMT confirmed (risk_score: {risk_score})",
            )
    elif target_state == AccountState.UNDER_SURVEILLANCE:
        if current == AccountState.RESTRICTED_WITHDRAWAL:
            await sm.transition(
                target_id,
                AccountState.UNDER_SURVEILLANCE,
                "L2_ANALYSIS",
                "GEMINI_VERDICT",
                f"Requires surveillance (risk_score: {risk_score})",
            )
    elif target_state == AccountState.NORMAL:
        if current in (AccountState.RESTRICTED_WITHDRAWAL, AccountState.UNDER_SURVEILLANCE):
            await sm.transition(
                target_id,
                AccountState.NORMAL,
                "L2_ANALYSIS",
                "GEMINI_VERDICT",
                f"Low-risk auto recovery (risk_score: {risk_score})",
            )

async def analyze_l2_task(ctx: dict[Any, Any], analysis_req_json: str) -> None:
    # arq can pass objects if we use pickle, but json is safer if we wanted to scale.
    # However, AnalysisRequest is a complex Pydantic model.
    # arq's default is pickle, so we can just pass the object.
    
    # Actually, let's assume it's the object.
    analysis_req: AnalysisRequest = analysis_req_json # If it's already an object
    
    # ctx['redis'] is the arq redis pool
    sm = ctx['sm']
    l2 = ctx['l2']
    persistence = ctx['persistence']
    
    try:
        verdict: ArbitrationResult = await l2.analyze(analysis_req)
        await apply_l2_verdict(sm, verdict.target_id, verdict.recommended_action, verdict.risk_score)
        
        # Persist snapshot
        # Since persistence_store.persist_runtime_snapshot needs sm and l1,
        # we might need to be careful. The worker might not have full L1 state.
        # But Phase 1.3 says "separate L2 analysis... delegate to worker".
        # Persistence might be better handled by a separate background task or by the worker.
        # For now, let's just use what we have.
        try:
            persistence.persist_runtime_snapshot(sm=sm, l1=None, l2_results=l2.analysis_results)
        except Exception as exc:
            logger.warning("Worker failed to persist snapshot: %s", exc)
            
    except Exception as e:
        logger.error(f"Error in analyze_l2_task: {e}", exc_info=True)

async def startup(ctx: dict[Any, Any]) -> None:
    redis_pool = ctx['redis']
    ctx['sm'] = StateMachine(redis_pool)
    ctx['l2'] = L2Engine()
    ctx['persistence'] = PersistenceStore.from_env()
    ctx['persistence'].init_schema()
    logger.info("Worker started up")

async def shutdown(ctx: dict[Any, Any]) -> None:
    logger.info("Worker shutting down")

class WorkerSettings:
    functions = [analyze_l2_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

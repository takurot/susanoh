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

async def analyze_l2_task(ctx: dict[Any, Any], analysis_req: AnalysisRequest) -> None:
    # ctx['redis'] is the arq redis pool
    sm = ctx['sm']
    l2 = ctx['l2']
    persistence = ctx['persistence']
    
    try:
        verdict: ArbitrationResult = await l2.analyze(analysis_req)
        await sm.apply_l2_verdict(verdict.target_id, verdict.recommended_action, verdict.risk_score)
        
        # Persist snapshot (L1 is None in worker)
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

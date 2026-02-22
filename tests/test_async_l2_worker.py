import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from backend.worker import analyze_l2_task, apply_l2_verdict
from backend.models import (
    AccountState, 
    AnalysisRequest, 
    ArbitrationResult, 
    FraudType, 
    UserProfile, 
    GameEventLog, 
    ActionDetails, 
    ContextMetadata
)
from backend.state_machine import StateMachine

@pytest.mark.asyncio
async def test_apply_l2_verdict_to_banned():
    sm = MagicMock(spec=StateMachine)
    sm.get_or_create = AsyncMock(side_effect=[AccountState.RESTRICTED_WITHDRAWAL, AccountState.UNDER_SURVEILLANCE])
    sm.transition = AsyncMock(return_value=True)
    
    await apply_l2_verdict(sm, "u1", AccountState.BANNED, 100)
    
    # Should transition from RESTRICTED_WITHDRAWAL to UNDER_SURVEILLANCE, 
    # then from UNDER_SURVEILLANCE to BANNED.
    assert sm.transition.call_count == 2
    sm.transition.assert_any_call("u1", AccountState.UNDER_SURVEILLANCE, "L2_ANALYSIS", "GEMINI_VERDICT", "L2 intermediate transition (risk_score: 100)")
    sm.transition.assert_any_call("u1", AccountState.BANNED, "L2_ANALYSIS", "GEMINI_VERDICT", "RMT confirmed (risk_score: 100)")

@pytest.mark.asyncio
async def test_apply_l2_verdict_to_normal():
    sm = MagicMock(spec=StateMachine)
    sm.get_or_create = AsyncMock(return_value=AccountState.RESTRICTED_WITHDRAWAL)
    sm.transition = AsyncMock(return_value=True)
    
    await apply_l2_verdict(sm, "u1", AccountState.NORMAL, 10)
    
    sm.transition.assert_called_once_with("u1", AccountState.NORMAL, "L2_ANALYSIS", "GEMINI_VERDICT", "Low-risk auto recovery (risk_score: 10)")

@pytest.mark.asyncio
async def test_analyze_l2_task_success():
    ctx = {
        'redis': MagicMock(),
        'sm': MagicMock(spec=StateMachine),
        'l2': MagicMock(),
        'persistence': MagicMock()
    }
    
    analysis_req = AnalysisRequest(
        trigger_event=GameEventLog(event_id="e1", actor_id="a1", target_id="u1"),
        user_profile=UserProfile(user_id="u1", current_state=AccountState.RESTRICTED_WITHDRAWAL)
    )
    
    verdict = ArbitrationResult(
        target_id="u1",
        is_fraud=False,
        risk_score=10,
        fraud_type=FraudType.LEGITIMATE,
        recommended_action=AccountState.NORMAL,
        reasoning="Test reasoning",
        confidence=1.0
    )
    
    ctx['l2'].analyze = AsyncMock(return_value=verdict)
    ctx['l2'].analysis_results = [verdict]
    ctx['sm'].get_or_create = AsyncMock(return_value=AccountState.RESTRICTED_WITHDRAWAL)
    ctx['sm'].transition = AsyncMock(return_value=True)
    
    await analyze_l2_task(ctx, analysis_req)
    
    ctx['l2'].analyze.assert_called_once_with(analysis_req)
    ctx['sm'].transition.assert_called_once()
    ctx['persistence'].persist_runtime_snapshot.assert_called_once()

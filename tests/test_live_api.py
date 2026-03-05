import os
import pytest
from backend.models import (
    AnalysisRequest,
    UserProfile,
    GameEventLog,
    AccountState,
    ActionDetails,
    ContextMetadata,
)
from backend.l2_gemini import L2Engine, ArbitrationResult
from backend.live_api_verification import (
    load_live_api_verification_config,
    run_live_api_verification,
)

@pytest.mark.asyncio
@pytest.mark.live_api
@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="Requires GEMINI_API_KEY environment variable to run live API test."
)
async def test_gemini_live_analysis():
    # Construct a realistic RMT_SMURFING or MONEY_LAUNDERING scenario
    profile = UserProfile(
        user_id="live_test_user_001",
        current_state=AccountState.RESTRICTED_WITHDRAWAL,
        total_received_5min=150000,
        transaction_count_5min=8,
        unique_senders_5min=6,
    )
    
    trigger_event = GameEventLog(
        event_id="evt_live_001",
        actor_id="suspicious_sender_001",
        target_id="live_test_user_001",
        action_type="TRADE",
        action_details=ActionDetails(currency_amount=20000),
        context_metadata=ContextMetadata(recent_chat_log="transferring the 20k now, confirm"),
    )
    
    request = AnalysisRequest(
        user_profile=profile,
        trigger_event=trigger_event,
        triggered_rules=["R1", "R4"],
        related_events=[trigger_event], # Simplified
    )
    
    # Initialize Engine (In-memory mode, no Redis required for this basic check)
    engine = L2Engine()
    
    # Call the actual Gemini API
    result = await engine.analyze(request)
    
    # Assertions
    assert isinstance(result, ArbitrationResult)
    assert result.target_id == profile.user_id
    assert isinstance(result.risk_score, int)
    assert 0 <= result.risk_score <= 100
    assert isinstance(result.reasoning, str)
    assert len(result.reasoning) > 0 # Should have actually written an explanation
    
    # Validate logical consistency of the result
    if result.risk_score <= 30:
        assert result.recommended_action == AccountState.NORMAL
        assert result.is_fraud is False
    elif result.risk_score <= 70:
        assert result.recommended_action == AccountState.UNDER_SURVEILLANCE
        assert result.is_fraud is True
    else:
        assert result.recommended_action == AccountState.BANNED
        assert result.is_fraud is True


@pytest.mark.asyncio
@pytest.mark.live_api
@pytest.mark.skipif(
    not (
        os.environ.get("SUSANOH_STAGING_BASE_URL")
        and os.environ.get("SUSANOH_STAGING_PASSWORD")
    ),
    reason=(
        "Requires SUSANOH_STAGING_BASE_URL and SUSANOH_STAGING_PASSWORD "
        "to run staging live API verification."
    ),
)
async def test_staging_live_api_verification():
    config = load_live_api_verification_config()
    result = await run_live_api_verification(config)
    assert result["ok"] is True
    assert isinstance(result["latency_ms"], (int, float))
    assert 0 <= result["risk_score"] <= 100

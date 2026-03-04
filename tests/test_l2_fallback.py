import os
import pytest
from backend.models import (
    AccountState,
    ActionDetails,
    AnalysisRequest,
    ContextMetadata,
    GameEventLog,
    UserProfile,
)
from backend.l2_gemini import L2Engine


def _make_request(rules=None, amount=2_000_000, senders=6):
    return AnalysisRequest(
        trigger_event=GameEventLog(
            event_id="evt_test",
            actor_id="a",
            target_id="b",
            action_details=ActionDetails(currency_amount=amount),
            context_metadata=ContextMetadata(recent_chat_log="振込完了"),
        ),
        triggered_rules=rules or ["R1", "R4"],
        user_profile=UserProfile(
            user_id="b",
            current_state=AccountState.RESTRICTED_WITHDRAWAL,
            total_received_5min=amount,
            transaction_count_5min=8,
            unique_senders_5min=senders,
        ),
    )


@pytest.mark.asyncio
async def test_fallback_without_api_key():
    """Local fallback should work when API key is missing."""
    old = os.environ.pop("GEMINI_API_KEY", None)
    try:
        engine = L2Engine()
        result = await engine.analyze(_make_request())
        assert result.target_id == "b"
        assert result.risk_score > 0
        assert "Local fallback" in result.reasoning
        assert result.recommended_action in (
            AccountState.UNDER_SURVEILLANCE,
            AccountState.BANNED,
        )
    finally:
        if old:
            os.environ["GEMINI_API_KEY"] = old


@pytest.mark.asyncio
async def test_fallback_stores_result():
    """Fallback results should be stored in analysis_results."""
    old = os.environ.pop("GEMINI_API_KEY", None)
    try:
        engine = L2Engine()
        await engine.analyze(_make_request())
        assert len(await engine.get_analyses()) == 1
    finally:
        if old:
            os.environ["GEMINI_API_KEY"] = old


@pytest.mark.asyncio
async def test_fallback_legitimate_low_risk():
    """Fallback behavior for low-risk trades."""
    old = os.environ.pop("GEMINI_API_KEY", None)
    try:
        engine = L2Engine()
        req = AnalysisRequest(
            trigger_event=GameEventLog(
                event_id="evt_test",
                actor_id="a",
                target_id="b",
                action_details=ActionDetails(currency_amount=1000),
                context_metadata=ContextMetadata(recent_chat_log="よろしく"),
            ),
            triggered_rules=[],
            user_profile=UserProfile(
                user_id="b",
                current_state=AccountState.NORMAL,
                total_received_5min=1000,
                transaction_count_5min=1,
                unique_senders_5min=1,
            ),
        )
        result = await engine.analyze(req)
        assert result.risk_score == 0
        assert result.is_fraud is False
    finally:
        if old:
            os.environ["GEMINI_API_KEY"] = old


@pytest.mark.asyncio
async def test_reset_clears_analysis_results():
    old = os.environ.pop("GEMINI_API_KEY", None)
    try:
        engine = L2Engine()
        await engine.analyze(_make_request())
        assert len(engine.analysis_results) == 1

        await engine.reset()
        assert engine.analysis_results == []
    finally:
        if old:
            os.environ["GEMINI_API_KEY"] = old


@pytest.mark.asyncio
async def test_gemini_api_timeout():
    """Simulate a timeout when calling Gemini API."""
    import asyncio
    
    old = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "fake-key-for-test"
    try:
        engine = L2Engine()
        
        # Patch asyncio.to_thread to simulate a timeout
        async def mock_timeout(*args, **kwargs):
            raise asyncio.TimeoutError("Gemini API took too long")
            
        with pytest.MonkeyPatch.context() as m:
            m.setattr(asyncio, "to_thread", mock_timeout)
            result = await engine.analyze(_make_request())
            
        # Should drop to local fallback
        assert result.target_id == "b"
        assert result.is_fraud is True
        assert "Local fallback: API error" in result.reasoning
        assert "Gemini API took too long" in result.reasoning
        assert result.recommended_action == AccountState.BANNED
    finally:
        if old is not None:
            os.environ["GEMINI_API_KEY"] = old
        else:
            del os.environ["GEMINI_API_KEY"]


@pytest.mark.asyncio
async def test_gemini_api_503_service_unavailable():
    """Simulate a general 503 error from Gemini API."""
    import asyncio
    
    old = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "fake-key-for-test"
    try:
        engine = L2Engine()
        
        # Patch asyncio.to_thread to simulate an error
        async def mock_503(*args, **kwargs):
            raise Exception("503 Service Unavailable")
            
        with pytest.MonkeyPatch.context() as m:
            m.setattr(asyncio, "to_thread", mock_503)
            result = await engine.analyze(_make_request())
            
        # Should drop to local fallback
        assert result.target_id == "b"
        assert result.is_fraud is True
        assert "Local fallback: API error" in result.reasoning
        assert "503 Service Unavailable" in result.reasoning
        assert result.recommended_action == AccountState.BANNED

    finally:
        if old is not None:
            os.environ["GEMINI_API_KEY"] = old
        else:
            del os.environ["GEMINI_API_KEY"]

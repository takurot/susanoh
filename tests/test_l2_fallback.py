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

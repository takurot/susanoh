import pytest
from backend.models import ActionDetails, ContextMetadata, GameEventLog, AccountState
from backend.l1_screening import L1Engine


@pytest.fixture
def engine():
    return L1Engine()


def _make_event(
    actor="a",
    target="b",
    amount=100,
    market_avg=1000,
    chat=None,
    eid="evt_test",
):
    return GameEventLog(
        event_id=eid,
        actor_id=actor,
        target_id=target,
        action_details=ActionDetails(
            currency_amount=amount,
            market_avg_price=market_avg,
        ),
        context_metadata=ContextMetadata(
            recent_chat_log=chat,
        ),
    )


@pytest.mark.asyncio
async def test_r1_amount_threshold(engine):
    """R1: 累計取引額 >= 1,000,000 G"""
    event = _make_event(amount=1_100_000)
    result = await engine.screen(event)
    assert "R1" in result.triggered_rules
    assert result.screened is True


@pytest.mark.asyncio
async def test_r2_transaction_count(engine):
    """R2: 取引回数 >= 10回"""
    for i in range(10):
        result = await engine.screen(_make_event(amount=100, eid=f"evt_{i}"))
    assert "R2" in result.triggered_rules


@pytest.mark.asyncio
async def test_r3_market_avg_multiplier(engine):
    """R3: 単発取引額が市場平均の100倍以上"""
    event = _make_event(amount=100_000, market_avg=10)
    result = await engine.screen(event)
    assert "R3" in result.triggered_rules


@pytest.mark.asyncio
async def test_r4_slang_detection(engine):
    """R4: 隠語正規表現に一致"""
    event = _make_event(chat="Dで確認しました。振込お願いします")
    result = await engine.screen(event)
    assert "R4" in result.triggered_rules
    assert result.needs_l2 is True


@pytest.mark.asyncio
async def test_no_trigger_normal_trade(engine):
    event = _make_event(amount=500, market_avg=1000, chat="よろしく！")
    result = await engine.screen(event)
    assert result.screened is False
    assert result.triggered_rules == []


@pytest.mark.asyncio
async def test_recent_events(engine):
    await engine.screen(_make_event(eid="evt_safe", amount=500, market_avg=1000, chat="よろしく"))
    await engine.screen(_make_event(eid="evt_r4", chat="Dで確認しました。振込お願いします"))
    for i in range(3):
        await engine.screen(_make_event(eid=f"evt_{i}"))
    events = await engine.get_recent_events(limit=3)
    assert len(events) == 3
    assert isinstance(events[0], dict)
    assert "screened" in events[0]
    assert "triggered_rules" in events[0]


@pytest.mark.asyncio
async def test_build_analysis_request(engine):
    event = _make_event(amount=2_000_000, chat="振込完了")
    await engine.screen(event)
    req = await engine.build_analysis_request("b", event, ["R1", "R4"], AccountState.RESTRICTED_WITHDRAWAL)
    assert req.user_profile.user_id == "b"
    assert req.user_profile.total_received_5min >= 2_000_000


@pytest.mark.asyncio
async def test_reset_clears_windows_and_counters(engine):
    await engine.screen(_make_event(eid="evt_reset", amount=1_200_000))
    assert engine.l1_flag_count > 0
    assert len(engine.recent_events) == 1

    await engine.reset()

    assert engine.l1_flag_count == 0
    assert len(engine.recent_events) == 0
    assert len(engine.user_windows) == 0

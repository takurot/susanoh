import pytest
import asyncio
from unittest.mock import patch
from fakeredis.aioredis import FakeRedis
from backend.state_machine import StateMachine
from backend.l1_screening import L1Engine
from backend.models import AccountState, GameEventLog, ActionDetails, ContextMetadata

@pytest.fixture
def fake_redis():
    return FakeRedis(decode_responses=True)

@pytest.mark.asyncio
async def test_state_machine_with_redis(fake_redis):
    sm = StateMachine(fake_redis)
    user_id = "user_redis_01"
    
    # Initial state
    assert await sm.get_or_create(user_id) == AccountState.NORMAL
    
    # Transition
    await sm.transition(user_id, AccountState.RESTRICTED_WITHDRAWAL, "TEST", "RULE")
    assert await sm.get_or_create(user_id) == AccountState.RESTRICTED_WITHDRAWAL
    
    # Check Redis data
    val = await fake_redis.hget("susanoh:accounts", user_id)
    assert val == AccountState.RESTRICTED_WITHDRAWAL.value

@pytest.mark.asyncio
async def test_l1_engine_with_redis(fake_redis):
    engine = L1Engine(fake_redis)
    event = GameEventLog(
        event_id="evt_redis_01",
        actor_id="actor_1",
        target_id="target_1",
        action_details=ActionDetails(currency_amount=2_000_000),
        context_metadata=ContextMetadata()
    )
    
    result = await engine.screen(event)
    assert result.screened is True
    assert "R1" in result.triggered_rules
    
    # Verify it's in Redis
    raw_events = await fake_redis.zrange("susanoh:window:target_1", 0, -1)
    assert len(raw_events) == 1

from redis.exceptions import RedisError

@pytest.mark.asyncio
async def test_redis_fault_tolerance(fake_redis):
    # Simulate a failed Redis by patching a method to raise an error
    sm = StateMachine(fake_redis)
    engine = L1Engine(fake_redis)
    
    user_id = "user_fault_01"
    
    with patch.object(fake_redis, 'hget', side_effect=RedisError("Redis Down")):
        # Should not raise exception and fallback to in-memory
        state = await sm.get_or_create(user_id)
        assert state == AccountState.NORMAL
        
    event = GameEventLog(
        event_id="evt_fault_01",
        actor_id="actor_2",
        target_id="target_2",
        action_details=ActionDetails(currency_amount=100),
        context_metadata=ContextMetadata()
    )
    
    with patch.object(fake_redis, 'zadd', side_effect=RedisError("Redis Down")):
        # Should not raise 500 and process in-memory
        result = await engine.screen(event)
        assert result.screened is False
        
    # Verify in-memory state still works
    assert "target_2" in engine.user_windows

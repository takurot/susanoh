from pathlib import Path

from backend.l1_screening import L1Engine
from backend.l2_gemini import _local_fallback
from backend.models import (
    AccountState,
    ActionDetails,
    ContextMetadata,
    GameEventLog,
)
from backend.persistence import (
    AnalysisResultRecord,
    AuditLogRecord,
    EventLogRecord,
    PersistenceStore,
    UserRecord,
)
from backend.state_machine import StateMachine


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'susanoh-test.db'}"


def test_snapshot_persists_runtime_state(tmp_path):
    store = PersistenceStore(_sqlite_url(tmp_path))
    store.init_schema()

    sm = StateMachine()
    l1 = L1Engine()

    event = GameEventLog(
        event_id="evt_001",
        actor_id="user_a",
        target_id="user_b",
        action_details=ActionDetails(currency_amount=2_000_000, market_avg_price=100),
        context_metadata=ContextMetadata(actor_level=2, account_age_days=1, recent_chat_log="Dで確認"),
    )
    screening = l1.screen(event)
    sm.get_or_create(event.actor_id)
    sm.get_or_create(event.target_id)
    sm.transition(
        event.target_id,
        AccountState.RESTRICTED_WITHDRAWAL,
        "L1_SCREENING",
        ",".join(screening.triggered_rules),
        "L1 rule triggered",
    )

    analysis_req = l1.build_analysis_request(
        event.target_id,
        event,
        screening.triggered_rules,
        sm.get_or_create(event.target_id),
    )
    l2_results = [_local_fallback(analysis_req, "test-fallback")]

    store.persist_runtime_snapshot(sm=sm, l1=l1, l2_results=l2_results)

    with store.session() as session:
        assert session.query(UserRecord).count() == 2
        assert session.query(EventLogRecord).count() == 1
        assert session.query(AnalysisResultRecord).count() == 1
        assert session.query(AuditLogRecord).count() == 1

        user_b = session.query(UserRecord).filter_by(user_id="user_b").one()
        assert user_b.state == AccountState.RESTRICTED_WITHDRAWAL.value

        event_row = session.query(EventLogRecord).filter_by(event_id="evt_001").one()
        assert event_row.screened is True
        assert "R1" in event_row.triggered_rules


def test_clear_all_removes_rows(tmp_path):
    store = PersistenceStore(_sqlite_url(tmp_path))
    store.init_schema()

    sm = StateMachine()
    l1 = L1Engine()
    event = GameEventLog(
        event_id="evt_002",
        actor_id="user_c",
        target_id="user_d",
        action_details=ActionDetails(currency_amount=100),
        context_metadata=ContextMetadata(),
    )
    l1.screen(event)
    sm.get_or_create(event.actor_id)
    sm.get_or_create(event.target_id)

    store.persist_runtime_snapshot(sm=sm, l1=l1, l2_results=[])
    store.clear_all()

    with store.session() as session:
        assert session.query(UserRecord).count() == 0
        assert session.query(EventLogRecord).count() == 0
        assert session.query(AnalysisResultRecord).count() == 0
        assert session.query(AuditLogRecord).count() == 0


def test_snapshot_appends_to_logs_instead_of_clearing(tmp_path):
    store = PersistenceStore(_sqlite_url(tmp_path))
    store.init_schema()

    sm = StateMachine()
    l1 = L1Engine()

    # First event
    e1 = GameEventLog(
        event_id="evt_append_001",
        actor_id="user_1",
        target_id="user_2",
        action_details=ActionDetails(currency_amount=100),
    )
    l1.screen(e1)
    sm.get_or_create(e1.actor_id)
    sm.get_or_create(e1.target_id)
    store.persist_runtime_snapshot(sm=sm, l1=l1, l2_results=[])

    with store.session() as session:
        assert session.query(EventLogRecord).count() == 1

    # Second event (without clearing sm/l1, but we want to see it appends in DB)
    e2 = GameEventLog(
        event_id="evt_append_002",
        actor_id="user_1",
        target_id="user_3",
        action_details=ActionDetails(currency_amount=200),
    )
    l1.screen(e2)
    sm.get_or_create(e2.target_id)
    store.persist_runtime_snapshot(sm=sm, l1=l1, l2_results=[])

    with store.session() as session:
        # EventLogRecord should have 2 rows now
        assert session.query(EventLogRecord).count() == 2
        # UserRecord should have 3 users (user_1, user_2, user_3)
        assert session.query(UserRecord).count() == 3

    # If we reset runtime state but DON'T clear DB, snapshot should preserve DB rows
    sm.reset()
    l1.reset()
    
    e3 = GameEventLog(
        event_id="evt_append_003",
        actor_id="user_4",
        target_id="user_5",
        action_details=ActionDetails(currency_amount=300),
    )
    l1.screen(e3)
    sm.get_or_create(e3.actor_id)
    sm.get_or_create(e3.target_id)
    store.persist_runtime_snapshot(sm=sm, l1=l1, l2_results=[])

    with store.session() as session:
        # Total event logs should be 3 (evt_001, evt_002, evt_003)
        assert session.query(EventLogRecord).count() == 3
        # Total users in DB should be 3 + 2 = 5 (since reset cleared in-memory, but DB rows were kept)
        assert session.query(UserRecord).count() == 5


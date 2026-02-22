from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

if TYPE_CHECKING:
    from collections.abc import Iterator

    from backend.l1_screening import L1Engine
    from backend.models import ArbitrationResult
    from backend.state_machine import StateMachine


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


class EventLogRecord(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    currency_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    market_avg_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_level: Mapped[int] = mapped_column(Integer, nullable=False)
    account_age_days: Mapped[int] = mapped_column(Integer, nullable=False)
    recent_chat_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    screened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    triggered_rules: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class AnalysisResultRecord(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    is_fraud: Mapped[bool] = mapped_column(Boolean, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    fraud_type: Mapped[str] = mapped_column(String(64), nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(64), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_event_ids: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class AuditLogRecord(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    from_state: Mapped[str] = mapped_column(String(64), nullable=False)
    to_state: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger: Mapped[str] = mapped_column(String(128), nullable=False)
    triggered_by_rule: Mapped[str] = mapped_column(String(128), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PersistenceStore:
    def __init__(self, database_url: str | None) -> None:
        self.database_url = (database_url or "").strip()
        self.enabled = bool(self.database_url)
        self._engine = None
        self._session_factory: sessionmaker[Session] | None = None

        if self.enabled:
            self._engine = create_engine(self.database_url, future=True)
            self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False, future=True)

    @classmethod
    def from_env(cls) -> "PersistenceStore":
        return cls(os.environ.get("DATABASE_URL"))

    def init_schema(self) -> None:
        if not self.enabled or self._engine is None:
            return
        Base.metadata.create_all(self._engine)

    @contextmanager
    def session(self) -> "Iterator[Session]":
        if not self.enabled or self._session_factory is None:
            raise RuntimeError("Persistence store is disabled")
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def clear_all(self) -> None:
        if not self.enabled:
            return
        with self.session() as session:
            session.query(AuditLogRecord).delete()
            session.query(AnalysisResultRecord).delete()
            session.query(EventLogRecord).delete()
            session.query(UserRecord).delete()
            session.commit()

    def persist_runtime_snapshot(
        self,
        sm: "StateMachine",
        l1: "L1Engine" | None,
        l2_results: list["ArbitrationResult"],
    ) -> None:
        if not self.enabled:
            return

        now = datetime.now(UTC)

        with self.session() as session:
            # Upsert users
            for user_id, state in sm.accounts.items():
                record = session.get(UserRecord, user_id)
                if record:
                    record.state = state.value
                    record.updated_at = now
                else:
                    session.add(UserRecord(user_id=user_id, state=state.value, updated_at=now))

            # Append only new events
            if l1:
                existing_event_ids = {r[0] for r in session.query(EventLogRecord.event_id).all()}
                for event, screening in l1.recent_events:
                    if event.event_id in existing_event_ids:
                        continue
                    session.add(
                        EventLogRecord(
                            event_id=event.event_id,
                            timestamp=event.timestamp,
                            event_type=event.event_type,
                            actor_id=event.actor_id,
                            target_id=event.target_id,
                            currency_amount=event.action_details.currency_amount,
                            item_id=event.action_details.item_id,
                            market_avg_price=event.action_details.market_avg_price,
                            actor_level=event.context_metadata.actor_level,
                            account_age_days=event.context_metadata.account_age_days,
                            recent_chat_log=event.context_metadata.recent_chat_log,
                            screened=screening.screened,
                            triggered_rules=",".join(screening.triggered_rules),
                        )
                    )

            # Append only new analysis results (using created_at heuristic or better uniquely identify them)
            # For simplicity in this snapshot model, we'll append all if we can't easily dedup, 
            # but ideally analysis results should have an ID.
            # L2 analysis results in the list are the full history for the session.
            # We skip existing ones by comparing target_id and reasoning (rough but works for prototype).
            existing_analyses = {(r.target_id, r.reasoning) for r in session.query(AnalysisResultRecord).all()}
            for analysis in l2_results:
                if (analysis.target_id, analysis.reasoning) in existing_analyses:
                    continue
                session.add(
                    AnalysisResultRecord(
                        target_id=analysis.target_id,
                        is_fraud=analysis.is_fraud,
                        risk_score=analysis.risk_score,
                        fraud_type=analysis.fraud_type.value,
                        recommended_action=analysis.recommended_action.value,
                        reasoning=analysis.reasoning,
                        evidence_event_ids=",".join(analysis.evidence_event_ids),
                        confidence=analysis.confidence,
                        created_at=now,
                    )
                )

            # Append only new transitions
            existing_transitions = {
                (r.user_id, r.timestamp, r.to_state) for r in session.query(AuditLogRecord).all()
            }
            for log in sm.transition_logs:
                if (log.user_id, log.timestamp, log.to_state.value) in existing_transitions:
                    continue
                session.add(
                    AuditLogRecord(
                        user_id=log.user_id,
                        from_state=log.from_state.value,
                        to_state=log.to_state.value,
                        trigger=log.trigger,
                        triggered_by_rule=log.triggered_by_rule,
                        timestamp=log.timestamp,
                        evidence_summary=log.evidence_summary,
                    )
                )

            session.commit()



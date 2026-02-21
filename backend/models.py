from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AccountState(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED_WITHDRAWAL = "RESTRICTED_WITHDRAWAL"
    UNDER_SURVEILLANCE = "UNDER_SURVEILLANCE"
    BANNED = "BANNED"


class FraudType(str, Enum):
    RMT_SMURFING = "RMT_SMURFING"
    RMT_DIRECT = "RMT_DIRECT"
    MONEY_LAUNDERING = "MONEY_LAUNDERING"
    LEGITIMATE = "LEGITIMATE"


class ActionDetails(BaseModel):
    currency_amount: int = 0
    item_id: Optional[str] = None
    market_avg_price: Optional[int] = None


class ContextMetadata(BaseModel):
    actor_level: int = 1
    account_age_days: int = 0
    recent_chat_log: Optional[str] = None


class GameEventLog(BaseModel):
    event_id: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    event_type: str = "TRADE"
    actor_id: str
    target_id: str
    action_details: ActionDetails = Field(default_factory=ActionDetails)
    context_metadata: ContextMetadata = Field(default_factory=ContextMetadata)


class UserProfile(BaseModel):
    user_id: str
    current_state: AccountState = AccountState.NORMAL
    total_received_5min: int = 0
    transaction_count_5min: int = 0
    unique_senders_5min: int = 0


class AnalysisRequest(BaseModel):
    trigger_event: GameEventLog
    related_events: list[GameEventLog] = Field(default_factory=list)
    triggered_rules: list[str] = Field(default_factory=list)
    user_profile: UserProfile


class ArbitrationResult(BaseModel):
    target_id: str
    is_fraud: bool
    risk_score: int = Field(ge=0, le=100)
    fraud_type: FraudType
    recommended_action: AccountState
    reasoning: str
    evidence_event_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class TransitionLog(BaseModel):
    user_id: str
    from_state: AccountState
    to_state: AccountState
    trigger: str
    triggered_by_rule: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    evidence_summary: str = ""


class ScreeningResult(BaseModel):
    screened: bool = False
    triggered_rules: list[str] = Field(default_factory=list)
    recommended_action: Optional[AccountState] = None
    needs_l2: bool = False


class WithdrawRequest(BaseModel):
    user_id: str
    amount: int


class ShowcaseResult(BaseModel):
    target_user: str
    triggered_rules: list[str] = Field(default_factory=list)
    withdraw_status_code: int
    latest_state: AccountState
    latest_risk_score: Optional[int] = None
    latest_reasoning: Optional[str] = None


class GraphNode(BaseModel):
    id: str
    state: AccountState
    label: str


class GraphLink(BaseModel):
    source: str
    target: str
    amount: int = 0
    count: int = 0


class GraphData(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    links: list[GraphLink] = Field(default_factory=list)

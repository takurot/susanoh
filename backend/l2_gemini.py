from __future__ import annotations

import json
import os
import logging

from backend.models import (
    AccountState,
    AnalysisRequest,
    ArbitrationResult,
    FraudType,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an anti-fraud analysis AI for an online game economy.
Analyze the provided data and return an arbitration result in the following JSON format.

Analysis dimensions:
1. Transaction patterns: bursty high-volume activity, aggregation patterns, chain transfers
2. Chat logs: RMT slang (e.g., transfer/confirmation/3k)
3. Account profile: level, account age, transaction frequency

Decision criteria:
- risk_score 0-30: NORMAL (legitimate)
- risk_score 31-70: UNDER_SURVEILLANCE (needs monitoring)
- risk_score 71-100: BANNED (confirmed fraud)

fraud_type must be one of: RMT_SMURFING, RMT_DIRECT, MONEY_LAUNDERING, LEGITIMATE

Output must strictly follow this JSON schema:
{
  "target_id": "string",
  "is_fraud": boolean,
  "risk_score": integer (0-100),
  "fraud_type": "string",
  "recommended_action": "string (NORMAL|UNDER_SURVEILLANCE|BANNED)",
  "reasoning": "string (explain your decision in English)",
  "evidence_event_ids": ["string"],
  "confidence": float (0.0-1.0)
}"""


def _score_to_action(score: int) -> AccountState:
    if score <= 30:
        return AccountState.NORMAL
    if score <= 70:
        return AccountState.UNDER_SURVEILLANCE
    return AccountState.BANNED


def _local_fallback(request: AnalysisRequest, reason: str) -> ArbitrationResult:
    """Gemini unavailable — rule-based local arbitration."""
    rules = request.triggered_rules
    profile = request.user_profile

    score = 0
    if "R1" in rules:
        score += 30
    if "R2" in rules:
        score += 20
    if "R3" in rules:
        score += 25
    if "R4" in rules:
        score += 30
    if profile.unique_senders_5min >= 5:
        score += 15

    score = min(score, 100)
    action = _score_to_action(score)

    fraud_type = FraudType.LEGITIMATE
    if score > 30:
        if profile.unique_senders_5min >= 3:
            fraud_type = FraudType.RMT_SMURFING
        elif "R4" in rules:
            fraud_type = FraudType.RMT_DIRECT
        else:
            fraud_type = FraudType.MONEY_LAUNDERING

    return ArbitrationResult(
        target_id=request.user_profile.user_id,
        is_fraud=score > 30,
        risk_score=score,
        fraud_type=fraud_type,
        recommended_action=action,
        reasoning=(
            f"[Local fallback: {reason}] Rules {rules} were triggered. "
            f"5-minute total={profile.total_received_5min}G, "
            f"transactions={profile.transaction_count_5min}, "
            f"unique_senders={profile.unique_senders_5min}."
        ),
        evidence_event_ids=[request.trigger_event.event_id],
        confidence=0.6,
    )


from typing import TYPE_CHECKING, Optional
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from redis.asyncio import Redis

class L2Engine:
    REDIS_KEY = "susanoh:analyses"

    def __init__(self, redis_client: Optional[Redis] = None) -> None:
        self.redis = redis_client
        self.analysis_results: list[ArbitrationResult] = []

    async def reset(self) -> None:
        self.analysis_results.clear()
        if self.redis:
            try:
                await self.redis.delete(self.REDIS_KEY)
            except Exception as e:
                logger.warning("Redis L2 reset failed: %s", e)

    async def _store_result(self, result: ArbitrationResult) -> None:
        """Store result in both in-memory list and Redis (if available)."""
        self.analysis_results.append(result)
        if self.redis:
            try:
                await self.redis.lpush(self.REDIS_KEY, result.model_dump_json())
                await self.redis.ltrim(self.REDIS_KEY, 0, 199)
            except Exception as e:
                logger.warning("Redis L2 store failed: %s", e)

    async def analyze(self, request: AnalysisRequest) -> ArbitrationResult:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            result = _local_fallback(request, "GEMINI_API_KEY is not set")
            await self._store_result(result)
            return result

        try:
            result = await self._call_gemini(request, api_key)
            await self._store_result(result)
            return result
        except Exception as e:
            logger.warning("Gemini API error: %s — falling back", e)
            result = _local_fallback(request, f"API error: {e}")
            await self._store_result(result)
            return result

    async def _call_gemini(self, request: AnalysisRequest, api_key: str) -> ArbitrationResult:
        import asyncio
        from google import genai

        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        client = genai.Client(api_key=api_key)

        prompt = self._build_prompt(request)

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ArbitrationResult,
                temperature=0.1,
            ),
        )

        text = response.text
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return _local_fallback(request, "JSON parse failed")

        action_str = data.get("recommended_action", "UNDER_SURVEILLANCE")
        try:
            action = AccountState(action_str)
        except ValueError:
            action = AccountState.UNDER_SURVEILLANCE

        fraud_type_str = data.get("fraud_type", "LEGITIMATE")
        try:
            fraud_type = FraudType(fraud_type_str)
        except ValueError:
            fraud_type = FraudType.LEGITIMATE

        return ArbitrationResult(
            target_id=data.get("target_id", request.user_profile.user_id),
            is_fraud=data.get("is_fraud", True),
            risk_score=max(0, min(100, data.get("risk_score", 50))),
            fraud_type=fraud_type,
            recommended_action=action,
            reasoning=data.get("reasoning", "Analysis completed"),
            evidence_event_ids=data.get("evidence_event_ids", [request.trigger_event.event_id]),
            confidence=max(0.0, min(1.0, data.get("confidence", 0.8))),
        )

    @staticmethod
    def _build_prompt(request: AnalysisRequest) -> str:
        profile = request.user_profile
        trigger = request.trigger_event

        lines = [
            "## Analysis Target",
            f"- User ID: {profile.user_id}",
            f"- Current state: {profile.current_state.value}",
            f"- 5-minute total received: {profile.total_received_5min}G",
            f"- 5-minute transaction count: {profile.transaction_count_5min}",
            f"- 5-minute unique senders: {profile.unique_senders_5min}",
            "",
            "## Trigger Event",
            f"- Event ID: {trigger.event_id}",
            f"- Sender: {trigger.actor_id} -> Receiver: {trigger.target_id}",
            f"- Amount: {trigger.action_details.currency_amount}G",
            f"- Chat: {trigger.context_metadata.recent_chat_log or '(none)'}",
            "",
            f"## Triggered Rules: {', '.join(request.triggered_rules) or 'none'}",
            "",
            "## Related Events",
        ]
        for evt in request.related_events[-10:]:
            lines.append(
                f"- {evt.event_id}: {evt.actor_id}→{evt.target_id} "
                f"{evt.action_details.currency_amount}G "
                f"chat=\"{evt.context_metadata.recent_chat_log or ''}\""
            )

        return "\n".join(lines)

    async def get_analyses(self, limit: int = 20) -> list[ArbitrationResult]:
        if self.redis:
            try:
                raw_analyses = await self.redis.lrange(self.REDIS_KEY, 0, limit - 1)
                results = []
                for item in raw_analyses:
                    try:
                        results.append(ArbitrationResult.model_validate_json(item))
                    except Exception:
                        continue
                return results
            except Exception as e:
                logger.warning("Redis L2 get_analyses failed: %s. Using in-memory.", e)
        return list(reversed(self.analysis_results[-limit:]))

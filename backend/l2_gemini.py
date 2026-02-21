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

SYSTEM_PROMPT = """あなたはオンラインゲーム経済圏の不正取引分析AIです。
提供されるデータを分析し、以下のJSON形式で裁定結果を返してください。

分析観点:
1. 取引パターン: 短時間の大量取引、集約パターン、チェーン送金
2. チャットログ: RMT隠語（「振込」「D確認」「3k」等）
3. アカウントプロファイル: レベル、アカウント年齢、取引頻度

判定基準:
- risk_score 0-30: NORMAL（正常取引）
- risk_score 31-70: UNDER_SURVEILLANCE（要監視）
- risk_score 71-100: BANNED（不正確定）

fraud_type: RMT_SMURFING, RMT_DIRECT, MONEY_LAUNDERING, LEGITIMATE のいずれか

出力は必ず以下のJSONスキーマに従ってください:
{
  "target_id": "string",
  "is_fraud": boolean,
  "risk_score": integer (0-100),
  "fraud_type": "string",
  "recommended_action": "string (NORMAL|UNDER_SURVEILLANCE|BANNED)",
  "reasoning": "string (日本語で判定根拠を説明)",
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
        reasoning=f"[ローカルフォールバック: {reason}] ルール{rules}が発火。累計額{profile.total_received_5min}G、取引{profile.transaction_count_5min}回、送信者{profile.unique_senders_5min}人。",
        evidence_event_ids=[request.trigger_event.event_id],
        confidence=0.6,
    )


class L2Engine:
    def __init__(self) -> None:
        self.analysis_results: list[ArbitrationResult] = []

    def reset(self) -> None:
        self.analysis_results.clear()

    async def analyze(self, request: AnalysisRequest) -> ArbitrationResult:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            result = _local_fallback(request, "GEMINI_API_KEY未設定")
            self.analysis_results.append(result)
            return result

        try:
            result = await self._call_gemini(request, api_key)
            self.analysis_results.append(result)
            return result
        except Exception as e:
            logger.warning("Gemini API error: %s — falling back", e)
            result = _local_fallback(request, f"API障害: {e}")
            self.analysis_results.append(result)
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
            return _local_fallback(request, "JSONパース失敗")

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
            reasoning=data.get("reasoning", "分析完了"),
            evidence_event_ids=data.get("evidence_event_ids", [request.trigger_event.event_id]),
            confidence=max(0.0, min(1.0, data.get("confidence", 0.8))),
        )

    @staticmethod
    def _build_prompt(request: AnalysisRequest) -> str:
        profile = request.user_profile
        trigger = request.trigger_event

        lines = [
            "## 分析対象",
            f"- ユーザーID: {profile.user_id}",
            f"- 現在の状態: {profile.current_state.value}",
            f"- 5分間累計受取額: {profile.total_received_5min}G",
            f"- 5分間取引回数: {profile.transaction_count_5min}",
            f"- 5分間ユニーク送信者数: {profile.unique_senders_5min}",
            "",
            "## トリガーイベント",
            f"- イベントID: {trigger.event_id}",
            f"- 送信者: {trigger.actor_id} → 受信者: {trigger.target_id}",
            f"- 金額: {trigger.action_details.currency_amount}G",
            f"- チャット: {trigger.context_metadata.recent_chat_log or '(なし)'}",
            "",
            f"## 発火ルール: {', '.join(request.triggered_rules) or 'なし'}",
            "",
            "## 関連イベント一覧",
        ]
        for evt in request.related_events[-10:]:
            lines.append(
                f"- {evt.event_id}: {evt.actor_id}→{evt.target_id} "
                f"{evt.action_details.currency_amount}G "
                f"chat=\"{evt.context_metadata.recent_chat_log or ''}\""
            )

        return "\n".join(lines)

    def get_analyses(self, limit: int = 20) -> list[ArbitrationResult]:
        return list(reversed(self.analysis_results[-limit:]))

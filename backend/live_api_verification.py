from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

import httpx


@dataclass(frozen=True)
class LiveAPIVerificationConfig:
    base_url: str
    username: str
    password: str
    api_key: str | None
    timeout_seconds: float


def load_live_api_verification_config(
    env: Mapping[str, str] | None = None,
) -> LiveAPIVerificationConfig:
    src = env or os.environ
    base_url = src.get("SUSANOH_STAGING_BASE_URL", "").strip()
    if not base_url:
        raise ValueError("SUSANOH_STAGING_BASE_URL is required")

    password = src.get("SUSANOH_STAGING_PASSWORD", "").strip()
    if not password:
        raise ValueError("SUSANOH_STAGING_PASSWORD is required")

    username = src.get("SUSANOH_STAGING_USERNAME", "admin").strip() or "admin"
    api_key_raw = src.get("SUSANOH_STAGING_API_KEY", "").strip()
    api_key = api_key_raw or None

    timeout_raw = src.get("SUSANOH_STAGING_TIMEOUT_SECONDS", "10").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise ValueError("SUSANOH_STAGING_TIMEOUT_SECONDS must be numeric") from exc
    if timeout_seconds <= 0:
        raise ValueError("SUSANOH_STAGING_TIMEOUT_SECONDS must be greater than 0")

    return LiveAPIVerificationConfig(
        base_url=base_url.rstrip("/"),
        username=username,
        password=password,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


def _build_probe_event() -> dict[str, Any]:
    now = datetime.now(UTC)
    suffix = int(now.timestamp())
    return {
        "event_id": f"evt_live_probe_{suffix}",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "actor_id": "live_probe_sender",
        "target_id": "live_check_target",
        "action_details": {
            "currency_amount": 14000,
        },
        "context_metadata": {
            "recent_chat_log": "transfer and confirmation for 14k as discussed",
        },
    }


def _validate_verdict_payload(payload: Mapping[str, Any]) -> None:
    required = (
        "target_id",
        "is_fraud",
        "risk_score",
        "fraud_type",
        "recommended_action",
        "reasoning",
        "evidence_event_ids",
        "confidence",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise RuntimeError(f"Invalid verification response: missing fields {', '.join(missing)}")

    score = payload["risk_score"]
    if not isinstance(score, int) or not (0 <= score <= 100):
        raise RuntimeError("Invalid verification response: risk_score must be integer 0-100")

    action = payload["recommended_action"]
    if action not in {"NORMAL", "UNDER_SURVEILLANCE", "BANNED"}:
        raise RuntimeError("Invalid verification response: recommended_action is invalid")

    reasoning = payload["reasoning"]
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise RuntimeError("Invalid verification response: reasoning must be non-empty string")

    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
        raise RuntimeError("Invalid verification response: confidence must be between 0.0 and 1.0")


async def run_live_api_verification(config: LiveAPIVerificationConfig) -> dict[str, Any]:
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=config.base_url, timeout=config.timeout_seconds) as client:
        token_response = await client.post(
            "/api/v1/auth/token",
            data={
                "username": config.username,
                "password": config.password,
            },
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise RuntimeError("Authentication succeeded but access_token is missing")

        headers = {"Authorization": f"Bearer {access_token}"}
        if config.api_key:
            headers["X-API-KEY"] = config.api_key

        verification_event = _build_probe_event()
        analyze_response = await client.post(
            "/api/v1/analyze",
            json=verification_event,
            headers=headers,
        )
        analyze_response.raise_for_status()
        payload = analyze_response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Invalid verification response: expected JSON object")
        _validate_verdict_payload(payload)

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    return {
        "ok": True,
        "latency_ms": elapsed_ms,
        "target_id": payload["target_id"],
        "risk_score": payload["risk_score"],
        "recommended_action": payload["recommended_action"],
    }


def main() -> int:
    try:
        config = load_live_api_verification_config()
        result = asyncio.run(run_live_api_verification(config))
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

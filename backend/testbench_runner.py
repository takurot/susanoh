from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from backend.models import AccountState, GameEventLog
from backend.testbench_policy import (
    FailureDisposition,
    FailureType,
    TestbenchMode,
    classify_failure,
    load_operational_testbench_policy,
    should_block_ci,
    should_notify_ops,
)


DEFAULT_FIXTURES_DIR = Path("tests/fixtures/testbench")
DEFAULT_OUTPUT_ROOT = Path("artifacts/testbench")


class RunnerProfile(str, Enum):
    LOCAL = "local"
    STAGING = "staging"


class RunnerExitCode(IntEnum):
    ALL_PASS = 0
    QUALITY_GATE_FAIL = 1
    INFRA_DEPENDENCY_FAIL = 2
    INVALID_FIXTURE = 3


@dataclass(frozen=True)
class RunnerConfig:
    profile: RunnerProfile
    mode: TestbenchMode
    base_url: str
    username: str
    password: str
    api_key: str | None
    timeout_seconds: float
    retry_attempts: int
    fixtures_dir: Path
    output_root: Path
    run_id: str
    selected_scenarios: tuple[str, ...]


@dataclass(frozen=True)
class TestbenchRunResult:
    summary: dict[str, Any]
    failures: list[dict[str, Any]]
    artifacts_dir: Path
    exit_code: RunnerExitCode


class ScenarioExpectation(BaseModel):
    target_id: str
    l1_primary_rules: list[str] = Field(default_factory=list)
    l2_fallback_action: AccountState = AccountState.NORMAL
    expected_state_path: list[AccountState] | None = None
    expected_l2_action_range: list[AccountState] | None = None
    notes: str = ""

    def derived_state_path(self) -> list[AccountState]:
        if self.expected_state_path is not None:
            return self.expected_state_path

        path = [AccountState.NORMAL]
        if self.l1_primary_rules:
            path.append(AccountState.RESTRICTED_WITHDRAWAL)

        if self.l2_fallback_action is AccountState.BANNED:
            path.extend([AccountState.UNDER_SURVEILLANCE, AccountState.BANNED])
        elif self.l2_fallback_action is AccountState.UNDER_SURVEILLANCE:
            path.append(AccountState.UNDER_SURVEILLANCE)
        elif self.l1_primary_rules and self.l2_fallback_action is AccountState.NORMAL:
            path.append(AccountState.NORMAL)

        return path

    def allowed_l2_actions(self) -> list[AccountState]:
        if self.expected_l2_action_range:
            return self.expected_l2_action_range
        return [self.l2_fallback_action]


class ScenarioFixture(BaseModel):
    scenario_id: str
    title: str
    pattern_family: str
    risk_tier: str
    expected: ScenarioExpectation
    events: list[GameEventLog] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_target_is_present(self) -> "ScenarioFixture":
        if not self.events:
            raise ValueError(f"scenario {self.scenario_id} has no events")

        targets = {event.target_id for event in self.events}
        if self.expected.target_id not in targets:
            raise ValueError(
                f"scenario {self.scenario_id} expected target_id {self.expected.target_id} is not present in events"
            )
        return self


class TestbenchDataset(BaseModel):
    dataset: str
    version: str
    generated_at: str
    seed: int
    scenario_count: int
    event_count: int
    scenarios: list[ScenarioFixture] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_dataset(self) -> "TestbenchDataset":
        if self.scenario_count != len(self.scenarios):
            raise ValueError(
                f"scenario_count mismatch: expected {self.scenario_count}, got {len(self.scenarios)}"
            )

        seen: set[str] = set()
        total_events = 0
        for scenario in self.scenarios:
            if scenario.scenario_id in seen:
                raise ValueError(f"duplicate scenario_id: {scenario.scenario_id}")
            seen.add(scenario.scenario_id)
            total_events += len(scenario.events)

        if self.event_count != total_events:
            raise ValueError(f"event_count mismatch: expected {self.event_count}, got {total_events}")
        return self


class FlattenedScenarioEvent(BaseModel):
    scenario_id: str
    scenario_risk_tier: str
    sequence: int
    event: GameEventLog


def load_runner_config(
    *,
    profile: RunnerProfile,
    mode: TestbenchMode,
    env: Mapping[str, str] | None = None,
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    selected_scenarios: Sequence[str] | None = None,
) -> RunnerConfig:
    src = os.environ if env is None else env
    policy = load_operational_testbench_policy()
    timeout_seconds = _load_timeout_seconds(src)

    if profile is RunnerProfile.LOCAL:
        api_key = _first_non_empty(
            src.get("SUSANOH_TESTBENCH_LOCAL_API_KEY"),
            _first_configured_api_key(src.get("SUSANOH_API_KEYS", "")),
        )
        username = src.get("SUSANOH_TESTBENCH_LOCAL_USERNAME", "admin").strip() or "admin"
        password = src.get("SUSANOH_TESTBENCH_LOCAL_PASSWORD", "password123").strip() or "password123"
        base_url = "http://test"
    else:
        base_url = src.get("SUSANOH_TESTBENCH_STAGING_BASE_URL", "").strip()
        if not base_url:
            raise ValueError("SUSANOH_TESTBENCH_STAGING_BASE_URL is required for staging profile")

        password = src.get("SUSANOH_TESTBENCH_STAGING_PASSWORD", "").strip()
        if not password:
            raise ValueError("SUSANOH_TESTBENCH_STAGING_PASSWORD is required for staging profile")

        username = src.get("SUSANOH_TESTBENCH_STAGING_USERNAME", "admin").strip() or "admin"
        api_key = _first_non_empty(src.get("SUSANOH_TESTBENCH_STAGING_API_KEY"))

    run_id_value = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    selected = tuple(selected_scenarios or ())

    return RunnerConfig(
        profile=profile,
        mode=mode,
        base_url=base_url.rstrip("/"),
        username=username,
        password=password,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        retry_attempts=policy.failure.max_retry_attempts,
        fixtures_dir=fixtures_dir,
        output_root=output_root,
        run_id=run_id_value,
        selected_scenarios=selected,
    )


def apply_run_namespace(scenario: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    suffix = f"__{run_id}"
    payload = json.loads(json.dumps(scenario))
    payload["expected"]["target_id"] = f"{payload['expected']['target_id']}{suffix}"

    for event in payload["events"]:
        event["event_id"] = f"{event['event_id']}{suffix}"
        event["actor_id"] = f"{event['actor_id']}{suffix}"
        event["target_id"] = f"{event['target_id']}{suffix}"

    return payload


def load_testbench_fixture(fixtures_dir: Path) -> TestbenchDataset:
    scenarios_path = fixtures_dir / "scenarios.json"
    events_path = fixtures_dir / "events.jsonl"

    try:
        dataset = TestbenchDataset.model_validate_json(scenarios_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing fixture file: {exc.filename}") from exc
    except ValidationError as exc:
        raise ValueError(f"invalid scenarios.json: {exc}") from exc

    flattened: list[FlattenedScenarioEvent] = []
    try:
        with events_path.open("r", encoding="utf-8") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    flattened.append(FlattenedScenarioEvent.model_validate_json(line))
                except ValidationError as exc:
                    raise ValueError(f"invalid events.jsonl line {line_no}: {exc}") from exc
    except FileNotFoundError as exc:
        raise ValueError(f"missing fixture file: {exc.filename}") from exc

    if len(flattened) != dataset.event_count:
        raise ValueError(
            f"flattened event_count mismatch: expected {dataset.event_count}, got {len(flattened)}"
        )

    events_by_scenario: dict[str, list[FlattenedScenarioEvent]] = {}
    for entry in flattened:
        events_by_scenario.setdefault(entry.scenario_id, []).append(entry)

    for scenario in dataset.scenarios:
        rows = events_by_scenario.get(scenario.scenario_id)
        if rows is None:
            raise ValueError(f"scenario {scenario.scenario_id} is missing from events.jsonl")
        if len(rows) != len(scenario.events):
            raise ValueError(
                f"scenario {scenario.scenario_id} flattened event count mismatch: "
                f"expected {len(scenario.events)}, got {len(rows)}"
            )

        rows = sorted(rows, key=lambda item: item.sequence)
        expected_ids = [event.event_id for event in scenario.events]
        actual_ids = [item.event.event_id for item in rows]
        if expected_ids != actual_ids:
            raise ValueError(
                f"scenario {scenario.scenario_id} events.jsonl order does not match scenarios.json"
            )

        if any(item.scenario_risk_tier != scenario.risk_tier for item in rows):
            raise ValueError(f"scenario {scenario.scenario_id} risk tier mismatch in events.jsonl")

    return dataset


async def run_testbench(config: RunnerConfig) -> TestbenchRunResult:
    artifacts_dir = config.output_root / config.run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    policy = load_operational_testbench_policy()

    try:
        dataset = load_testbench_fixture(config.fixtures_dir)
        scenarios = _select_scenarios(dataset, config.selected_scenarios)
    except ValueError as exc:
        failure = _build_failure(
            failure_type=FailureType.INVALID_FIXTURE,
            disposition=FailureDisposition.IMMEDIATE_FAIL,
            mode=config.mode,
            scenario_id=None,
            message=str(exc),
            failed_gates=[],
        )
        summary = _build_terminal_summary(
            config=config,
            dataset_name="unknown",
            dataset_version="unknown",
            scenario_results=[],
            failures=[failure],
            latencies_ms=[],
            exit_code=RunnerExitCode.INVALID_FIXTURE,
        )
        _write_artifacts(artifacts_dir, summary, [failure])
        return TestbenchRunResult(
            summary=summary,
            failures=[failure],
            artifacts_dir=artifacts_dir,
            exit_code=RunnerExitCode.INVALID_FIXTURE,
        )

    latencies_ms: list[float] = []
    failures: list[dict[str, Any]] = []
    scenario_results: list[dict[str, Any]] = []

    if config.profile is RunnerProfile.LOCAL:
        from backend.main import reset_runtime_state

        await reset_runtime_state()

    async with _build_http_client(config) as client:
        auth_payload, auth_latency_ms, auth_failure = await _request_json(
            client=client,
            method="POST",
            path="/api/v1/auth/token",
            retry_attempts=config.retry_attempts,
            timeout_seconds=config.timeout_seconds,
            data={"username": config.username, "password": config.password},
        )
        if auth_failure:
            failures.append(
                _build_failure(
                    failure_type=FailureType.INFRA_DEPENDENCY,
                    disposition=FailureDisposition.FAIL_AFTER_RETRY,
                    mode=config.mode,
                    scenario_id=None,
                    message=f"authentication failed: {auth_failure}",
                    failed_gates=["api_availability"],
                )
            )
        else:
            access_token = auth_payload.get("access_token") if isinstance(auth_payload, dict) else None
            if not isinstance(access_token, str) or not access_token:
                failures.append(
                    _build_failure(
                        failure_type=FailureType.INFRA_DEPENDENCY,
                        disposition=FailureDisposition.FAIL_AFTER_RETRY,
                        mode=config.mode,
                        scenario_id=None,
                        message="authentication succeeded but access_token is missing",
                        failed_gates=["api_availability"],
                    )
                )
            else:
                auth_headers = {
                    "Authorization": f"Bearer {access_token}",
                    **_api_key_headers(config.api_key),
                }
                event_headers = _api_key_headers(config.api_key)

                for scenario in scenarios:
                    result = await _run_scenario(
                        client=client,
                        config=config,
                        scenario=scenario,
                        auth_headers=auth_headers,
                        event_headers=event_headers,
                    )
                    scenario_results.append(result["scenario"])
                    failures.extend(result["failures"])
                    latencies_ms.extend(result["latencies_ms"])

    exit_code = _determine_exit_code(failures)
    summary = _build_terminal_summary(
        config=config,
        dataset_name=dataset.dataset,
        dataset_version=dataset.version,
        scenario_results=scenario_results,
        failures=failures,
        latencies_ms=latencies_ms,
        exit_code=exit_code,
    )
    _write_artifacts(artifacts_dir, summary, failures)

    return TestbenchRunResult(
        summary=summary,
        failures=failures,
        artifacts_dir=artifacts_dir,
        exit_code=exit_code,
    )


async def _run_scenario(
    *,
    client: httpx.AsyncClient,
    config: RunnerConfig,
    scenario: ScenarioFixture,
    auth_headers: Mapping[str, str],
    event_headers: Mapping[str, str],
) -> dict[str, Any]:
    namespaced = ScenarioFixture.model_validate(apply_run_namespace(scenario.model_dump(mode="json"), config.run_id))
    latencies_ms: list[float] = []
    failures: list[dict[str, Any]] = []
    event_pairs: list[tuple[GameEventLog, dict[str, Any]]] = []
    api_available = True

    with _local_background_l2_suppressed(config.profile):
        for event in namespaced.events:
            payload, latency_ms, error = await _request_json(
                client=client,
                method="POST",
                path="/api/v1/events",
                retry_attempts=config.retry_attempts,
                timeout_seconds=config.timeout_seconds,
                headers=event_headers,
                json_body=event.model_dump(mode="json"),
            )
            if latency_ms > 0:
                latencies_ms.append(latency_ms)
            if error is not None:
                api_available = False
                failures.append(
                    _build_failure(
                        failure_type=FailureType.INFRA_DEPENDENCY,
                        disposition=FailureDisposition.FAIL_AFTER_RETRY,
                        mode=config.mode,
                        scenario_id=scenario.scenario_id,
                        message=error,
                        failed_gates=["api_availability"],
                    )
                )
                break
            event_pairs.append((event, payload))

    latest_analysis: dict[str, Any] | None = None
    if api_available and namespaced.expected.l1_primary_rules:
        if config.profile is RunnerProfile.LOCAL:
            analysis_payload, analysis_latency_ms, analysis_error = await _run_local_l2(
                scenario=namespaced,
                event_pairs=event_pairs,
            )
        else:
            analysis_payload, analysis_latency_ms, analysis_error = await _request_json(
                client=client,
                method="POST",
                path="/api/v1/analyze",
                retry_attempts=config.retry_attempts,
                timeout_seconds=config.timeout_seconds,
                headers=auth_headers,
                json_body=_latest_target_event(event_pairs, namespaced.expected.target_id).model_dump(mode="json"),
            )
        if analysis_latency_ms > 0 and config.profile is not RunnerProfile.LOCAL:
            latencies_ms.append(analysis_latency_ms)
        if analysis_error is not None:
            api_available = False
            failures.append(
                _build_failure(
                    failure_type=FailureType.INFRA_DEPENDENCY,
                    disposition=FailureDisposition.FAIL_AFTER_RETRY,
                    mode=config.mode,
                    scenario_id=scenario.scenario_id,
                    message=analysis_error,
                    failed_gates=["api_availability"],
                )
            )
        else:
            latest_analysis = analysis_payload

    user_payload: dict[str, Any] | None = None
    transitions_payload: list[dict[str, Any]] = []
    analyses_payload: list[dict[str, Any]] = []
    if api_available:
        user_payload, latency_ms, error = await _request_json(
            client=client,
            method="GET",
            path=f"/api/v1/users/{namespaced.expected.target_id}",
            retry_attempts=config.retry_attempts,
            timeout_seconds=config.timeout_seconds,
            headers=auth_headers,
        )
        if latency_ms > 0:
            latencies_ms.append(latency_ms)
        if error is not None:
            api_available = False
            failures.append(
                _build_failure(
                    failure_type=FailureType.INFRA_DEPENDENCY,
                    disposition=FailureDisposition.FAIL_AFTER_RETRY,
                    mode=config.mode,
                    scenario_id=scenario.scenario_id,
                    message=error,
                    failed_gates=["api_availability"],
                )
            )
            user_payload = None

    if api_available:
        transitions_payload, latency_ms, error = await _request_json(
            client=client,
            method="GET",
            path="/api/v1/transitions?limit=200",
            retry_attempts=config.retry_attempts,
            timeout_seconds=config.timeout_seconds,
            headers=auth_headers,
        )
        if latency_ms > 0:
            latencies_ms.append(latency_ms)
        if error is not None:
            api_available = False
            failures.append(
                _build_failure(
                    failure_type=FailureType.INFRA_DEPENDENCY,
                    disposition=FailureDisposition.FAIL_AFTER_RETRY,
                    mode=config.mode,
                    scenario_id=scenario.scenario_id,
                    message=error,
                    failed_gates=["api_availability"],
                )
            )
            transitions_payload = []

    if api_available:
        analyses_payload, latency_ms, error = await _request_json(
            client=client,
            method="GET",
            path="/api/v1/analyses?limit=100",
            retry_attempts=config.retry_attempts,
            timeout_seconds=config.timeout_seconds,
            headers=auth_headers,
        )
        if latency_ms > 0:
            latencies_ms.append(latency_ms)
        if error is not None:
            api_available = False
            failures.append(
                _build_failure(
                    failure_type=FailureType.INFRA_DEPENDENCY,
                    disposition=FailureDisposition.FAIL_AFTER_RETRY,
                    mode=config.mode,
                    scenario_id=scenario.scenario_id,
                    message=error,
                    failed_gates=["api_availability"],
                )
            )
            analyses_payload = []

    if latest_analysis is None and analyses_payload:
        latest_analysis = next(
            (analysis for analysis in analyses_payload if analysis.get("target_id") == namespaced.expected.target_id),
            None,
        )

    target_pairs = [pair for pair in event_pairs if pair[0].target_id == namespaced.expected.target_id]
    observed_l1_rules = sorted(
        {
            rule
            for _, payload in target_pairs
            for rule in payload.get("triggered_rules", [])
        }
    )
    expected_l1_rules = sorted(namespaced.expected.l1_primary_rules)
    observed_state_path = [
        transition["to_state"]
        for transition in reversed(transitions_payload or [])
        if transition.get("user_id") == namespaced.expected.target_id
    ]
    expected_state_path = [
        state.value for state in namespaced.expected.derived_state_path()[1:]
    ]

    if latest_analysis is None and not expected_l1_rules:
        observed_l2_action = AccountState.NORMAL.value
    else:
        observed_l2_action = latest_analysis.get("recommended_action") if latest_analysis else None

    expected_l2_actions = [state.value for state in namespaced.expected.allowed_l2_actions()]
    final_state = user_payload.get("state") if isinstance(user_payload, dict) else AccountState.NORMAL.value

    gates = {
        "l1_rule_match": observed_l1_rules == expected_l1_rules,
        "state_path_match": observed_state_path == expected_state_path,
        "l2_action_range_match": observed_l2_action in expected_l2_actions,
        "api_availability": api_available,
    }
    failed_gates = [name for name, ok in gates.items() if not ok]

    expected_final_state = expected_state_path[-1] if expected_state_path else AccountState.NORMAL.value
    if not failed_gates and final_state != expected_final_state:
        failed_gates.append("state_path_match")
        gates["state_path_match"] = False

    if failed_gates and not any(failure["failure_type"] == FailureType.INFRA_DEPENDENCY.value for failure in failures):
        failures.append(
            _build_failure(
                failure_type=FailureType.QUALITY_GATE,
                disposition=FailureDisposition.IMMEDIATE_FAIL,
                mode=config.mode,
                scenario_id=scenario.scenario_id,
                message=f"quality gates failed: {', '.join(failed_gates)}",
                failed_gates=failed_gates,
            )
        )

    scenario_summary = {
        "scenario_id": scenario.scenario_id,
        "title": scenario.title,
        "risk_tier": scenario.risk_tier,
        "target_id": namespaced.expected.target_id,
        "passed": not failed_gates,
        "failed_gates": failed_gates,
        "expected_l1_rules": expected_l1_rules,
        "observed_l1_rules": observed_l1_rules,
        "expected_state_path": expected_state_path,
        "observed_state_path": observed_state_path,
        "expected_l2_actions": expected_l2_actions,
        "observed_l2_action": observed_l2_action,
        "final_state": final_state,
        "request_count": len(latencies_ms),
        "latency_ms": _latency_summary(latencies_ms),
        "quality_gates": gates,
    }
    return {
        "scenario": scenario_summary,
        "failures": failures,
        "latencies_ms": latencies_ms,
    }


async def _run_local_l2(
    *,
    scenario: ScenarioFixture,
    event_pairs: list[tuple[GameEventLog, dict[str, Any]]],
) -> tuple[dict[str, Any] | None, float, str | None]:
    import backend.main as main_module

    trigger_event = _latest_target_event(event_pairs, scenario.expected.target_id)
    triggered_rules = []
    for event, payload in reversed(event_pairs):
        if event.target_id == scenario.expected.target_id and payload.get("triggered_rules"):
            triggered_rules = list(payload.get("triggered_rules", []))
            trigger_event = event
            break

    started = time.perf_counter()
    try:
        current_state = await main_module.sm.get_or_create(trigger_event.target_id)
        analysis_req = await main_module.l1.build_analysis_request(
            trigger_event.target_id,
            trigger_event,
            triggered_rules,
            current_state,
        )
        verdict = await main_module.l2.analyze_deterministically(
            analysis_req,
            reason="local testbench profile",
        )
        await main_module.sm.apply_l2_verdict(
            verdict.target_id,
            verdict.recommended_action,
            verdict.risk_score,
        )
        await main_module._persist_runtime_snapshot()
        return verdict.model_dump(mode="json"), round((time.perf_counter() - started) * 1000.0, 2), None
    except Exception as exc:
        return None, round((time.perf_counter() - started) * 1000.0, 2), f"local L2 execution failed: {exc}"


def _latest_target_event(
    event_pairs: list[tuple[GameEventLog, dict[str, Any]]],
    target_id: str,
) -> GameEventLog:
    for event, _payload in reversed(event_pairs):
        if event.target_id == target_id:
            return event
    raise ValueError(f"no event found for target_id {target_id}")


def _select_scenarios(dataset: TestbenchDataset, selected: Sequence[str]) -> list[ScenarioFixture]:
    if not selected:
        return list(dataset.scenarios)

    selected_set = set(selected)
    scenarios = [scenario for scenario in dataset.scenarios if scenario.scenario_id in selected_set]
    missing = sorted(selected_set - {scenario.scenario_id for scenario in scenarios})
    if missing:
        raise ValueError(f"selected scenarios not found in fixture: {', '.join(missing)}")
    return scenarios


def _build_http_client(config: RunnerConfig) -> httpx.AsyncClient:
    if config.profile is RunnerProfile.LOCAL:
        from backend.main import app

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )
    return httpx.AsyncClient(base_url=config.base_url, timeout=config.timeout_seconds)


async def _request_json(
    *,
    client: httpx.AsyncClient,
    method: str,
    path: str,
    retry_attempts: int,
    timeout_seconds: float,
    headers: Mapping[str, str] | None = None,
    data: Mapping[str, Any] | None = None,
    json_body: Mapping[str, Any] | None = None,
) -> tuple[Any, float, str | None]:
    del timeout_seconds
    policy = load_operational_testbench_policy().failure
    attempt = 1

    while True:
        started = time.perf_counter()
        try:
            response = await client.request(
                method=method,
                url=path,
                headers=dict(headers or {}),
                data=data,
                json=json_body,
            )
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            response.raise_for_status()
            return response.json(), latency_ms, None
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            disposition = classify_failure(
                FailureType.INFRA_DEPENDENCY,
                attempt=attempt,
                policy=policy,
            )
            if disposition is FailureDisposition.RETRY and attempt <= retry_attempts:
                attempt += 1
                await asyncio.sleep(0)
                continue
            return None, latency_ms, f"{method} {path} failed after {attempt} attempt(s): {exc}"


def _build_failure(
    *,
    failure_type: FailureType,
    disposition: FailureDisposition,
    mode: TestbenchMode,
    scenario_id: str | None,
    message: str,
    failed_gates: list[str],
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "failure_type": failure_type.value,
        "message": message,
        "failed_gates": failed_gates,
        "ci_block": should_block_ci(failure_type, disposition, mode, load_operational_testbench_policy().failure),
        "notify_ops": should_notify_ops(failure_type, disposition, mode, load_operational_testbench_policy().failure),
    }


def _determine_exit_code(failures: Sequence[Mapping[str, Any]]) -> RunnerExitCode:
    failure_types = {failure.get("failure_type") for failure in failures}
    if FailureType.INVALID_FIXTURE.value in failure_types:
        return RunnerExitCode.INVALID_FIXTURE
    if FailureType.INFRA_DEPENDENCY.value in failure_types:
        return RunnerExitCode.INFRA_DEPENDENCY_FAIL
    if FailureType.QUALITY_GATE.value in failure_types:
        return RunnerExitCode.QUALITY_GATE_FAIL
    return RunnerExitCode.ALL_PASS


def _build_terminal_summary(
    *,
    config: RunnerConfig,
    dataset_name: str,
    dataset_version: str,
    scenario_results: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    latencies_ms: list[float],
    exit_code: RunnerExitCode,
) -> dict[str, Any]:
    passed = sum(1 for scenario in scenario_results if scenario.get("passed"))
    failed = len(scenario_results) - passed
    success_rate = round((passed / len(scenario_results)), 4) if scenario_results else 0.0
    latency_summary = _latency_summary(latencies_ms)
    slo = load_operational_testbench_policy().slos[config.mode]
    slo_passed = (
        success_rate >= slo.min_success_rate
        and latency_summary["p95"] <= float(slo.max_p95_latency_ms)
        and failed <= slo.max_failures
    )

    return {
        "run_id": config.run_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if exit_code is RunnerExitCode.ALL_PASS else "failed",
        "profile": config.profile.value,
        "mode": config.mode.value,
        "dataset": dataset_name,
        "dataset_version": dataset_version,
        "scenarios_total": len(scenario_results),
        "scenarios_passed": passed,
        "scenarios_failed": failed,
        "request_count": len(latencies_ms),
        "success_rate": success_rate,
        "latency_ms": latency_summary,
        "slo": {
            "min_success_rate": slo.min_success_rate,
            "max_p95_latency_ms": slo.max_p95_latency_ms,
            "max_failures": slo.max_failures,
            "passed": slo_passed,
        },
        "failure_count": len(failures),
        "exit_code": exit_code.value,
        "scenarios": scenario_results,
    }


def _write_artifacts(
    artifacts_dir: Path,
    summary: dict[str, Any],
    failures: list[dict[str, Any]],
) -> None:
    (artifacts_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    (artifacts_dir / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    (artifacts_dir / "report.md").write_text(
        _build_report_markdown(summary, failures),
        encoding="utf-8",
    )
    (artifacts_dir / "junit.xml").write_text(
        _build_junit_xml(summary, failures),
        encoding="utf-8",
    )


def _build_report_markdown(summary: Mapping[str, Any], failures: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Susanoh Operational Testbench Report",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Profile: `{summary['profile']}`",
        f"- Mode: `{summary['mode']}`",
        f"- Dataset: `{summary['dataset']}` ({summary['dataset_version']})",
        f"- Exit Code: `{summary['exit_code']}`",
        f"- Success Rate: `{summary['success_rate']}`",
        f"- Latency p95: `{summary['latency_ms']['p95']}` ms",
        "",
        "## Scenarios",
        "",
    ]

    for scenario in summary.get("scenarios", []):
        state = "PASS" if scenario["passed"] else "FAIL"
        lines.append(
            f"- `{scenario['scenario_id']}`: {state} "
            f"(target=`{scenario['target_id']}`, failed_gates={scenario['failed_gates']})"
        )

    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(
                f"- `{failure.get('scenario_id') or 'run'}`: {failure['failure_type']} - {failure['message']}"
            )

    return "\n".join(lines) + "\n"


def _build_junit_xml(summary: Mapping[str, Any], failures: Sequence[Mapping[str, Any]]) -> str:
    failure_map: dict[str | None, list[Mapping[str, Any]]] = {}
    for failure in failures:
        failure_map.setdefault(failure.get("scenario_id"), []).append(failure)

    testsuite = ET.Element(
        "testsuite",
        attrib={
            "name": "susanoh-operational-testbench",
            "tests": str(len(summary.get("scenarios", []))),
            "failures": str(sum(1 for scenario in summary.get("scenarios", []) if not scenario["passed"])),
            "errors": str(sum(1 for failure in failures if failure["failure_type"] != FailureType.QUALITY_GATE.value)),
        },
    )

    for scenario in summary.get("scenarios", []):
        testcase = ET.SubElement(
            testsuite,
            "testcase",
            attrib={
                "classname": f"{summary['profile']}.{summary['mode']}",
                "name": scenario["scenario_id"],
            },
        )
        for failure in failure_map.get(scenario["scenario_id"], []):
            tag = "failure" if failure["failure_type"] == FailureType.QUALITY_GATE.value else "error"
            element = ET.SubElement(
                testcase,
                tag,
                attrib={"message": failure["failure_type"]},
            )
            element.text = failure["message"]

    return ET.tostring(testsuite, encoding="unicode")


def _latency_summary(latencies_ms: Sequence[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}

    ordered = sorted(float(value) for value in latencies_ms)
    return {
        "p50": _percentile(ordered, 50),
        "p95": _percentile(ordered, 95),
        "p99": _percentile(ordered, 99),
    }


def _percentile(values: Sequence[float], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(float(values[0]), 2)

    position = (len(values) - 1) * (percentile / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(float(values[int(position)]), 2)
    weight = position - lower
    interpolated = values[lower] + (values[upper] - values[lower]) * weight
    return round(float(interpolated), 2)


def _load_timeout_seconds(env: Mapping[str, str]) -> float:
    raw = env.get("SUSANOH_TESTBENCH_TIMEOUT_SECONDS", "10").strip()
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise ValueError("SUSANOH_TESTBENCH_TIMEOUT_SECONDS must be numeric") from exc
    if timeout <= 0:
        raise ValueError("SUSANOH_TESTBENCH_TIMEOUT_SECONDS must be greater than 0")
    return timeout


def _api_key_headers(api_key: str | None) -> dict[str, str]:
    return {"X-API-KEY": api_key} if api_key else {}


def _first_configured_api_key(raw: str) -> str | None:
    for chunk in raw.split(","):
        value = chunk.strip()
        if value:
            return value
    return None


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value:
            trimmed = value.strip()
            if trimmed:
                return trimmed
    return None


@contextmanager
def _local_background_l2_suppressed(profile: RunnerProfile):
    if profile is not RunnerProfile.LOCAL:
        yield
        return

    import backend.main as main_module

    original_create_task = main_module.asyncio.create_task

    def _drop_background_task(coro):
        coro.close()
        return None

    main_module.asyncio.create_task = _drop_background_task
    try:
        yield
    finally:
        main_module.asyncio.create_task = original_create_task


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Susanoh operational testbench scenarios.")
    parser.add_argument("--profile", choices=[profile.value for profile in RunnerProfile], default="local")
    parser.add_argument("--mode", choices=[mode.value for mode in TestbenchMode], default=TestbenchMode.REGRESSION.value)
    parser.add_argument("--fixtures-dir", default=str(DEFAULT_FIXTURES_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--scenario", action="append", default=[])

    args = parser.parse_args(list(argv) if argv is not None else None)
    config = load_runner_config(
        profile=RunnerProfile(args.profile),
        mode=TestbenchMode(args.mode),
        fixtures_dir=Path(args.fixtures_dir),
        output_root=Path(args.output_root),
        run_id=args.run_id,
        selected_scenarios=args.scenario,
    )
    result = asyncio.run(run_testbench(config))
    print(json.dumps(result.summary, ensure_ascii=True))
    return int(result.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())

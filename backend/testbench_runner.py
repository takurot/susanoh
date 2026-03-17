from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend import live_api_verification
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


class FaultInjectionType(str, Enum):
    GEMINI_TIMEOUT = "gemini_timeout"
    GEMINI_429 = "gemini_429"
    GEMINI_5XX = "gemini_5xx"


class ScenarioFaultInjection(BaseModel):
    type: FaultInjectionType

    def applies(self, *, profile: RunnerProfile, mode: TestbenchMode) -> bool:
        return profile is RunnerProfile.LOCAL and mode is TestbenchMode.REGRESSION

    def error_message(self) -> str:
        if self.type is FaultInjectionType.GEMINI_TIMEOUT:
            return "Gemini API took too long"
        if self.type is FaultInjectionType.GEMINI_429:
            return "429 Too Many Requests"
        return "503 Service Unavailable"

    def expected_reason_substring(self) -> str:
        return f"Local fallback: API error: {self.error_message()}"

    def build_exception(self) -> Exception:
        if self.type is FaultInjectionType.GEMINI_TIMEOUT:
            return TimeoutError(self.error_message())
        return RuntimeError(self.error_message())


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
    soak_iterations: int | None = None


@dataclass(frozen=True)
class TestbenchRunResult:
    summary: dict[str, Any]
    failures: list[dict[str, Any]]
    artifacts_dir: Path
    exit_code: RunnerExitCode


@dataclass(frozen=True)
class SoakReplayPlan:
    iterations_planned: int
    target_tps: float
    duration_minutes: int
    machine_profile: str
    scenario_execution_count: int
    event_replay_count: int


class ScenarioExpectation(BaseModel):
    target_id: str
    l1_primary_rules: list[str] = Field(default_factory=list)
    l2_fallback_action: AccountState = AccountState.NORMAL
    expected_state_path: list[AccountState] | None = None
    expected_l2_action_range: list[AccountState] | None = None
    max_p95_ms: int = Field(gt=0)
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
    fault_injection: ScenarioFaultInjection | None = None
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


class DatasetChangelogEntry(BaseModel):
    version: str
    released_at: str
    summary: str
    changes: list[str] = Field(default_factory=list)
    previous_version: str | None = None


REQUIRED_SCENARIOS = frozenset([
    "fraud_smurfing_fan_in",
    "fraud_direct_rmt_chat",
    "fraud_layering_chain_exit",
    "fraud_microburst_bot_farm",
    "fraud_market_price_abuse",
    "fraud_cross_cluster_bridge",
    "fraud_cashout_prep_sequence",
    "fraud_sleeper_activation",
    "gray_guild_treasury_collection",
    "gray_flash_sale_peak",
    "gray_streamer_donation_spike",
    "legit_new_season_rewards",
    "legit_friend_gifts_low_value",
    "legit_whale_purchase_high_avg",
    "legit_tournament_prize_batch",
])


class TestbenchDataset(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dataset: str
    dataset_version: str = Field(validation_alias=AliasChoices("dataset_version", "version"))
    generated_at: str
    seed: int
    scenario_count: int
    event_count: int
    changelog: list[DatasetChangelogEntry] = Field(default_factory=list)
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

        missing = REQUIRED_SCENARIOS - seen
        if missing:
            raise ValueError(
                f"missing required scenario categories: {', '.join(sorted(missing))}"
            )

        if not any(entry.version == self.dataset_version for entry in self.changelog):
            raise ValueError(
                f"dataset_version {self.dataset_version} is missing from changelog"
            )

        return self

    def current_changelog_entry(self) -> DatasetChangelogEntry:
        for entry in self.changelog:
            if entry.version == self.dataset_version:
                return entry
        raise ValueError(f"dataset_version {self.dataset_version} is missing from changelog")


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
    soak_iterations: int | None = None,
) -> RunnerConfig:
    src = os.environ if env is None else env
    policy = load_operational_testbench_policy()
    timeout_seconds = _load_timeout_seconds(src)
    soak_iterations_value = (
        _load_soak_iterations(src, explicit=soak_iterations)
        if mode is TestbenchMode.SOAK
        else None
    )

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
        soak_iterations=soak_iterations_value,
    )


def _load_soak_iterations(
    env: Mapping[str, str],
    *,
    explicit: int | None,
) -> int | None:
    if explicit is not None:
        if explicit <= 0:
            raise ValueError("soak_iterations must be greater than 0")
        return explicit

    raw = env.get("SUSANOH_TESTBENCH_SOAK_ITERATIONS", "").strip()
    if not raw:
        return None

    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("SUSANOH_TESTBENCH_SOAK_ITERATIONS must be an integer") from exc
    if value <= 0:
        raise ValueError("SUSANOH_TESTBENCH_SOAK_ITERATIONS must be greater than 0")
    return value


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


def _build_soak_plan(
    scenarios: Sequence[ScenarioFixture],
    *,
    configured_iterations: int | None,
) -> SoakReplayPlan:
    policy = load_operational_testbench_policy().load_targets[TestbenchMode.SOAK]
    events_per_cycle = sum(len(scenario.events) for scenario in scenarios)
    if configured_iterations is None:
        target_events = math.ceil(policy.target_tps * policy.duration_minutes * 60)
        iterations = max(1, math.ceil(target_events / max(events_per_cycle, 1)))
    else:
        iterations = configured_iterations

    return SoakReplayPlan(
        iterations_planned=iterations,
        target_tps=policy.target_tps,
        duration_minutes=policy.duration_minutes,
        machine_profile=policy.machine_profile,
        scenario_execution_count=len(scenarios) * iterations,
        event_replay_count=events_per_cycle * iterations,
    )


def _peak_rss_mb() -> float | None:
    try:
        import resource
    except ImportError:
        return None

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(float(rss) / float(divisor), 2)


async def _pace_soak_replay(
    *,
    replayed_event_count: int,
    started_at: float,
    target_tps: float,
) -> None:
    if replayed_event_count <= 0 or target_tps <= 0:
        return

    expected_elapsed_seconds = replayed_event_count / target_tps
    remaining_seconds = expected_elapsed_seconds - (time.perf_counter() - started_at)
    if remaining_seconds > 0:
        await asyncio.sleep(remaining_seconds)


async def run_testbench(config: RunnerConfig) -> TestbenchRunResult:
    artifacts_dir = config.output_root / config.run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    try:
        dataset = load_testbench_fixture(config.fixtures_dir)
        scenarios = _select_scenarios(dataset, config.selected_scenarios, config.mode)
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
            dataset_changelog=None,
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
    execution_totals: dict[str, int] | None = None
    extra_summary: dict[str, Any] | None = None

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
                if config.mode is TestbenchMode.SOAK:
                    soak_plan = _build_soak_plan(
                        scenarios,
                        configured_iterations=config.soak_iterations,
                    )
                    soak_aggregates: dict[str, dict[str, Any]] = {}
                    peak_rss_before_mb = _peak_rss_mb()
                    soak_started_at = time.perf_counter()
                    replayed_event_count = 0
                    for iteration in range(1, soak_plan.iterations_planned + 1):
                        iteration_config = replace(
                            config,
                            run_id=f"{config.run_id}-it{iteration:05d}",
                        )
                        for scenario in scenarios:
                            result = await _run_scenario(
                                client=client,
                                config=iteration_config,
                                scenario=scenario,
                                auth_headers=auth_headers,
                                event_headers=event_headers,
                            )
                            _record_soak_execution(
                                soak_aggregates,
                                result["scenario"],
                                result["latencies_ms"],
                            )
                            failures.extend(
                                _annotate_failures_for_iteration(result["failures"], iteration=iteration)
                            )
                            latencies_ms.extend(result["latencies_ms"])
                            replayed_event_count += len(scenario.events)
                            await _pace_soak_replay(
                                replayed_event_count=replayed_event_count,
                                started_at=soak_started_at,
                                target_tps=soak_plan.target_tps,
                            )

                    scenario_results = _finalize_soak_scenario_results(soak_aggregates)
                    peak_rss_after_mb = _peak_rss_mb()
                    execution_totals = {
                        "total": soak_plan.scenario_execution_count,
                        "passed": sum(item["passed_iterations"] for item in scenario_results),
                        "failed": sum(item["failed_iterations"] for item in scenario_results),
                    }
                    extra_summary = {
                        "soak": {
                            "iterations_planned": soak_plan.iterations_planned,
                            "target_tps": soak_plan.target_tps,
                            "duration_minutes": soak_plan.duration_minutes,
                            "machine_profile": soak_plan.machine_profile,
                            "scenario_execution_count": soak_plan.scenario_execution_count,
                            "event_replay_count": soak_plan.event_replay_count,
                            "state_drift_count": sum(
                                item["state_drift_count"] for item in scenario_results
                            ),
                            "peak_rss_mb": peak_rss_after_mb,
                            "peak_rss_growth_mb": (
                                round(max(peak_rss_after_mb - peak_rss_before_mb, 0.0), 2)
                                if peak_rss_before_mb is not None and peak_rss_after_mb is not None
                                else None
                            ),
                        }
                    }
                else:
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

    if (
        config.profile is RunnerProfile.STAGING
        and config.mode is TestbenchMode.LIVE
        and scenario_results
    ):
        live_summary, live_failures = await _run_live_verification_probe(config)
        failures.extend(live_failures)
        extra_summary = dict(extra_summary or {})
        extra_summary["live_verification"] = live_summary

    exit_code = _determine_exit_code(failures)
    summary = _build_terminal_summary(
        config=config,
        dataset_name=dataset.dataset,
        dataset_version=dataset.dataset_version,
        dataset_changelog=dataset.current_changelog_entry().model_dump(mode="json"),
        scenario_results=scenario_results,
        failures=failures,
        latencies_ms=latencies_ms,
        exit_code=exit_code,
        execution_totals=execution_totals,
        extra_summary=extra_summary,
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
                mode=config.mode,
                fault_injection=namespaced.fault_injection,
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

    latency_stats = _latency_summary(latencies_ms)
    p95_ok = latency_stats["p95"] <= namespaced.expected.max_p95_ms

    applied_fault_injection = bool(
        namespaced.fault_injection
        and namespaced.fault_injection.applies(
            profile=config.profile,
            mode=config.mode,
        )
    )

    gates = {
        "l1_rule_match": observed_l1_rules == expected_l1_rules,
        "state_path_match": observed_state_path == expected_state_path,
        "l2_action_range_match": observed_l2_action in expected_l2_actions,
        "api_availability": api_available,
        "latency_p95_match": p95_ok,
    }
    if applied_fault_injection:
        reasoning = latest_analysis.get("reasoning", "") if latest_analysis else ""
        gates["fault_injection_match"] = (
            isinstance(reasoning, str)
            and namespaced.fault_injection.expected_reason_substring() in reasoning
        )
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
        "max_p95_ms": namespaced.expected.max_p95_ms,
        "observed_l2_action": observed_l2_action,
        "final_state": final_state,
        "fault_injection": (
            namespaced.fault_injection.model_dump(mode="json")
            if namespaced.fault_injection is not None
            else None
        ),
        "fault_injection_applied": applied_fault_injection,
        "analysis_reasoning": latest_analysis.get("reasoning") if latest_analysis else None,
        "request_count": len(latencies_ms),
        "latency_ms": latency_stats,
        "quality_gates": gates,
    }
    return {
        "scenario": scenario_summary,
        "failures": failures,
        "latencies_ms": latencies_ms,
    }


async def _run_live_verification_probe(
    config: RunnerConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    verification_config = live_api_verification.LiveAPIVerificationConfig(
        base_url=config.base_url,
        username=config.username,
        password=config.password,
        api_key=config.api_key,
        timeout_seconds=config.timeout_seconds,
    )
    started = time.perf_counter()

    try:
        result = await live_api_verification.run_live_api_verification(verification_config)
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        failure = _build_failure(
            failure_type=FailureType.INFRA_DEPENDENCY,
            disposition=FailureDisposition.FAIL_AFTER_RETRY,
            mode=config.mode,
            scenario_id=None,
            message=f"live API verification failed: {exc}",
            failed_gates=["live_verification"],
        )
        return (
            {
                "ok": False,
                "latency_ms": latency_ms,
                "target_id": None,
                "risk_score": None,
                "recommended_action": None,
                "error": str(exc),
            },
            [failure],
        )

    latency_ms = round(float(result.get("latency_ms", 0.0)), 2)
    live_summary = {
        "ok": result.get("ok") is True,
        "latency_ms": latency_ms,
        "target_id": result.get("target_id"),
        "risk_score": result.get("risk_score"),
        "recommended_action": result.get("recommended_action"),
        "error": None,
    }
    if live_summary["ok"]:
        return live_summary, []

    error_message = str(result.get("error") or "live API verification returned unsuccessful result")
    live_summary["error"] = error_message
    failure = _build_failure(
        failure_type=FailureType.INFRA_DEPENDENCY,
        disposition=FailureDisposition.FAIL_AFTER_RETRY,
        mode=config.mode,
        scenario_id=None,
        message=f"live API verification failed: {error_message}",
        failed_gates=["live_verification"],
    )
    return live_summary, [failure]


def _record_soak_execution(
    aggregates: dict[str, dict[str, Any]],
    scenario_summary: Mapping[str, Any],
    latencies_ms: Sequence[float],
) -> None:
    scenario_id = str(scenario_summary["scenario_id"])
    aggregate = aggregates.get(scenario_id)
    if aggregate is None:
        aggregate = {
            "scenario_id": scenario_id,
            "title": scenario_summary["title"],
            "risk_tier": scenario_summary["risk_tier"],
            "expected_l1_rules": list(scenario_summary.get("expected_l1_rules", [])),
            "expected_state_path": list(scenario_summary.get("expected_state_path", [])),
            "expected_l2_actions": list(scenario_summary.get("expected_l2_actions", [])),
            "max_p95_ms": scenario_summary["max_p95_ms"],
            "iterations": 0,
            "passed_iterations": 0,
            "failed_iterations": 0,
            "state_drift_count": 0,
            "request_count": 0,
            "latencies_ms": [],
            "iteration_p95s": [],
            "failed_gates": set(),
            "quality_gates": {},
            "fault_injection": scenario_summary.get("fault_injection"),
            "fault_injection_applied": False,
            "baseline_signature": None,
            "baseline_observed_l1_rules": [],
            "baseline_observed_state_path": [],
            "baseline_observed_l2_action": None,
            "baseline_final_state": None,
            "last_target_id": scenario_summary.get("target_id"),
            "last_observed_l1_rules": [],
            "last_observed_state_path": [],
            "last_observed_l2_action": None,
            "last_final_state": None,
            "last_analysis_reasoning": None,
        }
        aggregates[scenario_id] = aggregate

    aggregate["iterations"] += 1
    if bool(scenario_summary.get("passed")):
        aggregate["passed_iterations"] += 1
    else:
        aggregate["failed_iterations"] += 1
    aggregate["request_count"] += int(scenario_summary.get("request_count", 0))
    aggregate["latencies_ms"].extend(float(value) for value in latencies_ms)
    aggregate["iteration_p95s"].append(float(scenario_summary.get("latency_ms", {}).get("p95", 0.0)))
    aggregate["failed_gates"].update(str(gate) for gate in scenario_summary.get("failed_gates", []))
    aggregate["fault_injection_applied"] = aggregate["fault_injection_applied"] or bool(
        scenario_summary.get("fault_injection_applied")
    )

    for gate, passed in scenario_summary.get("quality_gates", {}).items():
        counts = aggregate["quality_gates"].setdefault(gate, {"passed": 0, "failed": 0})
        counts["passed" if passed else "failed"] += 1

    observed_l1_rules = list(scenario_summary.get("observed_l1_rules", []))
    observed_state_path = list(scenario_summary.get("observed_state_path", []))
    observed_l2_action = scenario_summary.get("observed_l2_action")
    final_state = scenario_summary.get("final_state")
    signature = (
        tuple(observed_l1_rules),
        tuple(observed_state_path),
        observed_l2_action,
        final_state,
    )
    if aggregate["baseline_signature"] is None:
        aggregate["baseline_signature"] = signature
        aggregate["baseline_observed_l1_rules"] = observed_l1_rules
        aggregate["baseline_observed_state_path"] = observed_state_path
        aggregate["baseline_observed_l2_action"] = observed_l2_action
        aggregate["baseline_final_state"] = final_state
    elif signature != aggregate["baseline_signature"]:
        aggregate["state_drift_count"] += 1

    aggregate["last_target_id"] = scenario_summary.get("target_id")
    aggregate["last_observed_l1_rules"] = observed_l1_rules
    aggregate["last_observed_state_path"] = observed_state_path
    aggregate["last_observed_l2_action"] = observed_l2_action
    aggregate["last_final_state"] = final_state
    aggregate["last_analysis_reasoning"] = scenario_summary.get("analysis_reasoning")


def _annotate_failures_for_iteration(
    failures: Sequence[Mapping[str, Any]],
    *,
    iteration: int,
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for failure in failures:
        tagged = dict(failure)
        tagged["iteration"] = iteration
        tagged["message"] = f"[iteration {iteration}] {tagged['message']}"
        annotated.append(tagged)
    return annotated


def _finalize_soak_scenario_results(
    aggregates: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for scenario_id in sorted(aggregates):
        aggregate = aggregates[scenario_id]
        iteration_p95s = [float(value) for value in aggregate["iteration_p95s"]]
        finalized.append(
            {
                "scenario_id": aggregate["scenario_id"],
                "title": aggregate["title"],
                "risk_tier": aggregate["risk_tier"],
                "target_id": aggregate["last_target_id"],
                "passed": aggregate["failed_iterations"] == 0,
                "failed_gates": sorted(aggregate["failed_gates"]),
                "expected_l1_rules": list(aggregate["expected_l1_rules"]),
                "observed_l1_rules": list(aggregate["last_observed_l1_rules"]),
                "expected_state_path": list(aggregate["expected_state_path"]),
                "observed_state_path": list(aggregate["last_observed_state_path"]),
                "expected_l2_actions": list(aggregate["expected_l2_actions"]),
                "max_p95_ms": aggregate["max_p95_ms"],
                "observed_l2_action": aggregate["last_observed_l2_action"],
                "final_state": aggregate["last_final_state"],
                "fault_injection": aggregate["fault_injection"],
                "fault_injection_applied": aggregate["fault_injection_applied"],
                "analysis_reasoning": aggregate["last_analysis_reasoning"],
                "request_count": aggregate["request_count"],
                "latency_ms": _latency_summary(aggregate["latencies_ms"]),
                "iteration_latency_ms": {
                    "first_p95": iteration_p95s[0] if iteration_p95s else 0.0,
                    "last_p95": iteration_p95s[-1] if iteration_p95s else 0.0,
                    "max_p95": max(iteration_p95s) if iteration_p95s else 0.0,
                },
                "quality_gates": {
                    gate: {
                        "passed": counts["passed"],
                        "failed": counts["failed"],
                    }
                    for gate, counts in sorted(aggregate["quality_gates"].items())
                },
                "iterations": aggregate["iterations"],
                "passed_iterations": aggregate["passed_iterations"],
                "failed_iterations": aggregate["failed_iterations"],
                "state_drift_count": aggregate["state_drift_count"],
            }
        )
    return finalized


async def _run_local_l2(
    *,
    scenario: ScenarioFixture,
    event_pairs: list[tuple[GameEventLog, dict[str, Any]]],
    mode: TestbenchMode,
    fault_injection: ScenarioFaultInjection | None,
) -> tuple[dict[str, Any] | None, float, str | None]:
    import backend.main as main_module

    trigger_event = _latest_target_event(event_pairs, scenario.expected.target_id)
    triggered_rules_set = set()
    for event, payload in event_pairs:
        if event.target_id == scenario.expected.target_id:
            triggered_rules_set.update(payload.get("triggered_rules", []))
            if payload.get("triggered_rules"):
                trigger_event = event

    triggered_rules = sorted(list(triggered_rules_set))
    started = time.perf_counter()
    try:
        current_state = await main_module.sm.get_or_create(trigger_event.target_id)
        analysis_req = await main_module.l1.build_analysis_request(
            trigger_event.target_id,
            trigger_event,
            triggered_rules,
            current_state,
        )
        if fault_injection is not None and fault_injection.applies(
            profile=RunnerProfile.LOCAL,
            mode=mode,
        ):
            verdict = await _run_local_l2_with_fault_injection(
                analysis_req=analysis_req,
                fault_injection=fault_injection,
            )
        else:
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


async def _run_local_l2_with_fault_injection(
    *,
    analysis_req: Any,
    fault_injection: ScenarioFaultInjection,
):
    import backend.main as main_module

    async def _raise_injected_error(_request, _api_key):
        raise fault_injection.build_exception()

    return await main_module.l2.analyze_with_overrides(
        analysis_req,
        api_key="testbench-fault-injection",
        gemini_call=_raise_injected_error,
    )


def _latest_target_event(
    event_pairs: list[tuple[GameEventLog, dict[str, Any]]],
    target_id: str,
) -> GameEventLog:
    for event, _payload in reversed(event_pairs):
        if event.target_id == target_id:
            return event
    raise ValueError(f"no event found for target_id {target_id}")


def _select_scenarios(dataset: TestbenchDataset, selected: Sequence[str], mode: TestbenchMode) -> list[ScenarioFixture]:
    if not selected:
        if mode is TestbenchMode.SMOKE:
            selected = [
                "fraud_smurfing_fan_in",
                "fraud_direct_rmt_chat",
                "legit_new_season_rewards",
                "legit_friend_gifts_low_value",
            ]
        else:
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
    dataset_changelog: Mapping[str, Any] | None,
    scenario_results: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    latencies_ms: list[float],
    exit_code: RunnerExitCode,
    execution_totals: Mapping[str, int] | None = None,
    extra_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if execution_totals is None:
        total = len(scenario_results)
        passed = sum(1 for scenario in scenario_results if scenario.get("passed"))
        failed = total - passed
    else:
        total = execution_totals["total"]
        passed = execution_totals["passed"]
        failed = execution_totals["failed"]

    success_rate = round((passed / total), 4) if total else 0.0
    latency_summary = _latency_summary(latencies_ms)
    slo = load_operational_testbench_policy().slos[config.mode]
    slo_passed = (
        success_rate >= slo.min_success_rate
        and latency_summary["p95"] <= float(slo.max_p95_latency_ms)
        and failed <= slo.max_failures
        and not failures
    )

    summary = {
        "run_id": config.run_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if exit_code is RunnerExitCode.ALL_PASS else "failed",
        "profile": config.profile.value,
        "mode": config.mode.value,
        "dataset": dataset_name,
        "dataset_version": dataset_version,
        "scenarios_total": total,
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
    if dataset_changelog:
        summary["dataset_changelog"] = dict(dataset_changelog)
    if extra_summary:
        summary.update(extra_summary)
    return summary


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
    ]

    dataset_changelog = summary.get("dataset_changelog")
    if isinstance(dataset_changelog, Mapping):
        lines.extend(
            [
                "## Dataset Release",
                "",
                f"- Released At: `{dataset_changelog['released_at']}`",
                f"- Summary: {dataset_changelog['summary']}",
            ]
        )
        previous_version = dataset_changelog.get("previous_version")
        if previous_version:
            lines.append(f"- Compare From: `{previous_version}`")
        for change in dataset_changelog.get("changes", []):
            lines.append(f"- Change: {change}")
        lines.append("")

    soak_summary = summary.get("soak")
    if isinstance(soak_summary, Mapping):
        lines.extend(
            [
                "## Soak Replay",
                "",
                f"- Iterations Planned: `{soak_summary['iterations_planned']}`",
                f"- Scenario Executions: `{soak_summary['scenario_execution_count']}`",
                f"- Event Replays: `{soak_summary['event_replay_count']}`",
                f"- State Drift Count: `{soak_summary['state_drift_count']}`",
            ]
        )
        peak_rss_mb = soak_summary.get("peak_rss_mb")
        if peak_rss_mb is not None:
            lines.append(f"- Peak RSS: `{peak_rss_mb}` MiB")
        peak_rss_growth_mb = soak_summary.get("peak_rss_growth_mb")
        if peak_rss_growth_mb is not None:
            lines.append(f"- Peak RSS Growth: `{peak_rss_growth_mb}` MiB")
        lines.append("")

    live_verification = summary.get("live_verification")
    if isinstance(live_verification, Mapping):
        status = "PASS" if live_verification.get("ok") else "FAIL"
        lines.extend(
            [
                "## Live Verification",
                "",
                f"- Status: `{status}`",
                f"- Latency: `{live_verification.get('latency_ms', 0.0)}` ms",
            ]
        )
        if live_verification.get("target_id"):
            lines.append(f"- Target: `{live_verification['target_id']}`")
        if live_verification.get("risk_score") is not None:
            lines.append(f"- Risk Score: `{live_verification['risk_score']}`")
        if live_verification.get("recommended_action"):
            lines.append(f"- Recommended Action: `{live_verification['recommended_action']}`")
        if live_verification.get("error"):
            lines.append(f"- Error: `{live_verification['error']}`")
        lines.append("")

    lines.extend(["## Scenarios", ""])

    for scenario in summary.get("scenarios", []):
        state = "PASS" if scenario["passed"] else "FAIL"
        fault_suffix = ""
        if scenario.get("fault_injection_applied") and scenario.get("fault_injection"):
            fault_suffix = f", fault={scenario['fault_injection']['type']}"
        soak_suffix = ""
        if "iterations" in scenario:
            soak_suffix = (
                f", iterations={scenario['iterations']}, drift={scenario['state_drift_count']}"
            )
        lines.append(
            f"- `{scenario['scenario_id']}`: {state} "
            f"(target=`{scenario['target_id']}`, failed_gates={scenario['failed_gates']}"
            f"{soak_suffix}{fault_suffix})"
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

    live_verification = summary.get("live_verification")
    live_case_count = 1 if isinstance(live_verification, Mapping) else 0
    has_live_failure = bool(isinstance(live_verification, Mapping) and not live_verification.get("ok"))
    has_live_failure_record = any(
        failure.get("scenario_id") is None
        and str(failure.get("message", "")).startswith("live API verification failed:")
        for failure in failures
    )
    error_count = sum(1 for failure in failures if failure["failure_type"] != FailureType.QUALITY_GATE.value)
    if has_live_failure and not has_live_failure_record:
        error_count += 1
    testsuite = ET.Element(
        "testsuite",
        attrib={
            "name": "susanoh-operational-testbench",
            "tests": str(len(summary.get("scenarios", [])) + live_case_count),
            "failures": str(sum(1 for scenario in summary.get("scenarios", []) if not scenario["passed"])),
            "errors": str(error_count),
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

    if isinstance(live_verification, Mapping):
        testcase = ET.SubElement(
            testsuite,
            "testcase",
            attrib={
                "classname": f"{summary['profile']}.{summary['mode']}",
                "name": "live_api_verification",
            },
        )
        if not live_verification.get("ok"):
            element = ET.SubElement(
                testcase,
                "error",
                attrib={"message": FailureType.INFRA_DEPENDENCY.value},
            )
            element.text = str(
                live_verification.get("error")
                or "live API verification failed"
            )

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
    parser.add_argument("--soak-iterations", type=int)

    args = parser.parse_args(list(argv) if argv is not None else None)
    config = load_runner_config(
        profile=RunnerProfile(args.profile),
        mode=TestbenchMode(args.mode),
        fixtures_dir=Path(args.fixtures_dir),
        output_root=Path(args.output_root),
        run_id=args.run_id,
        selected_scenarios=args.scenario,
        soak_iterations=args.soak_iterations,
    )
    result = asyncio.run(run_testbench(config))
    print(json.dumps(result.summary, ensure_ascii=True))
    return int(result.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())

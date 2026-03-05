from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class TestbenchMode(str, Enum):
    __test__ = False

    SMOKE = "smoke"
    REGRESSION = "regression"
    SOAK = "soak"
    LIVE = "live"


class FailureType(str, Enum):
    QUALITY_GATE = "quality_gate"
    INFRA_DEPENDENCY = "infra_dependency"
    INVALID_FIXTURE = "invalid_fixture"


class FailureDisposition(str, Enum):
    IMMEDIATE_FAIL = "immediate_fail"
    RETRY = "retry"
    FAIL_AFTER_RETRY = "fail_after_retry"


@dataclass(frozen=True)
class ServiceLevelObjective:
    min_success_rate: float
    max_p95_latency_ms: int
    max_failures: int


@dataclass(frozen=True)
class LoadTarget:
    target_tps: float
    duration_minutes: int
    max_error_rate: float
    machine_profile: str


@dataclass(frozen=True)
class QualityGatePolicy:
    require_l1_rule_match: bool
    require_state_path_match: bool
    require_l2_action_range_match: bool
    require_api_availability: bool


@dataclass(frozen=True)
class FailurePolicy:
    max_retry_attempts: int
    immediate_failures: frozenset[FailureType]
    retryable_failures: frozenset[FailureType]
    ci_block_on: frozenset[str]
    notify_on: frozenset[str]


@dataclass(frozen=True)
class OperationalTestbenchPolicy:
    slos: Mapping[TestbenchMode, ServiceLevelObjective]
    load_targets: Mapping[TestbenchMode, LoadTarget]
    quality_gates: QualityGatePolicy
    failure: FailurePolicy


_DEFAULT_POLICY = OperationalTestbenchPolicy(
    slos={
        TestbenchMode.SMOKE: ServiceLevelObjective(
            min_success_rate=1.0,
            max_p95_latency_ms=1200,
            max_failures=0,
        ),
        TestbenchMode.REGRESSION: ServiceLevelObjective(
            min_success_rate=0.99,
            max_p95_latency_ms=1800,
            max_failures=2,
        ),
        TestbenchMode.SOAK: ServiceLevelObjective(
            min_success_rate=0.995,
            max_p95_latency_ms=2200,
            max_failures=8,
        ),
        TestbenchMode.LIVE: ServiceLevelObjective(
            min_success_rate=0.95,
            max_p95_latency_ms=5000,
            max_failures=1,
        ),
    },
    load_targets={
        TestbenchMode.REGRESSION: LoadTarget(
            target_tps=25.0,
            duration_minutes=30,
            max_error_rate=0.01,
            machine_profile="4 vCPU / 8 GB RAM / NVMe SSD / 1 Gbps network",
        ),
        TestbenchMode.SOAK: LoadTarget(
            target_tps=40.0,
            duration_minutes=240,
            max_error_rate=0.005,
            machine_profile="8 vCPU / 16 GB RAM / NVMe SSD / 1 Gbps network",
        ),
    },
    quality_gates=QualityGatePolicy(
        require_l1_rule_match=True,
        require_state_path_match=True,
        require_l2_action_range_match=True,
        require_api_availability=True,
    ),
    failure=FailurePolicy(
        max_retry_attempts=2,
        immediate_failures=frozenset({FailureType.QUALITY_GATE, FailureType.INVALID_FIXTURE}),
        retryable_failures=frozenset({FailureType.INFRA_DEPENDENCY}),
        ci_block_on=frozenset(
            {
                FailureType.QUALITY_GATE.value,
                FailureType.INVALID_FIXTURE.value,
                "infra_dependency_after_retry",
            }
        ),
        notify_on=frozenset({"infra_dependency_after_retry", "live_mode_failure"}),
    ),
)


def load_operational_testbench_policy() -> OperationalTestbenchPolicy:
    return _DEFAULT_POLICY


def classify_failure(
    failure_type: FailureType, *, attempt: int, policy: FailurePolicy
) -> FailureDisposition:
    if attempt < 1:
        raise ValueError("attempt must be >= 1")

    if failure_type in policy.immediate_failures:
        return FailureDisposition.IMMEDIATE_FAIL

    if failure_type in policy.retryable_failures:
        if attempt <= policy.max_retry_attempts:
            return FailureDisposition.RETRY
        return FailureDisposition.FAIL_AFTER_RETRY

    return FailureDisposition.IMMEDIATE_FAIL


def _to_signals(
    failure_type: FailureType,
    disposition: FailureDisposition,
    mode: TestbenchMode,
) -> set[str]:
    signals = {failure_type.value}
    if (
        failure_type is FailureType.INFRA_DEPENDENCY
        and disposition is FailureDisposition.FAIL_AFTER_RETRY
    ):
        signals.add("infra_dependency_after_retry")
    if mode is TestbenchMode.LIVE and disposition is not FailureDisposition.RETRY:
        signals.add("live_mode_failure")
    return signals


def should_block_ci(
    failure_type: FailureType,
    disposition: FailureDisposition,
    mode: TestbenchMode,
    policy: FailurePolicy,
) -> bool:
    signals = _to_signals(failure_type, disposition, mode)
    return bool(signals & policy.ci_block_on)


def should_notify_ops(
    failure_type: FailureType,
    disposition: FailureDisposition,
    mode: TestbenchMode,
    policy: FailurePolicy,
) -> bool:
    signals = _to_signals(failure_type, disposition, mode)
    return bool(signals & policy.notify_on)

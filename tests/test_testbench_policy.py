import pytest

from backend.testbench_policy import (
    FailureDisposition,
    FailureType,
    TestbenchMode,
    classify_failure,
    load_operational_testbench_policy,
    should_block_ci,
    should_notify_ops,
)


def test_policy_defines_slos_for_all_modes():
    policy = load_operational_testbench_policy()
    assert set(policy.slos) == set(TestbenchMode)


def test_policy_load_targets_are_defined_for_regression_and_soak():
    policy = load_operational_testbench_policy()
    assert set(policy.load_targets) == {TestbenchMode.REGRESSION, TestbenchMode.SOAK}

    regression = policy.load_targets[TestbenchMode.REGRESSION]
    assert regression.target_tps == 25.0
    assert regression.duration_minutes == 30
    assert regression.max_error_rate == 0.01
    assert "4 vCPU" in regression.machine_profile

    soak = policy.load_targets[TestbenchMode.SOAK]
    assert soak.target_tps == 40.0
    assert soak.duration_minutes == 240
    assert soak.max_error_rate == 0.005
    assert "8 vCPU" in soak.machine_profile


def test_policy_quality_gates_are_all_required():
    gates = load_operational_testbench_policy().quality_gates
    assert gates.require_l1_rule_match is True
    assert gates.require_state_path_match is True
    assert gates.require_l2_action_range_match is True
    assert gates.require_api_availability is True
    assert gates.require_latency_p95_match is True


def test_classify_failure_uses_fail_fast_and_retry_paths():
    policy = load_operational_testbench_policy()

    assert classify_failure(FailureType.INVALID_FIXTURE, attempt=1, policy=policy.failure) == (
        FailureDisposition.IMMEDIATE_FAIL
    )
    assert classify_failure(FailureType.QUALITY_GATE, attempt=1, policy=policy.failure) == (
        FailureDisposition.IMMEDIATE_FAIL
    )
    assert classify_failure(
        FailureType.INFRA_DEPENDENCY, attempt=1, policy=policy.failure
    ) == FailureDisposition.RETRY
    assert classify_failure(
        FailureType.INFRA_DEPENDENCY, attempt=3, policy=policy.failure
    ) == FailureDisposition.FAIL_AFTER_RETRY


def test_failure_policy_ci_block_and_ops_notification():
    policy = load_operational_testbench_policy()

    assert should_block_ci(
        FailureType.INVALID_FIXTURE, FailureDisposition.IMMEDIATE_FAIL, TestbenchMode.SMOKE, policy.failure
    )
    assert should_block_ci(
        FailureType.QUALITY_GATE, FailureDisposition.IMMEDIATE_FAIL, TestbenchMode.REGRESSION, policy.failure
    )
    assert should_block_ci(
        FailureType.INFRA_DEPENDENCY,
        FailureDisposition.FAIL_AFTER_RETRY,
        TestbenchMode.REGRESSION,
        policy.failure,
    )
    assert not should_block_ci(
        FailureType.INFRA_DEPENDENCY, FailureDisposition.RETRY, TestbenchMode.REGRESSION, policy.failure
    )

    assert should_notify_ops(
        FailureType.INFRA_DEPENDENCY,
        FailureDisposition.FAIL_AFTER_RETRY,
        TestbenchMode.SOAK,
        policy.failure,
    )
    assert should_notify_ops(
        FailureType.QUALITY_GATE,
        FailureDisposition.IMMEDIATE_FAIL,
        TestbenchMode.LIVE,
        policy.failure,
    )
    assert not should_notify_ops(
        FailureType.QUALITY_GATE,
        FailureDisposition.IMMEDIATE_FAIL,
        TestbenchMode.SMOKE,
        policy.failure,
    )


def test_classify_failure_rejects_invalid_attempt():
    policy = load_operational_testbench_policy()
    with pytest.raises(ValueError, match="attempt"):
        classify_failure(FailureType.INFRA_DEPENDENCY, attempt=0, policy=policy.failure)


def test_policy_mappings_are_immutable():
    policy = load_operational_testbench_policy()

    with pytest.raises(TypeError):
        policy.slos[TestbenchMode.SMOKE] = policy.slos[TestbenchMode.SMOKE]  # type: ignore[index]

    with pytest.raises(TypeError):
        policy.load_targets[TestbenchMode.REGRESSION] = policy.load_targets[TestbenchMode.REGRESSION]  # type: ignore[index]

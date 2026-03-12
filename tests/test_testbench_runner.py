import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from backend.models import ActionDetails, ContextMetadata, GameEventLog
from backend.testbench_policy import TestbenchMode
from backend.testbench_runner import (
    RunnerExitCode,
    RunnerProfile,
    _select_scenarios,
    apply_run_namespace,
    load_runner_config,
    load_testbench_fixture,
    run_testbench,
)


def _event(
    *,
    event_id: str,
    actor_id: str,
    target_id: str,
    amount: int,
    market_avg: int = 10_000,
    chat: str | None = None,
    timestamp: str,
) -> dict:
    return GameEventLog(
        event_id=event_id,
        timestamp=timestamp,
        actor_id=actor_id,
        target_id=target_id,
        action_details=ActionDetails(
            currency_amount=amount,
            market_avg_price=market_avg,
        ),
        context_metadata=ContextMetadata(
            actor_level=25,
            account_age_days=180,
            recent_chat_log=chat,
        ),
    ).model_dump()


def _write_fixture(
    root: Path,
    *,
    scenarios: list[dict],
    flattened_events: list[dict] | None = None,
) -> Path:
    fixture_dir = root / "fixture"
    fixture_dir.mkdir()

    total_events = sum(len(scenario["events"]) for scenario in scenarios)
    payload = {
        "dataset": "testbench-fixture",
        "version": "v-test",
        "generated_at": "2026-03-06T00:00:00Z",
        "seed": 123,
        "scenario_count": len(scenarios),
        "event_count": total_events,
        "scenarios": scenarios,
    }
    (fixture_dir / "scenarios.json").write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    lines = flattened_events
    if lines is None:
        lines = []
        for scenario in scenarios:
            for index, event in enumerate(scenario["events"], start=1):
                lines.append(
                    {
                        "scenario_id": scenario["scenario_id"],
                        "scenario_risk_tier": scenario["risk_tier"],
                        "sequence": index,
                        "event": event,
                    }
                )

    with (fixture_dir / "events.jsonl").open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=True))
            handle.write("\n")

    return fixture_dir


def _passing_scenarios() -> list[dict]:
    from backend.testbench_runner import REQUIRED_SCENARIOS

    scenarios = []

    for req_scenario in REQUIRED_SCENARIOS:
        scenarios.append({
            "scenario_id": req_scenario,
            "title": f"Local test - {req_scenario}",
            "pattern_family": "LEGITIMATE",
            "risk_tier": "low",
            "expected": {
                "target_id": f"acct_target_{req_scenario}",
                "l1_primary_rules": [],
                "l2_fallback_action": "NORMAL",
                "max_p95_ms": 5000,
                "notes": "Valid passing scenario.",
            },
            "events": [
                _event(
                    event_id=f"evt_{req_scenario}_01",
                    actor_id=f"acct_src_{req_scenario}",
                    target_id=f"acct_target_{req_scenario}",
                    amount=10_000,
                    timestamp="2099-01-01T00:00:00Z",
                ),
            ],
        })

    return scenarios


def _passing_scenarios_original() -> list[dict]:
    return [
        {
            "scenario_id": "fraud_runner_local",
            "title": "Local high-risk fraud",
            "pattern_family": "RMT_SMURFING",
            "risk_tier": "high",
            "expected": {
                "target_id": "acct_target_01",
                "l1_primary_rules": ["R1", "R4"],
                "l2_fallback_action": "BANNED",
                "max_p95_ms": 5000,
                "notes": "Five senders converge and the final trade contains slang.",
            },
            "events": [
                _event(
                    event_id="evt_hi_01",
                    actor_id="acct_src_01",
                    target_id="acct_target_01",
                    amount=300_000,
                    timestamp="2099-01-01T00:00:00Z",
                ),
                _event(
                    event_id="evt_hi_02",
                    actor_id="acct_src_02",
                    target_id="acct_target_01",
                    amount=300_000,
                    timestamp="2099-01-01T00:00:10Z",
                ),
                _event(
                    event_id="evt_hi_03",
                    actor_id="acct_src_03",
                    target_id="acct_target_01",
                    amount=300_000,
                    timestamp="2099-01-01T00:00:20Z",
                ),
                _event(
                    event_id="evt_hi_04",
                    actor_id="acct_src_04",
                    target_id="acct_target_01",
                    amount=300_000,
                    timestamp="2099-01-01T00:00:30Z",
                ),
                _event(
                    event_id="evt_hi_05",
                    actor_id="acct_src_05",
                    target_id="acct_target_01",
                    amount=300_000,
                    chat="confirm 14k via PayPal",
                    timestamp="2099-01-01T00:00:40Z",
                ),
            ],
        },
        {
            "scenario_id": "legit_runner_local",
            "title": "Local normal activity",
            "pattern_family": "LEGITIMATE",
            "risk_tier": "low",
            "expected": {
                "target_id": "acct_target_02",
                "l1_primary_rules": [],
                "l2_fallback_action": "NORMAL",
                "max_p95_ms": 5000,
                "notes": "Low-value transfer should remain normal.",
            },
            "events": [
                _event(
                    event_id="evt_lo_01",
                    actor_id="acct_friend_01",
                    target_id="acct_target_02",
                    amount=5_000,
                    timestamp="2099-01-01T00:01:00Z",
                ),
                _event(
                    event_id="evt_lo_02",
                    actor_id="acct_friend_02",
                    target_id="acct_target_02",
                    amount=7_500,
                    timestamp="2099-01-01T00:01:10Z",
                ),
            ],
        },
    ]


def test_load_runner_config_local_defaults(tmp_path):
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.REGRESSION,
        env={},
        fixtures_dir=tmp_path / "fixtures",
        output_root=tmp_path / "artifacts",
        run_id="run-local",
    )

    assert config.profile == RunnerProfile.LOCAL
    assert config.base_url == "http://test"
    assert config.username == "admin"
    assert config.password == "password123"
    assert config.timeout_seconds == 10.0
    assert config.retry_attempts == 2
    assert config.run_id == "run-local"


def test_load_runner_config_staging_requires_base_url_and_password(tmp_path):
    with pytest.raises(ValueError, match="SUSANOH_TESTBENCH_STAGING_BASE_URL"):
        load_runner_config(
            profile=RunnerProfile.STAGING,
            mode=TestbenchMode.LIVE,
            env={},
            fixtures_dir=tmp_path / "fixtures",
            output_root=tmp_path / "artifacts",
        )


def test_load_runner_config_ignores_soak_iterations_outside_soak_mode(tmp_path):
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.REGRESSION,
        env={"SUSANOH_TESTBENCH_SOAK_ITERATIONS": "oops"},
        fixtures_dir=tmp_path / "fixtures",
        output_root=tmp_path / "artifacts",
        run_id="run-regression",
    )

    assert config.mode is TestbenchMode.REGRESSION
    assert config.soak_iterations is None


def test_apply_run_namespace_suffixes_targets_and_event_ids():
    fixture_dir = Path("/tmp")
    _ = fixture_dir  # keep the test body symmetrical with other fixture helpers
    scenario = _passing_scenarios()[0]

    namespaced = apply_run_namespace(scenario, "run-abc")

    assert namespaced["expected"]["target_id"].endswith("__run-abc")
    assert namespaced["events"][0]["event_id"].endswith("__run-abc")
    assert namespaced["events"][0]["actor_id"].endswith("__run-abc")
    assert namespaced["events"][0]["target_id"].endswith("__run-abc")
    assert namespaced["events"][0]["target_id"] == namespaced["expected"]["target_id"]


@pytest.mark.asyncio
async def test_run_testbench_local_writes_artifacts_and_passes(tmp_path):
    scenarios = _passing_scenarios()
    fixture_dir = _write_fixture(tmp_path, scenarios=scenarios)
    output_root = tmp_path / "artifacts"
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.REGRESSION,
        env={},
        fixtures_dir=fixture_dir,
        output_root=output_root,
        run_id="run-pass",
    )

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.ALL_PASS
    assert result.summary["scenarios_total"] == len(scenarios)
    assert result.summary["scenarios_passed"] == len(scenarios)
    assert result.summary["scenarios_failed"] == 0
    assert result.summary["profile"] == "local"
    assert result.summary["mode"] == "regression"
    assert result.failures == []

    scenario_ids = {scenario["scenario_id"] for scenario in result.summary["scenarios"]}
    expected_scenario_ids = {s["scenario_id"] for s in scenarios}
    assert scenario_ids == expected_scenario_ids
    target_ids = {scenario["target_id"] for scenario in result.summary["scenarios"]}
    assert all(target_id.endswith("__run-pass") for target_id in target_ids)
    assert all(scenario["max_p95_ms"] == 5000 for scenario in result.summary["scenarios"])
    assert all(scenario["quality_gates"]["latency_p95_match"] for scenario in result.summary["scenarios"])

    summary_path = result.artifacts_dir / "summary.json"
    failures_path = result.artifacts_dir / "failures.json"
    report_path = result.artifacts_dir / "report.md"
    junit_path = result.artifacts_dir / "junit.xml"
    assert summary_path.exists()
    assert failures_path.exists()
    assert report_path.exists()
    assert junit_path.exists()

    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary_payload["exit_code"] == RunnerExitCode.ALL_PASS.value

    failure_payload = json.loads(failures_path.read_text(encoding="utf-8"))
    assert failure_payload == []

    report_text = report_path.read_text(encoding="utf-8")
    assert "run-pass" in report_text
    assert list(expected_scenario_ids)[0] in report_text

    root = ET.fromstring(junit_path.read_text(encoding="utf-8"))
    assert root.attrib["tests"] == str(len(scenarios))
    assert root.attrib["failures"] == "0"


@pytest.mark.asyncio
async def test_run_testbench_local_regression_fixture_passes(tmp_path):
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.REGRESSION,
        env={},
        fixtures_dir=Path("tests/fixtures/testbench"),
        output_root=tmp_path / "artifacts",
        run_id="run-regression-fixture",
    )

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.ALL_PASS
    assert result.summary["scenarios_total"] == 15
    assert result.summary["scenarios_failed"] == 0
    assert result.summary["failure_count"] == 0


@pytest.mark.asyncio
async def test_run_testbench_local_ignores_gemini_env(tmp_path, monkeypatch):
    fixture_dir = _write_fixture(tmp_path, scenarios=_passing_scenarios())
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")

    from backend.l2_gemini import L2Engine

    gemini_calls = 0

    async def _unexpected_gemini_call(self, request, api_key):
        nonlocal gemini_calls
        gemini_calls += 1
        raise AssertionError("Gemini should not be called for local profile")

    monkeypatch.setattr(L2Engine, "_call_gemini", _unexpected_gemini_call)

    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.REGRESSION,
        env={},
        fixtures_dir=fixture_dir,
        output_root=tmp_path / "artifacts",
        run_id="run-no-gemini",
    )

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.ALL_PASS
    assert gemini_calls == 0


@pytest.mark.asyncio
async def test_run_testbench_returns_quality_gate_exit_code_when_expectations_mismatch(tmp_path):
    scenarios = _passing_scenarios()
    scenarios[0]["expected"]["l1_primary_rules"] = ["R2"]
    scenario_id = scenarios[0]["scenario_id"]
    fixture_dir = _write_fixture(tmp_path, scenarios=scenarios)
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.REGRESSION,
        env={},
        fixtures_dir=fixture_dir,
        output_root=tmp_path / "artifacts",
        run_id="run-quality-fail",
    )

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.QUALITY_GATE_FAIL
    assert result.summary["scenarios_failed"] == 1
    assert result.failures[0]["failure_type"] == "quality_gate"
    assert result.failures[0]["scenario_id"] == scenario_id
    assert "l1_rule_match" in result.failures[0]["failed_gates"]


@pytest.mark.asyncio
async def test_run_testbench_returns_quality_gate_exit_code_when_latency_budget_is_exceeded(
    tmp_path, monkeypatch
):
    scenarios = _passing_scenarios()
    scenarios[0]["expected"]["max_p95_ms"] = 5
    scenario_id = scenarios[0]["scenario_id"]
    fixture_dir = _write_fixture(tmp_path, scenarios=scenarios)

    import backend.testbench_runner as runner_module

    original_latency_summary = runner_module._latency_summary
    latency_summary_calls = 0

    def _latency_summary_with_scenario_breach(latencies_ms):
        nonlocal latency_summary_calls
        latency_summary_calls += 1
        if latency_summary_calls == 1:
            return {"p50": 8.0, "p95": 12.0, "p99": 15.0}
        return original_latency_summary(latencies_ms)

    monkeypatch.setattr(runner_module, "_latency_summary", _latency_summary_with_scenario_breach)

    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.REGRESSION,
        env={},
        fixtures_dir=fixture_dir,
        output_root=tmp_path / "artifacts",
        run_id="run-latency-fail",
    )

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.QUALITY_GATE_FAIL
    assert result.summary["scenarios_failed"] == 1
    assert result.failures[0]["failure_type"] == "quality_gate"
    assert result.failures[0]["scenario_id"] == scenario_id
    assert "latency_p95_match" in result.failures[0]["failed_gates"]


@pytest.mark.asyncio
async def test_run_testbench_returns_invalid_fixture_exit_code_for_duplicate_scenarios(tmp_path):
    scenarios = _passing_scenarios()
    scenarios[1]["scenario_id"] = scenarios[0]["scenario_id"]
    fixture_dir = _write_fixture(tmp_path, scenarios=scenarios)
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.REGRESSION,
        env={},
        fixtures_dir=fixture_dir,
        output_root=tmp_path / "artifacts",
        run_id="run-invalid",
    )

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.INVALID_FIXTURE
    assert result.summary["status"] == "failed"
    assert result.failures[0]["failure_type"] == "invalid_fixture"
    assert "duplicate scenario_id" in result.failures[0]["message"]


@pytest.mark.asyncio
async def test_run_testbench_local_regression_applies_fault_injection_and_reports_fallback(tmp_path):
    scenarios = _passing_scenarios()
    scenario = next(item for item in scenarios if item["scenario_id"] == "fraud_direct_rmt_chat")
    scenario["expected"]["l1_primary_rules"] = ["R3", "R4"]
    scenario["expected"]["l2_fallback_action"] = "UNDER_SURVEILLANCE"
    scenario["fault_injection"] = {"type": "gemini_timeout"}
    scenario["events"] = [
        _event(
            event_id="evt_fault_timeout_01",
            actor_id="acct_fault_sender_01",
            target_id="acct_target_fraud_direct_rmt_chat",
            amount=480_000,
            market_avg=2_000,
            chat="send 15k via PayPal and confirm",
            timestamp="2099-01-01T00:00:00Z",
        ),
    ]

    fixture_dir = _write_fixture(tmp_path, scenarios=scenarios)
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.REGRESSION,
        env={},
        fixtures_dir=fixture_dir,
        output_root=tmp_path / "artifacts",
        run_id="run-fault-timeout",
        selected_scenarios=["fraud_direct_rmt_chat"],
    )

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.ALL_PASS
    assert result.failures == []
    assert result.summary["scenarios_total"] == 1

    scenario_summary = result.summary["scenarios"][0]
    assert scenario_summary["scenario_id"] == "fraud_direct_rmt_chat"
    assert scenario_summary["fault_injection"] == {"type": "gemini_timeout"}
    assert scenario_summary["fault_injection_applied"] is True
    assert scenario_summary["quality_gates"]["fault_injection_match"] is True
    assert (
        "Local fallback: API error: Gemini API took too long"
        in scenario_summary["analysis_reasoning"]
    )
    report_text = (result.artifacts_dir / "report.md").read_text(encoding="utf-8")
    assert "fault=gemini_timeout" in report_text


@pytest.mark.asyncio
async def test_run_testbench_local_smoke_ignores_fault_injection_metadata(tmp_path):
    scenarios = _passing_scenarios()
    scenario = next(item for item in scenarios if item["scenario_id"] == "fraud_direct_rmt_chat")
    scenario["expected"]["l1_primary_rules"] = ["R3", "R4"]
    scenario["expected"]["l2_fallback_action"] = "UNDER_SURVEILLANCE"
    scenario["fault_injection"] = {"type": "gemini_timeout"}
    scenario["events"] = [
        _event(
            event_id="evt_fault_smoke_01",
            actor_id="acct_fault_sender_01",
            target_id="acct_target_fraud_direct_rmt_chat",
            amount=480_000,
            market_avg=2_000,
            chat="send 15k via PayPal and confirm",
            timestamp="2099-01-01T00:00:00Z",
        ),
    ]

    fixture_dir = _write_fixture(tmp_path, scenarios=scenarios)
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.SMOKE,
        env={},
        fixtures_dir=fixture_dir,
        output_root=tmp_path / "artifacts",
        run_id="run-fault-smoke",
        selected_scenarios=["fraud_direct_rmt_chat"],
    )

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.ALL_PASS
    scenario_summary = result.summary["scenarios"][0]
    assert scenario_summary["fault_injection"] == {"type": "gemini_timeout"}
    assert scenario_summary["fault_injection_applied"] is False
    assert "fault_injection_match" not in scenario_summary["quality_gates"]
    assert "Local fallback: local testbench profile" in scenario_summary["analysis_reasoning"]
    report_text = (result.artifacts_dir / "report.md").read_text(encoding="utf-8")
    assert "fault=gemini_timeout" not in report_text


def test_select_scenarios_smoke_mode_returns_default_four(tmp_path):
    """Smoke mode with no explicit selection should return exactly 4 default scenarios."""
    fixture_dir = Path("tests/fixtures/testbench")
    dataset = load_testbench_fixture(fixture_dir)

    selected = _select_scenarios(dataset, selected=[], mode=TestbenchMode.SMOKE)

    ids = [s.scenario_id for s in selected]
    assert ids == [
        "fraud_smurfing_fan_in",
        "fraud_direct_rmt_chat",
        "legit_new_season_rewards",
        "legit_friend_gifts_low_value",
    ]
    assert len(selected) == 4


def test_select_scenarios_smoke_mode_raises_on_missing_default():
    """Smoke mode should raise ValueError if a default scenario ID is missing from the dataset."""
    from backend.testbench_runner import ScenarioFixture, TestbenchDataset
    from pydantic import ValidationError

    scenarios = _passing_scenarios()
    # Remove one required smoke scenario
    scenarios = [s for s in scenarios if s["scenario_id"] != "fraud_smurfing_fan_in"]

    with pytest.raises(ValidationError, match="missing required scenario categories"):
        TestbenchDataset(
            dataset="test",
            version="v0",
            generated_at="2026-01-01T00:00:00Z",
            seed=0,
            scenario_count=len(scenarios),
            event_count=sum(len(s["events"]) for s in scenarios),
            scenarios=scenarios,
        )


def test_testbench_dataset_requires_all_scenarios():
    """The TestbenchDataset model should enforce that all REQUIRED_SCENARIOS are present."""
    from backend.testbench_runner import TestbenchDataset, REQUIRED_SCENARIOS
    from pydantic import ValidationError

    scenarios = _passing_scenarios()

    # Valid
    dataset = TestbenchDataset(
        dataset="test",
        version="v0",
        generated_at="2026-01-01T00:00:00Z",
        seed=0,
        scenario_count=len(scenarios),
        event_count=len(scenarios),
        scenarios=scenarios,
    )
    assert len(dataset.scenarios) == len(REQUIRED_SCENARIOS)

    # Missing a required scenario
    invalid_scenarios = scenarios[:-1]
    with pytest.raises(ValidationError, match="missing required scenario categories"):
        TestbenchDataset(
            dataset="test",
            version="v0",
            generated_at="2026-01-01T00:00:00Z",
            seed=0,
            scenario_count=len(invalid_scenarios),
            event_count=len(invalid_scenarios),
            scenarios=invalid_scenarios,
        )


def test_load_runner_config_soak_iterations_can_be_overridden(tmp_path):
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.SOAK,
        env={"SUSANOH_TESTBENCH_SOAK_ITERATIONS": "3"},
        fixtures_dir=tmp_path / "fixtures",
        output_root=tmp_path / "artifacts",
        run_id="run-soak-config",
    )

    assert config.mode is TestbenchMode.SOAK
    assert config.soak_iterations == 3


@pytest.mark.asyncio
async def test_run_testbench_local_soak_replays_iterations_and_aggregates_metrics(tmp_path):
    scenarios = _passing_scenarios()
    fixture_dir = _write_fixture(tmp_path, scenarios=scenarios)
    output_root = tmp_path / "artifacts"
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.SOAK,
        env={"SUSANOH_TESTBENCH_SOAK_ITERATIONS": "2"},
        fixtures_dir=fixture_dir,
        output_root=output_root,
        run_id="run-soak-pass",
        selected_scenarios=["fraud_smurfing_fan_in"],
    )

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.ALL_PASS
    assert result.summary["mode"] == "soak"
    assert result.summary["scenarios_total"] == 2
    assert result.summary["soak"]["iterations_planned"] == 2
    assert result.summary["soak"]["state_drift_count"] == 0
    assert result.summary["soak"]["event_replay_count"] == 2
    assert "peak_rss_mb" in result.summary["soak"]
    assert "peak_rss_growth_mb" in result.summary["soak"]
    assert len(result.summary["scenarios"]) == 1

    scenario = result.summary["scenarios"][0]
    assert scenario["scenario_id"] == "fraud_smurfing_fan_in"
    assert scenario["iterations"] == 2
    assert scenario["passed_iterations"] == 2
    assert scenario["failed_iterations"] == 0
    assert scenario["state_drift_count"] == 0
    assert scenario["request_count"] > 0
    assert scenario["iteration_latency_ms"]["first_p95"] >= 0.0
    assert scenario["iteration_latency_ms"]["last_p95"] >= 0.0


@pytest.mark.asyncio
async def test_run_testbench_local_soak_detects_state_drift(tmp_path, monkeypatch):
    scenarios = _passing_scenarios()
    fixture_dir = _write_fixture(tmp_path, scenarios=scenarios)
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.SOAK,
        env={"SUSANOH_TESTBENCH_SOAK_ITERATIONS": "2"},
        fixtures_dir=fixture_dir,
        output_root=tmp_path / "artifacts",
        run_id="run-soak-drift",
        selected_scenarios=["fraud_smurfing_fan_in"],
    )

    scenario_calls = 0

    async def _fake_run_scenario(*, client, config, scenario, auth_headers, event_headers):
        del client, config, auth_headers, event_headers
        nonlocal scenario_calls
        scenario_calls += 1
        observed_state_path = (
            ["RESTRICTED_WITHDRAWAL", "NORMAL"]
            if scenario_calls == 1
            else ["RESTRICTED_WITHDRAWAL", "UNDER_SURVEILLANCE"]
        )
        observed_l2_action = "NORMAL" if scenario_calls == 1 else "UNDER_SURVEILLANCE"
        return {
            "scenario": {
                "scenario_id": scenario.scenario_id,
                "title": scenario.title,
                "risk_tier": scenario.risk_tier,
                "target_id": f"{scenario.expected.target_id}__{scenario_calls}",
                "passed": True,
                "failed_gates": [],
                "expected_l1_rules": [],
                "observed_l1_rules": [],
                "expected_state_path": ["NORMAL"],
                "observed_state_path": observed_state_path,
                "expected_l2_actions": ["NORMAL", "UNDER_SURVEILLANCE"],
                "max_p95_ms": scenario.expected.max_p95_ms,
                "observed_l2_action": observed_l2_action,
                "final_state": observed_state_path[-1],
                "fault_injection": None,
                "fault_injection_applied": False,
                "analysis_reasoning": None,
                "request_count": 1,
                "latency_ms": {"p50": 8.0, "p95": 9.0, "p99": 10.0},
                "quality_gates": {
                    "l1_rule_match": True,
                    "state_path_match": True,
                    "l2_action_range_match": True,
                    "api_availability": True,
                    "latency_p95_match": True,
                },
            },
            "failures": [],
            "latencies_ms": [9.0],
        }

    monkeypatch.setattr("backend.testbench_runner._run_scenario", _fake_run_scenario)

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.ALL_PASS
    assert result.summary["soak"]["iterations_planned"] == 2
    assert result.summary["soak"]["state_drift_count"] == 1
    assert result.summary["scenarios"][0]["state_drift_count"] == 1


@pytest.mark.asyncio
async def test_run_testbench_local_soak_paces_replay_against_target_tps(tmp_path, monkeypatch):
    scenarios = _passing_scenarios()
    fixture_dir = _write_fixture(tmp_path, scenarios=scenarios)
    config = load_runner_config(
        profile=RunnerProfile.LOCAL,
        mode=TestbenchMode.SOAK,
        env={"SUSANOH_TESTBENCH_SOAK_ITERATIONS": "2"},
        fixtures_dir=fixture_dir,
        output_root=tmp_path / "artifacts",
        run_id="run-soak-paced",
        selected_scenarios=["fraud_smurfing_fan_in"],
    )

    pace_calls: list[tuple[int, float]] = []

    async def _fake_pace_soak_replay(*, replayed_event_count, started_at, target_tps):
        del started_at
        pace_calls.append((replayed_event_count, target_tps))

    monkeypatch.setattr("backend.testbench_runner._pace_soak_replay", _fake_pace_soak_replay)

    result = await run_testbench(config)

    assert result.exit_code is RunnerExitCode.ALL_PASS
    assert pace_calls == [(1, 40.0), (2, 40.0)]

import json
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.l1_screening import L1Engine
from backend.models import GameEventLog
from scripts.generate_testbench_dataset import EventFactory, _build_rule_boundaries, _build_scenarios


BOUNDARY_FIXTURE_PATH = Path("tests/fixtures/testbench/rule_boundaries.json")
EXPECTED_RULE_VARIANTS = {
    "R1": {"just_below", "at_threshold", "just_above"},
    "R2": {"just_below", "at_threshold", "just_above"},
    "R3": {"just_below", "at_threshold", "just_above"},
    "R4": {"just_below", "at_threshold", "just_above"},
}
FIXTURE_SEED = 20260305
FIXTURE_STARTED_AT = datetime(2099, 1, 1, 0, 0, tzinfo=UTC)


def _load_boundary_fixture() -> dict:
    return json.loads(BOUNDARY_FIXTURE_PATH.read_text(encoding="utf-8"))


def _generate_boundary_cases() -> list[dict]:
    factory = EventFactory(started_at=FIXTURE_STARTED_AT)
    _build_scenarios(factory=factory, rng=random.Random(FIXTURE_SEED))
    return _build_rule_boundaries(factory=factory)


def test_rule_boundary_fixture_covers_all_rules_and_variants():
    payload = _load_boundary_fixture()

    assert payload["dataset"] == "susanoh-operational-testbench-boundaries"
    assert payload["dataset_version"].startswith("v")
    assert payload["changelog"][0]["version"] == payload["dataset_version"]
    assert payload["case_count"] == 12

    seen: dict[str, set[str]] = {}
    for case in payload["cases"]:
        seen.setdefault(case["rule_id"], set()).add(case["variant"])

    assert seen == EXPECTED_RULE_VARIANTS


def test_rule_boundary_fixture_matches_generator_output():
    payload = _load_boundary_fixture()

    assert payload["seed"] == FIXTURE_SEED
    assert payload["case_count"] == len(payload["cases"])
    assert payload["cases"] == _generate_boundary_cases()


@pytest.mark.asyncio
async def test_rule_boundary_fixture_matches_l1_thresholds():
    payload = _load_boundary_fixture()

    for case in payload["cases"]:
        engine = L1Engine()
        result = None
        for raw_event in case["events"]:
            result = await engine.screen(GameEventLog.model_validate(raw_event))

        assert result is not None
        assert result.triggered_rules == case["expected_triggered_rules"]
        assert result.screened is case["expected_screened"]
        assert result.needs_l2 is case["expected_needs_l2"]

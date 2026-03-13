import json
from pathlib import Path

import pytest

from backend.l1_screening import L1Engine
from backend.models import GameEventLog


BOUNDARY_FIXTURE_PATH = Path("tests/fixtures/testbench/rule_boundaries.json")
EXPECTED_RULE_VARIANTS = {
    "R1": {"just_below", "at_threshold", "just_above"},
    "R2": {"just_below", "at_threshold", "just_above"},
    "R3": {"just_below", "at_threshold", "just_above"},
    "R4": {"just_below", "at_threshold", "just_above"},
}


def _load_boundary_fixture() -> dict:
    return json.loads(BOUNDARY_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_rule_boundary_fixture_covers_all_rules_and_variants():
    payload = _load_boundary_fixture()

    assert payload["dataset"] == "susanoh-operational-testbench-boundaries"
    assert payload["case_count"] == 12

    seen: dict[str, set[str]] = {}
    for case in payload["cases"]:
        seen.setdefault(case["rule_id"], set()).add(case["variant"])

    assert seen == EXPECTED_RULE_VARIANTS


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

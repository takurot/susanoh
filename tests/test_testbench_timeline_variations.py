import json
import random
from datetime import UTC, datetime
from pathlib import Path

from scripts.generate_testbench_dataset import (
    EventFactory,
    _build_scenarios,
    _build_timeline_variations,
)


TIMELINE_FIXTURE_PATH = Path("tests/fixtures/testbench/timeline_variations.json")
EXPECTED_VARIATION_TYPES = {
    "out_of_order_arrival",
    "delayed_arrival",
    "duplicate_delivery",
}
FIXTURE_SEED = 20260305
FIXTURE_STARTED_AT = datetime(2099, 1, 1, 0, 0, tzinfo=UTC)


def _load_timeline_fixture() -> dict:
    return json.loads(TIMELINE_FIXTURE_PATH.read_text(encoding="utf-8"))


def _generate_timeline_cases() -> list[dict]:
    factory = EventFactory(started_at=FIXTURE_STARTED_AT)
    scenarios = _build_scenarios(factory=factory, rng=random.Random(FIXTURE_SEED))
    return _build_timeline_variations(scenarios)


def test_timeline_variation_fixture_covers_expected_variation_types():
    payload = _load_timeline_fixture()

    assert payload["dataset"] == "susanoh-operational-testbench-timeline-variations"
    assert payload["case_count"] == 3

    variation_types = {case["variation_type"] for case in payload["cases"]}
    assert variation_types == EXPECTED_VARIATION_TYPES


def test_timeline_variation_fixture_matches_generator_output():
    payload = _load_timeline_fixture()

    assert payload["seed"] == FIXTURE_SEED
    assert payload["case_count"] == len(payload["cases"])
    assert payload["cases"] == _generate_timeline_cases()


def test_timeline_variation_fixture_preserves_canonical_targets_and_flags_changed_arrival():
    payload = _load_timeline_fixture()

    for case in payload["cases"]:
        assert case["canonical_event_ids"]
        assert case["arrival_event_ids"]
        assert len(case["events"]) == len(case["arrival_event_ids"])
        assert [event["event_id"] for event in case["events"]] == case["arrival_event_ids"]
        assert any(event["target_id"] == case["target_id"] for event in case["events"])

        if case["variation_type"] == "duplicate_delivery":
            assert len(case["arrival_event_ids"]) > len(set(case["arrival_event_ids"]))
            assert case["duplicate_event_ids"]
        else:
            assert len(case["arrival_event_ids"]) == len(set(case["arrival_event_ids"]))
            assert case["arrival_event_ids"] != case["canonical_event_ids"]
            assert case["delayed_event_ids"]

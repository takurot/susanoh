from collections import Counter
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


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_timeline_variation_fixture_covers_expected_variation_types():
    payload = _load_timeline_fixture()

    assert payload["dataset"] == "susanoh-operational-testbench-timeline-variations"
    assert payload["dataset_version"].startswith("v")
    assert payload["changelog"][0]["version"] == payload["dataset_version"]
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
        canonical_counts = Counter(case["canonical_event_ids"])
        arrival_counts = Counter(case["arrival_event_ids"])
        timestamps = [_parse_timestamp(event["timestamp"]) for event in case["events"]]

        assert case["canonical_event_ids"]
        assert case["arrival_event_ids"]
        assert len(case["events"]) == len(case["arrival_event_ids"])
        assert [event["event_id"] for event in case["events"]] == case["arrival_event_ids"]
        assert any(event["target_id"] == case["target_id"] for event in case["events"])
        assert set(case["canonical_event_ids"]).issubset(set(case["arrival_event_ids"]))

        if case["variation_type"] == "duplicate_delivery":
            assert len(case["arrival_event_ids"]) > len(set(case["arrival_event_ids"]))
            assert case["duplicate_event_ids"]
            expected_counts = canonical_counts.copy()
            for event_id in case["duplicate_event_ids"]:
                expected_counts[event_id] += 1
            assert arrival_counts == expected_counts
            assert all(arrival_counts[event_id] == canonical_counts[event_id] + 1 for event_id in case["duplicate_event_ids"])
            assert timestamps == sorted(timestamps)
        else:
            assert len(case["arrival_event_ids"]) == len(set(case["arrival_event_ids"]))
            assert case["arrival_event_ids"] != case["canonical_event_ids"]
            assert case["delayed_event_ids"]
            assert Counter(case["canonical_event_ids"]) == arrival_counts
            assert timestamps != sorted(timestamps)

            delayed_positions = [
                case["arrival_event_ids"].index(event_id)
                for event_id in case["delayed_event_ids"]
            ]
            canonical_positions = [
                case["canonical_event_ids"].index(event_id)
                for event_id in case["delayed_event_ids"]
            ]
            assert delayed_positions != canonical_positions

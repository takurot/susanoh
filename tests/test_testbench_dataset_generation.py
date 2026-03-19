import json
import random
from datetime import UTC, datetime
from pathlib import Path

from scripts.generate_testbench_dataset import (
    EventFactory,
    _build_rule_boundaries,
    _build_scenarios,
    _build_timeline_variations,
    _write_outputs,
)


FIXTURE_DIR = Path("tests/fixtures/testbench")
FIXTURE_SEED = 20260305
FIXTURE_STARTED_AT = datetime(2099, 1, 1, 0, 0, tzinfo=UTC)


def _generate_fixture(output_dir: Path) -> Path:
    factory = EventFactory(started_at=FIXTURE_STARTED_AT)
    scenarios = _build_scenarios(factory=factory, rng=random.Random(FIXTURE_SEED))
    rule_boundaries = _build_rule_boundaries(factory=factory)
    timeline_variations = _build_timeline_variations(scenarios)
    _write_outputs(
        output_dir,
        seed=FIXTURE_SEED,
        scenarios=scenarios,
        rule_boundaries=rule_boundaries,
        timeline_variations=timeline_variations,
    )
    return output_dir


def test_canonical_testbench_fixture_matches_generator_output(tmp_path):
    generated_dir = _generate_fixture(tmp_path / "generated")

    expected_manifest = json.loads((FIXTURE_DIR / "scenarios.json").read_text(encoding="utf-8"))
    actual_manifest = json.loads((generated_dir / "scenarios.json").read_text(encoding="utf-8"))
    actual_manifest["generated_at"] = expected_manifest["generated_at"]

    assert actual_manifest == expected_manifest
    assert (generated_dir / "events.jsonl").read_text(encoding="utf-8") == (
        FIXTURE_DIR / "events.jsonl"
    ).read_text(encoding="utf-8")


def test_canonical_testbench_readme_matches_generator_output(tmp_path):
    generated_dir = _generate_fixture(tmp_path / "generated")

    assert (generated_dir / "README.md").read_text(encoding="utf-8") == (
        FIXTURE_DIR / "README.md"
    ).read_text(encoding="utf-8")

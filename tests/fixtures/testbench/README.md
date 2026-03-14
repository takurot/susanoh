# Operational Testbench Dataset (Seed)

- Dataset version: `v0.3.0`
- Seed: `20260305`
- Scenario count: `15`
- Event count: `125`
- Rule boundary cases: `12`
- Timeline variation cases: `3`

## Risk-tier distribution
- `high`: 8 scenarios
- `low`: 4 scenarios
- `medium`: 3 scenarios

## Files
- `scenarios.json`: scenario-level manifest, expectations (including `max_p95_ms`), and full event sequences.
- `events.jsonl`: flattened stream for replay/soak test ingestion.
- `rule_boundaries.json`: R1-R4 threshold boundary cases (`just_below`, `at_threshold`, `just_above`) validated against `L1Engine`.
- `timeline_variations.json`: out-of-order arrival / delayed arrival / duplicate delivery replay cases derived from canonical scenarios.

## Regression Fault Injection
- `fraud_direct_rmt_chat`: `gemini_timeout` (applies only to local regression mode)
- `fraud_layering_chain_exit`: `gemini_5xx` (applies only to local regression mode)

## Rule Boundaries
- `R1`: `just_below`, `at_threshold`, `just_above`
- `R2`: `just_below`, `at_threshold`, `just_above`
- `R3`: `just_below`, `at_threshold`, `just_above`
- `R4`: `just_below`, `at_threshold`, `just_above`

## Timeline Variations
- `out_of_order_arrival`: `timeline_out_of_order_layering_chain` -> `fraud_layering_chain_exit`
- `delayed_arrival`: `timeline_delayed_flash_sale_peak` -> `gray_flash_sale_peak`
- `duplicate_delivery`: `timeline_duplicate_friend_gifts` -> `legit_friend_gifts_low_value`

## Regeneration
```bash
python3 scripts/generate_testbench_dataset.py --seed 20260305 --output tests/fixtures/testbench
```

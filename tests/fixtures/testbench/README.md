# Operational Testbench Dataset (Seed)

- Dataset version: `v0.1.1`
- Seed: `20260305`
- Scenario count: `15`
- Event count: `125`

## Risk-tier distribution
- `high`: 8 scenarios
- `low`: 4 scenarios
- `medium`: 3 scenarios

## Files
- `scenarios.json`: scenario-level manifest, expectations (including `max_p95_ms`), and full event sequences.
- `events.jsonl`: flattened stream for replay/soak test ingestion.

## Regression Fault Injection
- `fraud_direct_rmt_chat`: `gemini_timeout` (applies only to local regression mode)
- `fraud_layering_chain_exit`: `gemini_5xx` (applies only to local regression mode)

## Regeneration
```bash
python3 scripts/generate_testbench_dataset.py --seed 20260305 --output tests/fixtures/testbench
```

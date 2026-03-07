# Operational Testbench Policy (Phase 1.6.1)

Phase 1.6.1 で定義した運用テストベンチの品質ポリシーをまとめる。  
実装上のソースオブトゥルースは `backend/testbench_policy.py`。

## SLO

| Mode | Min Success Rate | Max P95 Latency | Max Failures |
|---|---:|---:|---:|
| Smoke | 100% | 1200 ms | 0 |
| Regression | 99% | 1800 ms | 2 |
| Soak | 99.5% | 2200 ms | 8 |
| Live | 95% | 5000 ms | 1 |

## Load Targets

| Mode | Target TPS | Duration | Max Error Rate | Machine Profile |
|---|---:|---:|---:|---|
| Regression | 25.0 | 30 min | 1.0% | 4 vCPU / 8 GB RAM / NVMe SSD / 1 Gbps network |
| Soak | 40.0 | 240 min | 0.5% | 8 vCPU / 16 GB RAM / NVMe SSD / 1 Gbps network |

## Required Quality Gates

- `L1ルール一致`
- `状態遷移一致`
- `L2裁定の範囲整合`
- `API可用性`
- `Latency p95 budget 一致`

上記5項目はいずれも必須。1つでも欠けた場合は品質ゲート不合格とする。  
`Latency p95 budget 一致` は各シナリオの `expected.max_p95_ms` に対して評価する。

## Failure Policy

- 即失敗（再試行なし）:
  - `quality_gate`
  - `invalid_fixture`
- 再試行対象:
  - `infra_dependency`
  - 最大再試行回数: 2
- CIブロック条件:
  - `quality_gate`
  - `invalid_fixture`
  - `infra_dependency_after_retry`
- 運用通知条件:
  - `infra_dependency_after_retry`
  - `live_mode_failure`

## Validation

`tests/test_testbench_policy.py` で以下を固定化している。

- モード別SLOの存在
- `Regression` / `Soak` の負荷目標
- 5つの必須品質ゲート
- 即失敗/再試行後失敗の判定
- CIブロック条件と運用通知条件

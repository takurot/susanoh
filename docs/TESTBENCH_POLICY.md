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

## Scheduled Operations

- PRごとの軽量モードは `.github/workflows/ci.yml` の `Backend Testbench (Smoke)` で実行し、`junit.xml` をチェックへ公開、artifact を7日保持する。
- 日次 Regression は `.github/workflows/testbench-regression.yml` で毎日 `03:00 JST` (`18:00 UTC`) に実行し、`local` プロファイルの決定論的 L2 と scenario-level fault injection で flakiness とコストを抑えつつ、Gemini fallback の健全性も継続確認する。
- 縮小した `Regression-Live` は `.github/workflows/testbench-regression-live.yml` で毎週月曜 `05:00 JST` (`20:00 UTC` 日曜) に staging secrets 利用時のみ実行し、staging が API key 必須構成なら `SUSANOH_TESTBENCH_STAGING_API_KEY` も前提に含めて実 API 健全性を別レーンで確認する。

# 実装ロードマップ：Susanoh (Production Roadmap)

## 概要

本ドキュメントでは、Susanohを現在のプロトタイプ（インメモリ・シングルプロセス）からプロダクションレディなミドルウェアへ昇華させるための段階的実装計画を定義する。
各フェーズは、前フェーズの安定稼働を前提として進行する。

---

## Phase 1: Foundation for Production (基盤強化)

プロトタイプから、永続化・分散対応可能なアーキテクチャへの移行を最優先とする。

### 1.1 永続化層の実装
- [x] **Database**: PostgreSQLの導入
  - `User`, `EventLog`, `AnalysisResult`, `AuditLog` テーブルのスキーマ設計 (SQLAlchemy / Alembic)
  - 既存のインメモリデータのDB移行ロジック
  - Status: プロトタイプ実装済み（`DATABASE_URL` 設定時にSQLAlchemyでスキーマ作成 + スナップショット永続化、2026-02-22）
- [x] **State Store**: Redisの導入
  - ステートマシン状態のRedis管理 (実装済み, 2026-02-22)
  - L1スライディングウィンドウデータのRedis移行 (Sorted Sets活用, 2026-02-22)
  - Async/Await化による分散対応への基盤構築 (2026-02-22)

### 1.2 認証・認可基盤
- [x] **Service Authentication**: ゲームサーバー向けAPI Key認証 (`X-API-KEY`) の実装と管理機能（Middleware実装）
  - Status: プロトタイプ実装済み（`SUSANOH_API_KEYS` 設定時に `/api/v1/*` へ適用、2026-02-22）
- [x] **User Authentication**: ダッシュボード向けJWT認証 (OAuth2 Password Bearer)
- [x] **RBAC**: `Admin`, `Operator`, `Viewer` ロールの実装

### 1.3 非同期処理の分離
- [x] **Task Queue**: arq の導入 (2026-02-22)
- [x] L2 Gemini分析処理をWebサーバープロセスから分離し、ワーカープロセスへ委譲 (2026-02-22)
- [x] 分析結果のWebフック通知またはポーリング用DB格納 (2026-02-28: Redisポーリングで実装)

### 1.4 ステートマシン機能補完
- [x] **自動復旧ロジック**: L2分析結果が「Low Risk」の場合、自動的に `RESTRICTED_WITHDRAWAL` から `NORMAL` へ戻す処理の実装
  - Status: プロトタイプ実装済み（2026-02-22）

---

## Phase 1.5: Testing & Quality Assurance (テスト・品質保証の強化)

プロダクション移行に向け、テストの自動化とカバレッジの向上を図る。

### 1.5.1 テスト基盤の整備
- [x] **Coverage Analysis**: `pytest-cov` を導入し、バックエンドのカバレッジを可視化。
- [x] **Frontend Testing**: Playwright を導入し、ダッシュボードの主要導線の E2E テストを自動化。

### 1.5.2 信頼性の検証
- [x] **Concurrency Testing**: 大量イベント同時受信時、およびステート遷移時の Race Condition 検証。
- [x] **Fault Injection**: Redis/Gemini API などの外部依存先が「スローレスポンス」や「瞬断」した際の耐障害性テストの拡充。
- [x] **Live API Verification**: ステージング環境における Gemini API との定期的疎通確認テスト。 (2026-03-05: `backend.live_api_verification` + `scripts/run_live_api_verification.sh` + `tests/test_live_api.py::test_staging_live_api_verification`)

---

## Phase 1.6: Operational Test Bench (運用形式テストベンチ)

POC運用に近い品質検証を可能にするため、定期実行・失敗検知・証跡保存を備えたテストベンチを整備する。

### 1.6.1 目的・品質ゲートの明確化
- [x] **SLO定義**: `Smoke` / `Regression` / `Soak` / `Live` の各モードで、成功率・許容レイテンシ・許容失敗件数を数値化。 (2026-03-05: `backend/testbench_policy.py`, `docs/TESTBENCH_POLICY.md`)
- [x] **負荷目標定義**: `Soak` と `Regression` の目標TPS・継続時間・許容エラー率を明示し、実行マシンスペック前提を固定化。 (2026-03-05: `backend/testbench_policy.py`, `docs/TESTBENCH_POLICY.md`)
- [x] **判定ゲート定義**: `L1ルール一致`, `状態遷移一致`, `L2裁定の範囲整合`, `API可用性`, `Latency p95 budget 一致` を必須ゲートとして定義。 (2026-03-07: `backend/testbench_policy.py`, `backend/testbench_runner.py`, `docs/TESTBENCH_POLICY.md`)
- [x] **実行失敗時ポリシー**: `即失敗` と `再試行後失敗` を分け、CIブロック条件と運用通知条件を明文化。 (2026-03-05: `backend/testbench_policy.py`, `tests/test_testbench_policy.py`)

### 1.6.2 テストベンチ実行基盤
- [x] **Runner設計**: シナリオ読込 -> API送信 -> 結果収集 -> 判定 -> レポート出力のパイプラインを実装。 (2026-03-06: `backend/testbench_runner.py`, `tests/test_testbench_runner.py`)
  - 対応入力: `tests/fixtures/testbench/scenarios.json` と `events.jsonl`
  - 対応出力: `artifacts/testbench/<run_id>/summary.json` + `failures.json` + `report.md` + `junit.xml`
- [x] **CI可視化連携**: `junit.xml` を GitHub Actions などで取り込み、失敗ケースをPR上でアノテーション表示可能にする。 (2026-03-06 / 2026-03-09: `.github/workflows/ci.yml`)
- [x] **実行プロファイル**: `local`, `staging` の2系統を切替可能化（base URL, auth, timeout, retry）。 (2026-03-06: `backend/testbench_runner.py`)
- [x] **再実行耐性**: 同一シナリオIDで複数回走らせても衝突しないよう、event_id suffix と target namespace をラン毎に隔離。 (2026-03-06: `backend/testbench_runner.py`, `tests/test_testbench_runner.py`)
- [x] **終了コード設計**: `0=all pass`, `1=quality gate fail`, `2=infra/dependency fail`, `3=invalid fixture` を固定化。 (2026-03-06: `backend/testbench_runner.py`, `tests/test_testbench_runner.py`)

### 1.6.3 実行モードとスケジュール運用
- [x] **Smoke (PRごと)**: 高リスク不正2件 + 正常系2件を5-10分で完走する軽量モードを追加。 (2026-03-06: `_select_scenarios` smoke defaults + `.github/workflows/ci.yml` testbench job)
- [x] **Regression (日次)**: 全シナリオ + fault injection を20-40分で実行し、日次サマリを保存。 (2026-03-10: `.github/workflows/testbench-regression.yml`, `.github/workflows/testbench-regression-live.yml`, `backend/testbench_runner.py`, `tests/fixtures/testbench/scenarios.json`)
  - 既定は決定論的ローカルL2と scenario-level fault injection で実行し、コストと flakiness を抑制。
  - 実APIを叩く `Regression-Live` は件数を絞って別スケジュール（例: 週次/夜間）で実行。
- [x] **Soak (週次)**: 長時間リプレイで状態不整合と遅延悪化を継続観測し、メモリ増分を telemetry として採取する。 (2026-03-11: `.github/workflows/testbench-soak.yml`, `backend/testbench_runner.py`, `tests/test_testbench_runner.py`, `docs/TESTBENCH_POLICY.md`)
  - Runner 内ループで namespaced scenario replay を反復し、per-scenario の `state_drift_count` と iteration latency を artifact に集約する。
  - Soak summary に `peak_rss_mb` / `peak_rss_growth_mb` を含め、長時間実行時のメモリ増分を観測可能化する。GitHub-hosted の `ubuntu-latest` 実行は固定スペック保証がないため、週次 lane は fixed-capacity gate ではなく best-effort telemetry として扱う。
  - `SUSANOH_TESTBENCH_SOAK_ITERATIONS` repository variable または `--soak-iterations` で replay 回数を調整可能。無効な repository variable は workflow 側で無視し、既定の soak plan にフォールバックする。
- [x] **Live Verification (定期)**: `backend.live_api_verification` と連動し、外部依存の生存確認を同一レポートへ集約。 (2026-03-12: `backend/testbench_runner.py`, `tests/test_testbench_runner.py`, `docs/TESTBENCH_POLICY.md`, `README.md`)

### 1.6.4 不正シナリオデータ戦略（多彩パターン検証）
- [x] **Seedデータ生成 (v0.1.0)**: 15シナリオ/125イベントの初期fixtureを作成。 (2026-03-05)
  - 生成スクリプト: `scripts/generate_testbench_dataset.py`
  - 生成物: `tests/fixtures/testbench/scenarios.json`, `tests/fixtures/testbench/events.jsonl`
  - 分布: high=8, medium=3, low=4
  - Current fixture version: `v0.2.0` (2026-03-13: rule boundary dataset refresh + expected-value validation)
- [x] **パターンカタログ固定**: 次のカテゴリを最小検証セットとして固定し、欠損時はCI failにする。 (2026-03-07 / 2026-03-13: `backend/testbench_runner.py`, `tests/test_testbench_runner.py`, `tests/fixtures/testbench/scenarios.json`)
  - 高リスク不正: `smurfing fan-in`, `direct RMT chat`, `layering chain`, `bot micro-burst`, `market price abuse`, `cross-cluster bridge`, `cashout prep`, `sleeper activation`
  - 誤検知ストレス: `guild treasury collection`, `flash-sale peak`, `streamer donation spike`
  - 正常ベースライン: `season rewards`, `small friend gifts`, `whale purchase fair-price`, `tournament payout`
- [x] **期待値メタデータ拡張**: 各シナリオに `expected_l1`, `expected_state_path`, `expected_l2_action_range`, `max_p95_ms` を保持。 (2026-03-07: `backend/testbench_runner.py`, `scripts/generate_testbench_dataset.py`, `tests/fixtures/testbench/scenarios.json`)
- [x] **閾値境界データ追加**: R1/R2/R3/R4 それぞれで `just_below`, `at_threshold`, `just_above` ケースを追加。 (2026-03-13: `scripts/generate_testbench_dataset.py`, `tests/fixtures/testbench/rule_boundaries.json`, `tests/test_testbench_rule_boundaries.py`)
- [x] **時系列ゆらぎデータ**: イベント順序入替・遅延到着・重複送信を再現するデータセットを追加。 (2026-03-13: `scripts/generate_testbench_dataset.py`, `tests/fixtures/testbench/timeline_variations.json`, `tests/test_testbench_timeline_variations.py`)
- [x] **長期運用用データ版管理**: `dataset_version` と changelog を導入し、ベンチ結果をデータ版で比較可能化。 (2026-03-14: `backend/testbench_runner.py`, `scripts/generate_testbench_dataset.py`, `tests/fixtures/testbench/*`, `tests/test_testbench_runner.py`)

### 1.6.5 Fault Injection / 可観測性タスク
- [ ] **依存障害シナリオ**: Redis timeout / Gemini 429・5xx / DB接続劣化をベンチシナリオとして実装。
- [ ] **LLM固有障害シナリオ**: malformed JSON（スキーマ崩れ）/ context length exceeded / token limit 超過時のフォールバック挙動を検証。
- [ ] **メトリクス収集**: シナリオ単位で `request_count`, `error_rate`, `p50/p95/p99`, `state_drift_count` を記録。
- [ ] **失敗時証跡**: 失敗イベントの request/response, triggered_rules, state snapshot を自動保存。
- [ ] **差分比較レポート**: 前回runとの差分（失敗増減、遅延悪化、誤検知率変化）を Markdown で出力。

### 1.6.6 受け入れ基準 (POC運用)
- [ ] **機能基準**: 15シナリオ全件をRunnerで再生し、期待ゲート判定を自動実施できる。
- [ ] **安定性基準**: 同条件3連続実行で判定ぶれが 0 件である。
- [ ] **運用基準**: 定期実行・失敗通知・レポート保存が手動介入なしで回る。
- [ ] **継続改善基準**: 新規不正パターン追加時、fixture更新 -> ベンチ実行 -> レポート反映が1PRで完了できる。

---

## Phase 2: Infrastructure & DevOps (運用基盤)

安定したデプロイと監視体制を構築し、SLA 99.9%を担保する準備を整える。

### 2.1 コンテナ化とオーケストレーション
- [ ] **Docker**: `Dockerfile` の最適化（Multi-stage build）
- [ ] **Compose**: `docker-compose.yml` によるフルスタック（App, Worker, DB, Redis）起動構成
- [ ] **Kubernetes**: Helmチャートの作成（Deployment, Service, Ingress, HPA）

### 2.2 CI/CDパイプライン
- [ ] **GitHub Actions**:
  - Lint / Type Check / Unit Test の自動化
  - コンテナイメージのビルドとRegistryへのプッシュ
  - ステージング環境への自動デプロイ

### 2.3 可観測性 (Observability)
- [ ] **Monitoring**: Prometheus エクスポーターの実装
- [ ] **Visualization**: Grafana ダッシュボードの構築（RPS, Latency, Error Rate, Queue Depth）
- [ ] **Logging**: 構造化ログ（JSON）の出力と集約

---

## Phase 3: Performance & Scalability (性能向上)

トラフィック増大に対応し、数万イベント/秒を捌くための最適化を行う。

### 3.1 キャッシュ戦略
- [ ] 頻繁にアクセスされるユーザープロファイルのRedisキャッシュ
- [ ] 読み取り専用クエリのDBリードレプリカ分散

### 3.2 負荷試験とチューニング
- [ ] Locust / k6 を用いた負荷試験シナリオの作成
- [ ] ボトルネック特定と改善（DBインデックス最適化、コネクションプーリング調整）
- [ ] オートスケーリング設定の最適化

### 3.3 L2エンジンの高度化
- [ ] Gemini APIのレート制限ハンドリング強化（トークンバケットアルゴリズム）
- [ ] 分析結果のキャッシュ（類似イベントの再分析回避）

### 3.4 L1 Rust Gateway化（高スループット対応）
- **目的**: L1判定のCPU負荷とレイテンシを削減し、イベント処理の上限を引き上げる。
- **設計方針**:
  - 既存の `/api/v1/events` 契約は維持し、クライアント互換性を壊さない。
  - Python FastAPIはAPI Gatewayとして残し、L1判定処理をRustサービスへ委譲する。
  - 切替は段階的に行い、`L1_ENGINE_PROVIDER=python|rust` のフラグでロールバック可能にする。

#### 3.4.1 契約固定と互換テスト基盤
- [ ] `GameEventLog` 入力と `ScreeningResult` 出力のJSON Schemaを固定化。
- [ ] Python版L1を基準に、同一入力で同一判定結果を比較するゴールデンテストを作成。

#### 3.4.2 Rust L1サービス実装
- [ ] 新規 `l1-rust/`（仮称）を作成し、HTTPまたはgRPCで判定APIを提供。
- [ ] 実装対象:
  - [ ] R1〜R4 ルール評価
  - [ ] 5分スライディングウィンドウ管理
  - [ ] `needs_l2` 判定
- [ ] Redis連携時のキー設計とTTL方針を定義（ユーザー単位でウィンドウ保持）。

#### 3.4.3 Gateway統合とフェイルセーフ
- [ ] `backend/main.py` のL1呼び出しをアダプタ層経由に変更し、Python/Rustを切替可能化。
- [ ] Rust側障害時はPython L1へ即時フォールバックし、サービス停止を回避。
- [ ] 判定差分・エラー率・レイテンシをメトリクスとして記録。

#### 3.4.4 パフォーマンス検証とリリース
- [ ] k6/Locustで Python L1 と Rust L1 を同一シナリオで比較測定。
- [ ] **受け入れ基準**:
  - [ ] ゴールデンテスト一致率 100%
  - [ ] Rustモードで p99 L1判定レイテンシ 30ms 以下（同一環境比較）
  - [ ] Rust障害注入時にPythonフォールバックで継続稼働
- [ ] 段階リリース: ステージング100% -> 本番カナリア10% -> 本番100%

---

## Phase 4: Ecosystem & Expansion (エコシステム拡大)

サードパーティ開発者が容易に利用できる環境を整備する。

### 4.1 Client SDK
- [ ] **Unity SDK**: C# パッケージの提供（イベント送信、非同期通知受信）
- [ ] **Unreal Engine SDK**: C++ プラグインの提供

### 4.2 マルチテナント対応
- [ ] データ分離（Row Level Security または Schema 分離）
- [ ] テナントごとの設定管理（検知閾値、通知先）

### 4.3 管理ダッシュボードの機能拡張
- [ ] 監査ログの検索・フィルタリング機能強化
- [ ] PDFレポート出力機能
- [ ] Webhook設定UI

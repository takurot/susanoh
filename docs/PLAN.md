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
- [ ] **State Store**: Redisの導入
  - ステートマシン状態のRedis管理
  - L1スライディングウィンドウデータのRedis移行 (Sorted Sets活用)

### 1.2 認証・認可基盤
- [x] **Service Authentication**: ゲームサーバー向けAPI Key認証 (`X-API-KEY`) の実装と管理機能（Middleware実装）
  - Status: プロトタイプ実装済み（`SUSANOH_API_KEYS` 設定時に `/api/v1/*` へ適用、2026-02-22）
- [ ] **User Authentication**: ダッシュボード向けJWT認証 (OAuth2 Password Bearer)
- [ ] **RBAC**: `Admin`, `Operator`, `Viewer` ロールの実装

### 1.3 非同期処理の分離
- [ ] **Task Queue**: Celery または Arq の導入
- [ ] L2 Gemini分析処理をWebサーバープロセスから分離し、ワーカープロセスへ委譲
- [ ] 分析結果のWebフック通知またはポーリング用DB格納

### 1.4 ステートマシン機能補完
- [x] **自動復旧ロジック**: L2分析結果が「Low Risk」の場合、自動的に `RESTRICTED_WITHDRAWAL` から `NORMAL` へ戻す処理の実装
  - Status: プロトタイプ実装済み（2026-02-22）

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

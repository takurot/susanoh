# 実装ロードマップ：Susanoh (Production Roadmap)

## 概要

本ドキュメントでは、Susanohを現在のプロトタイプ（インメモリ・シングルプロセス）からプロダクションレディなミドルウェアへ昇華させるための段階的実装計画を定義する。
各フェーズは、前フェーズの安定稼働を前提として進行する。

---

## Phase 1: Foundation for Production (基盤強化)

プロトタイプから、永続化・分散対応可能なアーキテクチャへの移行を最優先とする。

### 1.1 永続化層の実装
- **Database**: PostgreSQLの導入
  - `User`, `EventLog`, `AnalysisResult`, `AuditLog` テーブルのスキーマ設計 (SQLAlchemy / Alembic)
  - 既存のインメモリデータのDB移行ロジック
- **State Store**: Redisの導入
  - ステートマシン状態のRedis管理
  - L1スライディングウィンドウデータのRedis移行 (Sorted Sets活用)

### 1.2 認証・認可基盤
- **Service Authentication**: ゲームサーバー向けAPI Key認証 (`X-API-KEY`) の実装と管理機能（Middleware実装）
  - Status: プロトタイプ実装済み（`SUSANOH_API_KEYS` 設定時に `/api/v1/*` へ適用、2026-02-22）
- **User Authentication**: ダッシュボード向けJWT認証 (OAuth2 Password Bearer)
- **RBAC**: `Admin`, `Operator`, `Viewer` ロールの実装

### 1.3 非同期処理の分離
- **Task Queue**: Celery または Arq の導入
- L2 Gemini分析処理をWebサーバープロセスから分離し、ワーカープロセスへ委譲
- 分析結果のWebフック通知またはポーリング用DB格納

### 1.4 ステートマシン機能補完
- **自動復旧ロジック**: L2分析結果が「Low Risk」の場合、自動的に `RESTRICTED_WITHDRAWAL` から `NORMAL` へ戻す処理の実装
  - Status: プロトタイプ実装済み（2026-02-22）

---

## Phase 2: Infrastructure & DevOps (運用基盤)

安定したデプロイと監視体制を構築し、SLA 99.9%を担保する準備を整える。

### 2.1 コンテナ化とオーケストレーション
- **Docker**: `Dockerfile` の最適化（Multi-stage build）
- **Compose**: `docker-compose.yml` によるフルスタック（App, Worker, DB, Redis）起動構成
- **Kubernetes**: Helmチャートの作成（Deployment, Service, Ingress, HPA）

### 2.2 CI/CDパイプライン
- **GitHub Actions**:
  - Lint / Type Check / Unit Test の自動化
  - コンテナイメージのビルドとRegistryへのプッシュ
  - ステージング環境への自動デプロイ

### 2.3 可観測性 (Observability)
- **Monitoring**: Prometheus エクスポーターの実装
- **Visualization**: Grafana ダッシュボードの構築（RPS, Latency, Error Rate, Queue Depth）
- **Logging**: 構造化ログ（JSON）の出力と集約

---

## Phase 3: Performance & Scalability (性能向上)

トラフィック増大に対応し、数万イベント/秒を捌くための最適化を行う。

### 3.1 キャッシュ戦略
- 頻繁にアクセスされるユーザープロファイルのRedisキャッシュ
- 読み取り専用クエリのDBリードレプリカ分散

### 3.2 負荷試験とチューニング
- Locust / k6 を用いた負荷試験シナリオの作成
- ボトルネック特定と改善（DBインデックス最適化、コネクションプーリング調整）
- オートスケーリング設定の最適化

### 3.3 L2エンジンの高度化
- Gemini APIのレート制限ハンドリング強化（トークンバケットアルゴリズム）
- 分析結果のキャッシュ（類似イベントの再分析回避）

---

## Phase 4: Ecosystem & Expansion (エコシステム拡大)

サードパーティ開発者が容易に利用できる環境を整備する。

### 4.1 Client SDK
- **Unity SDK**: C# パッケージの提供（イベント送信、非同期通知受信）
- **Unreal Engine SDK**: C++ プラグインの提供

### 4.2 マルチテナント対応
- データ分離（Row Level Security または Schema 分離）
- テナントごとの設定管理（検知閾値、通知先）

### 4.3 管理ダッシュボードの機能拡張
- 監査ログの検索・フィルタリング機能強化
- PDFレポート出力機能
- Webhook設定UI

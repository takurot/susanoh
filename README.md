# Susanoh (スサノヲ)

> **[Status: Prototype / Beta]**
> 本プロジェクトは現在プロトタイプ段階であり、プロダクション運用に向けたアーキテクチャ設計（[docs/SPEC.md](docs/SPEC.md)）と実装計画（[docs/PLAN.md](docs/PLAN.md)）を策定中です。
> 現行実装はデモ用のインメモリ構成で動作します。

**AI駆動型 経済圏防衛ミドルウェア — ゲーム内不正取引をリアルタイムで検知・隔離・監査**

Susanoh は、オンラインゲーム経済圏におけるRMT（リアルマネートレーディング）、資金洗浄、Bot活動などの不正取引を、ゲームサーバーからのイベント送信だけで導入できる開発者向けセキュリティミドルウェアです。

---

## 主な機能 (Target Architecture)

以下の機能は、プロダクション版での実現を目指すターゲット仕様です。（現行プロトタイプでは一部簡略化されています）

- **🛡️ L1 高速ルール判定 (Real-time Screening)**
  Redisを用いたスライディングウィンドウにより、イベント受信から50ms以内に不審な動きを検知し、即座に一次対応を行います。
  *(Current: Pythonインメモリ実装)*

- **🧠 L2 Gemini 文脈判定 (Contextual Analysis)**
  Google Gemini API を活用し、チャットログや取引パターンから「なぜ不正と疑われるか」の文脈を解析。構造化された監査レポート（判定理由）を提供します。

- **🍯 ハニーポット制御 (Dynamic State Machine)**
  疑わしいアカウントに対し、即座にBANするのではなく「出金のみをブロック」するステートへ遷移。業者の活動を泳がせつつ、経済圏からの資産流出を確実に阻止します。
  *(Current: L2 Low Risk verdict時の自動復旧に対応済み)*

- **📊 統合ダッシュボード (Observability)**
  資金フローの可視化グラフ、リアルタイム監査ログ、手動介入インターフェースを備えた管理画面を提供します。

---

## アーキテクチャ

Susanoh は、スケールアウト可能なマイクロサービスアーキテクチャへの移行を進めています。

### Target Architecture (Production Goal)

```mermaid
graph TD
    GameServer -->|HTTP/REST| APIGateway[FastAPI Gateway]
    APIGateway -->|Events| L1[L1 Screening Engine]
    L1 -->|State| Redis[(Redis State Store)]
    L1 -->|Async Task| Queue[Task Queue]
    Queue --> Worker[L2 Analysis Worker]
    Worker -->|Prompt| LLM[Gemini API]
    APIGateway -->|Logs| DB[(PostgreSQL)]
    Dashboard -->|Query| APIGateway
```

### Current Implementation (Prototype)

- **Backend**: FastAPI (Single Process)
- **State Store**: Redis (Implemented Phase 1)
- **Persistence**: PostgreSQL snapshot persistence (Implemented Phase 1)
- **AI Engine**: Google Gemini API (Direct Call)
- **Frontend**: React, TypeScript, Vite

---

## クイックスタート (開発環境)

DBやRedisなしで即座に動作確認が可能です。

### 前提条件

- Python 3.11+
- Node.js 18+
- Google AI Studio API Key

### 1. バックエンド構築

```bash
# リポジトリのクローン
git clone <repository_url>
cd susanoh

# 仮想環境の作成と依存関係のインストール
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# 環境変数の設定
export GEMINI_API_KEY=<your_api_key>
# (Optional) モデル指定
export GEMINI_MODEL=gemini-2.0-flash
# (Optional) API Key認証を有効化する場合（カンマ区切りで複数指定可）
export SUSANOH_API_KEYS=dev-key
# (Optional) DB永続化を有効化する場合
export DATABASE_URL=postgresql://user:pass@localhost:5432/susanoh

# サーバー起動 (開発モード)
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# (Optional) 非同期ワーカーの起動 (L2分析を非同期で行う場合)
# REDIS_URL が必要です。未設定の場合はサーバープロセス内で同期的に処理されます。
arq backend.worker.WorkerSettings
```

### 2. フロントエンド構築

```bash
cd frontend
npm install

# 開発サーバー起動
npm run dev
```

ブラウザで `http://localhost:5173` を開き、ダッシュボードにアクセスします。

---

## API リファレンス

### Authentication (Current Behavior)
- `SUSANOH_API_KEYS` が未設定: **認証なし**（従来どおり）
- `SUSANOH_API_KEYS` が設定済み: ゲームサーバー用APIエンドポイントで `X-API-KEY` ヘッダー必須
- ダッシュボードエンドポイント全体がJWTベースの `OAuth2 Password Bearer` 認証とRBAC（Admin, Operator, Viewer）で保護されています。モックユーザー: `admin`, `operator`, `viewer` (パスワードは共通で `password123`)

```bash
curl -H "X-API-KEY: dev-key" http://localhost:8000/api/v1/stats
```

### Endpoints (Implemented)

| メソッド | エンドポイント | 説明 |
|---|---|---|
| `POST` | `/api/v1/events` | ゲームイベント受信 + L1スクリーニング |
| `GET` | `/api/v1/events/recent` | 直近イベント一覧 (Dashboard用) |
| `GET` | `/api/v1/users` | 全ユーザー状態一覧 |
| `GET` | `/api/v1/users/{user_id}` | 特定ユーザー状態照会 |
| `POST` | `/api/v1/withdraw` | 出金リクエスト（ステートに基づく制御） |
| `POST` | `/api/v1/users/{user_id}/release` | アカウントの手動ロック解除 |
| `GET` | `/api/v1/stats` | 統計メトリクス取得 |
| `GET` | `/api/v1/graph` | 資金フローグラフデータ取得 |
| `POST` | `/api/v1/analyze` | 手動L2分析トリガー |
| `GET` | `/api/v1/analyses` | AI監査レポート一覧 |
| `GET` | `/api/v1/transitions` | 状態遷移ログ一覧 |
| `POST` | `/api/v1/demo/scenario/{name}` | デモシナリオ注入 (`normal`, `rmt-smurfing` etc.) |
| `POST` | `/api/v1/demo/start` | デモストリーミング開始 |
| `POST` | `/api/v1/demo/stop` | デモストリーミング停止 |

詳細な仕様（将来像を含む）は [docs/SPEC.md](docs/SPEC.md) を参照してください。

---

## 開発ロードマップ

プロダクション運用に向けたロードマップは [docs/PLAN.md](docs/PLAN.md) で管理されています。

- [x] **Prototype**: L1 ルールエンジン & ステートマシン (In-Memory)
- [x] **Prototype**: L2 Gemini 分析統合
- [x] **Prototype**: リアルタイムダッシュボード
- [x] **Phase 1**: PostgreSQL 永続化 & Redis 導入
  - PostgreSQLスナップショット永続化（SQLAlchemy）: 実装済み
  - Redis state store: 実装済み (2026-02-22)
- [x] **Phase 1**: 認証・認可基盤 (API Key / JWT)
  - Service API Key (`X-API-KEY` middleware): 実装済み
  - JWT / RBAC: 実装済み
- [x] **Phase 1**: 自動ステート復旧ロジック (L2 White Verdict)
- [ ] **Phase 2**: CI/CD & Docker 化

---

## ライセンス

[MIT License](LICENSE)

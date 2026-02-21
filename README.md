# Susanoh

AI駆動型 経済圏防衛ミドルウェア — ゲーム内不正取引をリアルタイムで検知・隔離するAPI

## 概要

Susanoh は、オンラインゲーム経済圏の不正取引（RMT・資金洗浄）対策を、ゲームサーバーからのイベント送信だけで導入できる開発者向けミドルウェアです。

**コアの仕組み:**

- **L1 高速ルール判定** — 5分スライディングウィンドウで即時検知
- **L2 Gemini 文脈判定** — 構造化出力で誤検知を抑制し、判定根拠を提示
- **ハニーポット制御** — 入金は許可、出金のみブロック（業者に気づかせない）

## セットアップ

### 前提条件

- Python 3.11+
- Node.js 18+
- (任意) Google AI Studio API Key

### バックエンド

```bash
cd susanoh
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### フロントエンド

```bash
cd frontend
npm install
```

### 環境変数（任意）

```bash
export GEMINI_API_KEY=<your-api-key>
export GEMINI_MODEL=gemini-2.5-flash
```

> APIキー未設定でもローカルフォールバック裁定で動作します。

## 起動方法

### バックエンド起動

```bash
source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### フロントエンド起動

```bash
cd frontend
npm run dev
```

ブラウザで http://localhost:5173 を開く。

## デモ実行手順

1. バックエンドとフロントエンドを起動
2. ダッシュボードの「Normal」ボタンで正常トラフィックを投入 → 全員 NORMAL
3. 「Smurfing」ボタンでスマーフィングパターンを注入 → 星型グラフが出現、ターゲットが黄→赤に遷移
4. アカウント管理テーブルで「出金テスト」→ 423 Locked を確認
5. AI監査レポートで Gemini の判定根拠（reasoning）を確認
6. 「Start Stream」で継続ストリーミングデモ

## テスト実行

```bash
source .venv/bin/activate
python3 -m pytest tests/ -v
```

## API一覧

| メソッド | エンドポイント | 説明 |
|---|---|---|
| POST | `/api/v1/events` | イベント受信 + L1スクリーニング |
| GET | `/api/v1/events/recent` | 直近イベント一覧 |
| GET | `/api/v1/users` | ユーザー状態一覧 |
| GET | `/api/v1/users/{user_id}` | ユーザー状態照会 |
| POST | `/api/v1/withdraw` | 出金リクエスト |
| POST | `/api/v1/users/{user_id}/release` | 手動解除 |
| GET | `/api/v1/stats` | 統計情報 |
| GET | `/api/v1/transitions` | 遷移ログ |
| GET | `/api/v1/graph` | 資金フローグラフデータ |
| POST | `/api/v1/analyze` | L2分析実行 |
| GET | `/api/v1/analyses` | 分析結果一覧 |
| POST | `/api/v1/demo/scenario/{name}` | デモシナリオ注入 |
| POST | `/api/v1/demo/start` | ストリーミング開始 |
| POST | `/api/v1/demo/stop` | ストリーミング停止 |

## 使用技術・外部API

| カテゴリ | 技術 |
|---|---|
| バックエンド | Python, FastAPI, Pydantic, uvicorn |
| フロントエンド | React, TypeScript, Vite, TailwindCSS |
| AI分析 | Google Gemini API (gemini-2.0-flash) |
| グラフ可視化 | react-force-graph-2d (D3 force-directed) |
| HTTP通信 | httpx |

## プロジェクト構成

```text
susanoh/
├── backend/
│   ├── main.py            # FastAPI エントリポイント
│   ├── models.py          # Pydantic データモデル
│   ├── state_machine.py   # ステートマシン
│   ├── l1_screening.py    # L1 ルールエンジン
│   ├── l2_gemini.py       # L2 Gemini 解析エンジン
│   ├── mock_server.py     # Mock データ生成
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       └── components/
│           ├── StatsCards.tsx
│           ├── EventStream.tsx
│           ├── NetworkGraph.tsx
│           ├── AuditReport.tsx
│           └── AccountTable.tsx
├── tests/
│   ├── test_state_machine.py
│   ├── test_l1_screening.py
│   ├── test_l2_fallback.py
│   └── test_withdraw_api.py
├── docs/
│   ├── SPEC.md
│   ├── RULE.md
│   ├── PLAN.md
│   └── PROMPT.md
└── README.md
```

## ハッカソン適合

- **対象ステートメント**: ステートメント2（ゲーム開発ツール強化）
- **デモ方針**: スライドなし、実稼働画面 + API実行 + 状態遷移ログを直接提示
- **DQ回避**: ハッカソン期間中に実装した範囲と将来構想を明確に分離

### 将来構想（今回未実装）

- Rust製高速ゲートウェイへの置換
- PostgreSQL永続DB・監査PDFエクスポート
- 認証・マルチテナント対応
- 実ゲームSDK化

# 機能仕様書（Hackathon Demo版）：AI駆動型 経済圏防衛ミドルウェア「Susanoh」

## 0. エグゼクティブサマリー

「Susanoh（スサノヲ）」は、オンラインゲームの不正取引対策を**1つのAPIで導入可能**にする開発者向けミドルウェアです。  
価値の核は、`L1:高速ルール判定` + `L2:Gemini文脈判定` + `出金だけを止めるハニーポット制御` により、**誤検知ダメージを抑えながら不正資金を隔離**できる点です。

本仕様は「審査で勝つ」ことを目的に、実装優先度と3分デモ動線を明確化した版です。

---

## 1. ハッカソンルール適合（`docs/RULE.md` 反映）

| ルール要件 | 本プロジェクトでの対応 |
|---|---|
| 問題ステートメントとの整合 | **ステートメント2（ゲーム開発ツール強化）**に合致。ゲーム開発者向けの不正対策APIを提供 |
| 新規作品であること | 既存プロダクトを持ち込まず、ハッカソン中に実装した機能のみデモ |
| 貢献範囲の明確化 | 「今回作った機能」「将来構想」を仕様で明確に分離 |
| 禁止カテゴリ回避 | 基本RAG/Streamlit/画像分析/医療助言系に該当しない |
| デモ重視 | スライドなしで、稼働画面 + API実行 + 状態遷移ログを直接提示 |

### ハッカソン中に実装して見せる範囲

- L1ルールエンジン（FastAPI）
- L2 Gemini分析（構造化出力）
- ハニーポット・ステートマシン（出金ブロック）
- リアルタイムダッシュボード
- 攻撃シナリオ生成用Mock Server

### 将来構想として口頭説明に留める範囲

- Rustゲートウェイ置換
- 永続DB（PostgreSQL）・監査PDF
- 認証・マルチテナント

---

## 2. 審査基準へのアピール設計

| 審査項目 | 配点 | 何を見せるか | 勝ち筋 |
|---|---:|---|---|
| インパクト | 25% | 不正資金隔離によるゲーム経済保護 | 「運営の不正対応コスト削減」と「誤BAN低減」を数値カードで提示 |
| デモ | 50% | 3分でE2E実演（検知→隔離→裁定→BAN） | APIレスポンスとUI遷移を同時に見せる |
| 創造性 | 15% | **入金許可/出金のみ停止**のハニーポット制御 | 業者の資金効率を逆利用する設計を強調 |
| ピッチ | 10% | 「1エンドポイントで導入」メッセージ | 技術詳細より導入容易性を短く訴求 |

---

## 3. プロダクト概要

### 3.1 対象ユーザー

- 中小〜中規模のオンラインゲーム運営チーム
- セキュリティ専任がいないインディー/スタートアップ開発者

### 3.2 提供価値

- ゲームサーバーに `POST /api/v1/events` を追加するだけで不正監視開始
- 不審アカウントは段階管理し、即BANではなく「証拠ベースの裁定」
- 審査員に示せる形で、AI判定理由（`reasoning`）を可視化

### 3.3 差別化ポイント

- **ハニーポット・ステートマシン**: 業者活動を継続させつつ出金だけ阻止
- **二層判定**: L1で即応、L2で誤検知を抑制
- **説明可能性**: Geminiの構造化出力で運営判断の説明責任を担保

---

## 4. デモファーストMVPスコープ

### 4.1 Must（審査までに必須）

| コンポーネント | 実装要件 |
|---|---|
| L1スクリーニング | 5分ウィンドウでルール判定、状態遷移トリガー発火 |
| L2 Gemini分析 | `response_schema` 強制で `ArbitrationResult` を返す |
| ステートマシン | `NORMAL → RESTRICTED_WITHDRAWAL → UNDER_SURVEILLANCE → BANNED` |
| 出金API | `POST /api/v1/withdraw` で状態に応じた拒否を実演可能にする |
| ダッシュボード | イベント流、状態遷移、AI判定理由、統計カードを単一画面表示 |
| 資金フローグラフ | `react-force-graph-2d` でユーザー間資金移動を有向グラフ表示。検知時のノード変色アニメーション |
| デモシナリオ注入 | `POST /api/v1/demo/scenario/{name}` で攻撃パターンを即注入 |

### 4.2 Should（時間があれば実装）

- 手動解除UI（`UNDER_SURVEILLANCE → NORMAL`）
- `p95判定遅延` 指標の表示

### 4.3 Out（今回やらない）

- 本番Rust化
- 認証/権限管理
- 永続DB/監査PDF
- 実ゲームSDK化

---

## 5. コアアーキテクチャ

### 5.1 処理フロー

```text
Game Server Event
  -> L1 Screening (<=50ms目標)
  -> State Machine (即時出金制御)
  -> L2 Gemini Arbitration (<=2s目標)
  -> Final Action + Dashboard Update
```

### 5.2 ステート定義

```text
NORMAL -> RESTRICTED_WITHDRAWAL -> UNDER_SURVEILLANCE -> BANNED
                                  └---------------> NORMAL (manual release)
```

| ステータス | 説明 | 挙動 |
|---|---|---|
| `NORMAL` | 通常利用 | 入出金・トレード可能 |
| `RESTRICTED_WITHDRAWAL` | 初期隔離 | **出金のみ拒否**。入金・プレイ継続 |
| `UNDER_SURVEILLANCE` | 要監視 | 出金拒否継続 + L2継続分析 |
| `BANNED` | 不正確定 | アカウント凍結 |

### 5.3 実装仕様（コア）

- 状態管理: `dict[str, AccountState]`（インメモリ）
- 遷移関数: `transition(user_id, trigger, evidence)`（不正遷移を検証）
- ログ: 全遷移を `TransitionLog[]` で記録しダッシュボードに表示
- 手動解除: `POST /api/v1/users/{id}/release`

---

## 6. コンポーネント詳細

### 6.1 Mock Game Server（合成データ）

| パターン | 割合 | 内容 | グラフ上の形状 |
|---|---:|---|---|
| 通常プレイヤー | 90% | 少額取引・自然チャット | 疎な双方向エッジ |
| スマーフィング | 5% | 複数低レベルアカウントから資金集約 | **星型**（多→1の集約） |
| RMT隠語トレード | 3% | 「D確認」「振込」「3k」等を含む | 太い単方向エッジ |
| レイヤリング | 2% | 多段ホップ送金で追跡回避 | **チェーン**（A→B→C→D） |

- 送信先: `POST /api/v1/events`
- 送信間隔: 100〜500ms
- デモ用シナリオ: `normal`, `rmt-smurfing`, `layering`

**グラフ映えのためのデータ設計ルール**:
- スマーフィングでは固定の `target_id`（例: `user_boss_01`）に対して5〜8個のサブアカウント（`user_mule_01`〜`08`）から送金し、星型パターンを明示
- レイヤリングでは `user_layer_A` → `user_layer_B` → `user_layer_C` → `user_layer_D` のチェーンを生成し、追跡線が視覚的に追える構造にする
- 通常プレイヤーは `user_player_01`〜`20` でランダムなペアの少額取引を生成し、背景ノイズとして機能させる

### 6.2 Tier 1: スクリーニングエンジン（FastAPI）

**エンドポイント**

```text
POST /api/v1/events
GET  /api/v1/events/recent
POST /api/v1/withdraw
GET  /api/v1/users
GET  /api/v1/users/{id}
GET  /api/v1/stats
GET  /api/v1/transitions
GET  /api/v1/graph
POST /api/v1/users/{id}/release
POST /api/v1/analyze
GET  /api/v1/analyses
POST /api/v1/demo/scenario/{name}
POST /api/v1/demo/start
POST /api/v1/demo/stop
```

**L1判定ルール（5分スライディングウィンドウ）**

| ルールID | 条件 | アクション |
|---|---|---|
| R1 | 累計取引額 >= 1,000,000 G | `RESTRICTED_WITHDRAWAL` |
| R2 | 取引回数 >= 10回 | `RESTRICTED_WITHDRAWAL` |
| R3 | 単発取引額が市場平均の100倍以上 | `RESTRICTED_WITHDRAWAL` |
| R4 | チャットが隠語正規表現に一致 | L2へ即時転送 |

**隠語正規表現（MVP）**

```regex
振[り込]?込|D[でにて]確認|[0-9]+[kK千万]|りょ[。.]|PayPa[ly]|銀行|口座|送金|入金確認
```

**出金API挙動（デモ要）**

- `NORMAL`: `200 OK`
- `RESTRICTED_WITHDRAWAL` / `UNDER_SURVEILLANCE`: `423 Locked`
- `BANNED`: `403 Forbidden`

### 6.3 Tier 2: Gemini解析・裁定エンジン

- 技術: FastAPI内部ルーター + Gemini API
- モデル: `GEMINI_MODEL`（デフォルト `gemini-2.0-flash`）
- 入力: `AnalysisRequest`
- 出力: `ArbitrationResult`（`response_schema` で強制）

**判定基準**

- `risk_score 0-30` -> `NORMAL`
- `risk_score 31-70` -> `UNDER_SURVEILLANCE`
- `risk_score 71-100` -> `BANNED`

**障害時フォールバック（デモ安定化）**

- Gemini timeout: 8秒 + 1回リトライ
- 失敗時: `UNDER_SURVEILLANCE` に遷移してサービス停止を回避
- パース失敗時: エラー記録 + `UNDER_SURVEILLANCE`

### 6.4 ダッシュボード（単一ページ）

| セクション | 表示内容 |
|---|---|
| 資金フローグラフ | ユーザー間資金移動の有向グラフ（ダッシュボード最上部、視覚的主役） |
| KPIカード | 総処理件数/L1フラグ/L2分析/BAN件数/ブロック出金件数 |
| リアルタイムイベント | 最新20件、危険イベントを強調 |
| AI監査レポート | `risk_score`、`reasoning`、`evidence_event_ids` |
| アカウント管理 | 状態別一覧 + 手動解除 |

> 注: Streamlitは禁止対象のため使用しない。

**資金フローグラフ仕様**:

- ライブラリ: `react-force-graph-2d`（D3 force-directed のReactラッパー）
- データソース: `GET /api/v1/graph` から3秒ポーリング
- ノード = アカウント。色でステータス表現:
  - 緑 = `NORMAL`
  - 黄 = `RESTRICTED_WITHDRAWAL`
  - 橙 = `UNDER_SURVEILLANCE`
  - 赤 = `BANNED`
- エッジ = 取引。太さで金額を表現（対数スケール）、矢印で方向を表示
- 検知演出: ステータス変更時にノードがパルスアニメーション（CSS `@keyframes`）で点滅
- グラフAPIレスポンス形式:

```json
{
  "nodes": [
    { "id": "user_00184", "state": "BANNED", "label": "user_00184" }
  ],
  "links": [
    { "source": "user_77391", "target": "user_00184", "amount": 1500000, "count": 3 }
  ]
}
```

---

## 7. データスキーマ（JSON）

### 7.1 GameEventLog

```json
{
  "event_id": "evt_9a8b7c6d",
  "timestamp": "2026-02-21T20:18:30Z",
  "event_type": "TRADE",
  "actor_id": "user_77391",
  "target_id": "user_00184",
  "action_details": {
    "currency_amount": 1500000,
    "item_id": "itm_wood_stick_01",
    "market_avg_price": 10
  },
  "context_metadata": {
    "actor_level": 3,
    "account_age_days": 2,
    "recent_chat_log": "Dで振り込み確認しました。"
  }
}
```

### 7.2 AnalysisRequest

```json
{
  "trigger_event": { "...GameEventLog..." },
  "related_events": ["...直近5分間のイベント..."],
  "triggered_rules": ["R1", "R3"],
  "user_profile": {
    "user_id": "user_00184",
    "current_state": "RESTRICTED_WITHDRAWAL",
    "total_received_5min": 3500000,
    "transaction_count_5min": 8,
    "unique_senders_5min": 6
  }
}
```

### 7.3 ArbitrationResult

```json
{
  "target_id": "user_00184",
  "is_fraud": true,
  "risk_score": 95,
  "fraud_type": "RMT_SMURFING",
  "recommended_action": "BANNED",
  "reasoning": "短時間で低レベル複数アカウントから高額資金が集中し、チャットにも外部決済を示す隠語があるためRMTと判定。",
  "evidence_event_ids": ["evt_9a8b7c6d", "evt_9a8b7c6e"],
  "confidence": 0.95
}
```

`fraud_type` 値:

- `RMT_SMURFING`
- `RMT_DIRECT`
- `MONEY_LAUNDERING`
- `LEGITIMATE`

### 7.4 TransitionLog

```json
{
  "user_id": "user_00184",
  "from_state": "RESTRICTED_WITHDRAWAL",
  "to_state": "BANNED",
  "trigger": "L2_ANALYSIS",
  "triggered_by_rule": "GEMINI_VERDICT",
  "timestamp": "2026-02-21T20:18:35Z",
  "evidence_summary": "RMTスマーフィング確定（risk_score: 95）"
}
```

---

## 8. 3分デモ台本（一次/最終審査共通）

### 0:00-0:25 問題提示

- 「不正対策は必要だが、誤BANで通常ユーザーを傷つけるのが怖い」
- 「Susanohは出金だけ止めるので、体験を壊さずに隔離できる」

### 0:25-1:00 正常トラフィック表示

- `normal` シナリオを流し、全員 `NORMAL` を確認
- 資金フローグラフに緑ノードが散在する平和な状態を提示
- KPIカードで処理継続を表示

### 1:00-1:45 攻撃注入 + 即時隔離

- `rmt-smurfing` シナリオ注入
- **グラフ上に星型パターンが出現** → 複数ノードからターゲットへ集約する動きを視覚提示
- 対象アカウントが黄色（`RESTRICTED_WITHDRAWAL`）にパルス変色
- `POST /api/v1/withdraw` 実行で `423 Locked` を提示

### 1:45-2:30 Gemini裁定

- L2レスポンスの `reasoning` を読み上げ
- `risk_score` と `evidence_event_ids` で根拠提示
- **グラフ上でターゲットノードが赤（`BANNED`）に変化**

### 2:30-3:00 結果と導入性

- 最終状態 `BANNED` + グラフ上で不正ネットワークが赤く染まった全体像を提示
- 「ゲーム側はイベントを送るだけ」の導入容易性で締める

---

## 9. 1分提出動画の構成

1. 0-10秒: 問題と解決策を1文で提示  
2. 10-25秒: 正常状態ダッシュボード  
3. 25-45秒: 攻撃注入 -> 出金拒否 -> AI判定理由  
4. 45-60秒: BAN完了 + 価値訴求（導入1エンドポイント）

---

## 10. 提出前チェックリスト（DQ回避）

- デモで見せる機能がハッカソン中実装分のみである
- 使用OSS/外部APIをREADMEに明記
- 「未実装の将来構想」は口頭説明に分離
- 1分動画URLを提出フォームに添付

---

## 11. プロジェクト構成

```text
susanoh/
├── docs/
│   ├── RULE.md
│   └── SPEC.md
├── backend/
│   ├── main.py
│   ├── state_machine.py
│   ├── l1_screening.py
│   ├── l2_gemini.py
│   ├── models.py
│   ├── mock_server.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── EventStream.tsx
│   │   │   ├── StatsCards.tsx
│   │   │   ├── NetworkGraph.tsx
│   │   │   ├── AuditReport.tsx
│   │   │   └── AccountTable.tsx
│   │   └── api.ts
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

---

## 12. 環境変数

```bash
GEMINI_API_KEY=<Google AI Studio API Key>
GEMINI_MODEL=gemini-2.0-flash
```

---

## 13. 審査員向けキラー・ステートメント

「Susanohは、ゲーム経済を壊す不正資金だけを狙って隔離する“ゲーム特化RegTech API”です。  
誤BANを最小化しながら、開発者は1エンドポイント追加だけでエンタープライズ級の不正対策を導入できます。」

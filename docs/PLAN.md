# 実装計画（PR単位）：Susanoh

## 概要

`docs/SPEC.md` に基づき、5時間以内に完了する実装計画をPR単位で分割する。
各PRは独立してテスト可能な単位とし、依存関係の順に実装する。
審査デモの失敗確率を下げるため、API契約の不足とフォールバック手順を先に潰す。

## 実装ステータス（2026-02-21 時点）

- [x] PR1: プロジェクト基盤 + データモデル定義
- [x] PR2: ステートマシン実装
- [x] PR3: L1 スクリーニングエンジン
- [x] PR4: L2 Gemini 解析・裁定エンジン
- [x] PR5: Mock Game Server + デモシナリオ注入
- [x] PR6: フロントエンド ダッシュボード
- [x] PR7: 統合テスト + デモ準備
- [x] PR8: Incident Timeline UI（審査導線強化）
- [ ] PR9: Demo Director（一発実演モード）
- [ ] PR10: Graph Cinematic Mode（視覚演出強化）

## 本レビューで反映した改善点

- フロントエンド実装に必要な `イベント一覧API` と `ユーザー一覧API` を計画に追加
- Gemini API障害/キー未設定でも動く `ローカル裁定フォールバック` を追加
- READMEを「作成」から「更新（実装に合わせる）」に変更
- 5時間ジャスト計画のため、時間超過時の削減優先順位を明記

---

## 依存関係グラフ

```text
PR1 (基盤+モデル)
 ├── PR2 (ステートマシン)
 │    ├── PR3 (L1スクリーニング)
 │    │    ├── PR4 (L2 Gemini)
 │    │    └── PR5 (Mock Server + デモシナリオ)
 │    └── PR4 (L2 Gemini)
 └── PR6 (フロントエンド)
      └── PR7 (統合+デモ準備)
           └── PR8 (Incident Timeline)
                └── PR9 (Demo Director)
                     └── PR10 (Graph Cinematic)
```

---

## PR1: プロジェクト基盤 + データモデル定義 ✅ 完了

**所要時間**: 30分  
**ブランチ**: `feat/foundation`

### 目的
プロジェクトの骨格を構築し、全コンポーネントが共有するデータモデルを定義する。

### タスク

1. **バックエンド初期化**
   - `backend/requirements.txt` 作成
     - `fastapi`, `uvicorn[standard]`, `pydantic`, `google-genai`, `httpx`
   - `backend/main.py` — FastAPIアプリ骨格 + CORSミドルウェア設定

2. **Pydanticモデル定義** (`backend/models.py`)
   - `GameEventLog` — L1入力ペイロード
   - `ActionDetails` — 取引詳細
   - `ContextMetadata` — チャットログ等のメタデータ
   - `AnalysisRequest` — L1→L2転送用バンドル
   - `UserProfile` — ユーザー集約プロファイル
   - `ArbitrationResult` — L2出力（Gemini構造化出力スキーマ）
   - `TransitionLog` — 状態遷移ログ
   - `AccountState` enum — `NORMAL`, `RESTRICTED_WITHDRAWAL`, `UNDER_SURVEILLANCE`, `BANNED`
   - `FraudType` enum — `RMT_SMURFING`, `RMT_DIRECT`, `MONEY_LAUNDERING`, `LEGITIMATE`

3. **フロントエンド初期化**
   - `npm create vite@latest frontend -- --template react-ts`
   - TailwindCSS 導入
   - `frontend/src/api.ts` — APIクライアント骨格（ベースURL設定、型定義）

### 完了条件
- `uvicorn backend.main:app` で起動し、`GET /` が200を返す
- `npm run dev` でフロントエンドが起動する
- 全Pydanticモデルがimport可能

---

## PR2: ステートマシン実装 ✅ 完了

**所要時間**: 30分  
**ブランチ**: `feat/state-machine`  
**依存**: PR1

### 目的
ハニーポット戦略の心臓部であるアカウント状態管理を実装する。

### タスク

1. **ステートマシン本体** (`backend/state_machine.py`)
   - `StateMachine` クラス
     - `accounts: dict[str, AccountState]` — ユーザー状態管理
     - `transition_logs: list[TransitionLog]` — 遷移履歴
     - `get_or_create(user_id) -> AccountState` — 未知ユーザーは `NORMAL` で初期化
     - `transition(user_id, new_state, trigger, rule, evidence_summary) -> bool`
       - 許可される遷移パスを検証: `NORMAL→RESTRICTED_WITHDRAWAL→UNDER_SURVEILLANCE→BANNED`、`UNDER_SURVEILLANCE→NORMAL`（手動解除）
       - 不正な遷移は `False` を返す
       - 成功時に `TransitionLog` を記録
     - `can_withdraw(user_id) -> bool` — `NORMAL` の場合のみ `True`
     - `get_stats() -> dict` — 各ステータスのアカウント数集計
     - `get_transitions(limit) -> list[TransitionLog]` — 直近の遷移ログ

2. **APIエンドポイント追加** (`backend/main.py`)
   - `GET /api/v1/users` — 全ユーザー状態一覧（`?state=` フィルタ任意）
   - `GET /api/v1/users/{user_id}` — ユーザー状態照会
   - `POST /api/v1/withdraw` — 出金リクエスト（状態に応じて200/423/403）
   - `POST /api/v1/users/{user_id}/release` — 手動解除
   - `GET /api/v1/stats` — 統計情報
   - `GET /api/v1/transitions` — 遷移ログ

### 完了条件
- curlで出金APIを叩き、`NORMAL`→200, `RESTRICTED_WITHDRAWAL`→423, `BANNED`→403を確認
- 手動解除APIで `UNDER_SURVEILLANCE` → `NORMAL` に戻ることを確認
- 不正遷移（例: `NORMAL`→`BANNED`）が拒否されることを確認
- `GET /api/v1/users` で状態別一覧を取得できることを確認

---

## PR3: L1 スクリーニングエンジン ✅ 完了

**所要時間**: 45分  
**ブランチ**: `feat/l1-screening`  
**依存**: PR2

### 目的
ルールベースの高速フィルタリングで、疑わしいイベントを検知し状態遷移をトリガーする。

### タスク

1. **L1エンジン本体** (`backend/l1_screening.py`)
   - `L1Engine` クラス
     - `user_windows: dict[str, UserWindow]` — ユーザーごとのスライディングウィンドウ
     - `UserWindow` 内部クラス/データクラス
       - `events: deque` — 直近5分間のイベント
       - `add_event(event)` — イベント追加 + 5分超過分パージ
       - `total_amount() -> int` — 累計取引額
       - `transaction_count() -> int` — 取引回数
       - `unique_senders() -> int` — ユニーク送信者数
     - `screen(event: GameEventLog) -> ScreeningResult`
       - R1〜R4ルールを順次評価
       - 発火したルールIDリストと推奨アクションを返す
     - `_check_slang(chat_log: str) -> bool` — 隠語正規表現マッチ
     - `build_analysis_request(user_id) -> AnalysisRequest` — L2転送用バンドル構築

2. **イベント受信エンドポイント** (`backend/main.py`)
   - `POST /api/v1/events`
     - L1でスクリーニング
     - ルール発火時 → ステートマシンで `RESTRICTED_WITHDRAWAL` に遷移
     - R4（隠語）発火 or 既に `RESTRICTED_WITHDRAWAL` 以上 → L2へ非同期転送
     - レスポンス: `{screened: true/false, triggered_rules: [...]}`
   - `GET /api/v1/events/recent`
     - 直近イベント（デフォルト20件、`?limit=` 指定可）を返す
     - ダッシュボードのイベントストリーム表示に使用

3. **グラフデータAPI** (`backend/main.py`)
   - `GET /api/v1/graph`
     - 直近イベントからノード（ユーザー）とリンク（取引）を集約して返す
     - ノードにはステートマシンの現在状態を付与
     - リンクには同一ペア間の累計金額・取引回数を集約
     - レスポンス: `{ nodes: [{id, state, label}], links: [{source, target, amount, count}] }`

4. **L2転送の準備**
   - L2エンドポイント（`POST /api/v1/analyze`）への `httpx` 非同期呼び出し骨格
   - PR4が未完の間は内部関数呼び出しで代替可能な構造にする

### 完了条件
- 100万G超の取引イベントを送信 → `RESTRICTED_WITHDRAWAL` に遷移
- 5分間に10回以上の取引 → `RESTRICTED_WITHDRAWAL` に遷移
- 隠語を含むチャット → L2転送フラグが立つ
- 5分経過後にウィンドウがリセットされる
- `GET /api/v1/events/recent` でイベントストリームが取得できる
- `GET /api/v1/graph` でノード・リンク形式のグラフデータが返る

---

## PR4: L2 Gemini 解析・裁定エンジン ✅ 完了

**所要時間**: 60分  
**ブランチ**: `feat/l2-gemini`  
**依存**: PR2, PR3

### 目的
Gemini APIを使い、L1が検知したグレーなログの文脈分析と最終裁定を行う。本プロジェクト最重要コンポーネント。

### タスク

1. **Gemini解析エンジン** (`backend/l2_gemini.py`)
   - `L2Engine` クラス
     - `analyze(request: AnalysisRequest) -> ArbitrationResult`
       - Gemini API呼び出し（`google-genai` SDK使用）
       - `system_instruction`: SPEC §6.3のシステムプロンプト埋め込み
       - `generation_config`:
         - `response_mime_type: "application/json"`
         - `response_schema`: `ArbitrationResult` のJSONスキーマ
       - タイムアウト: 8秒 + 1回リトライ
       - パース失敗時フォールバック: `UNDER_SURVEILLANCE`
     - `_build_prompt(request: AnalysisRequest) -> str` — リクエストデータをGeminiへの入力文字列に整形

2. **システムプロンプト定義**
   - SPEC §6.3記載のプロンプト全文をコード内定数として定義
   - 分析観点: 取引パターン、チャットログ、アカウントプロファイル
   - 判定基準: risk_score 0-30→NORMAL, 31-70→UNDER_SURVEILLANCE, 71-100→BANNED

3. **オフライン/障害時フォールバック**
   - `GEMINI_API_KEY` 未設定時はローカル裁定器（ルールベース）を使用
   - Gemini timeout/429時は `UNDER_SURVEILLANCE` を返す安全側フォールバック
   - フォールバック時は `reasoning` に `fallback_reason` を明示

4. **L1→L2連携の統合**
   - PR3で作成した非同期転送骨格にL2エンジンを接続
   - L2判定結果でステートマシンを遷移（`UNDER_SURVEILLANCE` or `BANNED`）
   - 判定結果をインメモリリスト（`analysis_results`）に蓄積

5. **分析結果APIエンドポイント**
   - `GET /api/v1/analyses` — 直近の分析結果一覧（ダッシュボード用）

### 完了条件
- 隠語+高額取引のバンドルを送信 → Geminiが `is_fraud: true` + `reasoning` 付きで返す
- `response_schema` による構造化出力が正しくパースされる
- Gemini API失敗時に `UNDER_SURVEILLANCE` でフォールバックする
- `GET /api/v1/analyses` で判定結果を取得できる
- APIキー未設定環境でも `/api/v1/analyze` がエラー停止せずに応答する

---

## PR5: Mock Game Server + デモシナリオ注入 ✅ 完了

**所要時間**: 30分  
**ブランチ**: `feat/mock-server`  
**依存**: PR3

### 目的
デモ用の合成データ生成器と、審査時にワンクリックで攻撃パターンを注入するAPIを実装する。

### タスク

1. **合成データ生成** (`backend/mock_server.py`)
   - `MockGameServer` クラス
     - `generate_normal_event() -> GameEventLog` — 通常取引（`user_player_01`〜`20` のランダムペア少額取引。グラフ上で疎な背景ノイズになる）
     - `generate_smurfing_events() -> list[GameEventLog]` — スマーフィングパターン（`user_mule_01`〜`08` → `user_boss_01` への集約。グラフ上で**星型**を形成）
     - `generate_rmt_slang_event() -> GameEventLog` — 隠語チャット付き取引（グラフ上で太い単方向エッジ）
     - `generate_layering_events() -> list[GameEventLog]` — レイヤリング（`user_layer_A`→`B`→`C`→`D`。グラフ上で**チェーン**を形成）
   - 各生成関数はランダム要素を含みつつ、L1ルールを確実に発火させるパラメータを設定
   - **グラフ映えルール**: 不正パターンでは固定のuser_id命名を使い、グラフ上で視覚的に識別可能な形状（星型・チェーン）を生成すること

2. **デモシナリオAPI** (`backend/main.py`)
   - `POST /api/v1/demo/scenario/{name}`
     - `normal`: 通常イベントを10件送信
     - `rmt-smurfing`: スマーフィングパターンを注入
     - `layering`: レイヤリングパターンを注入
   - 各シナリオは内部的に `POST /api/v1/events` を呼び出す

3. **連続ストリーミングモード**
   - `POST /api/v1/demo/start` — バックグラウンドで100〜500ms間隔のイベント送信を開始
   - `POST /api/v1/demo/stop` — 停止
   - 90%通常 / 5%スマーフィング / 3%隠語 / 2%レイヤリングの比率で混合

### 完了条件
- `/api/v1/demo/scenario/rmt-smurfing` を叩くと、L1が発火し状態遷移が起きる
- `/api/v1/demo/start` で継続的にイベントが流れ、`/api/v1/demo/stop` で停止する
- 生成データがSPECのJSONスキーマに準拠している

---

## PR6: フロントエンド ダッシュボード ✅ 完了

**所要時間**: 60分  
**ブランチ**: `feat/dashboard`  
**依存**: PR1（API型定義のみ。バックエンドは並行開発可能）

### 目的
審査の50%を占める「デモ」の顔となるリアルタイムダッシュボードを構築する。

### タスク

1. **APIクライアント** (`frontend/src/api.ts`)
   - `fetchStats()` — `GET /api/v1/stats`
   - `fetchTransitions()` — `GET /api/v1/transitions`
   - `fetchAnalyses()` — `GET /api/v1/analyses`
   - `fetchRecentEvents()` — `GET /api/v1/events/recent`
   - `fetchUsers()` — `GET /api/v1/users`
   - `fetchGraph()` — `GET /api/v1/graph`
   - `triggerScenario(name)` — `POST /api/v1/demo/scenario/{name}`
   - `startDemo()` / `stopDemo()` — デモ制御
   - `tryWithdraw(userId, amount)` — `POST /api/v1/withdraw`
   - 3秒間隔のポーリングフック (`usePolling`)

2. **レイアウト + ヘッダー** (`frontend/src/App.tsx`)
   - 会場スクリーンでも見やすい高コントラストUI（ライト基調）
   - ヘッダー: 「Susanoh」ロゴ + リアルタイム処理カウンター
   - デモ制御パネル: シナリオ注入ボタン群 + Start/Stop

3. **KPIカード** (`frontend/src/components/StatsCards.tsx`)
   - 総処理件数 / L1フラグ件数 / L2分析件数 / BAN件数 / ブロック出金件数
   - 数値のアニメーション付きカウンター

4. **イベントストリーム** (`frontend/src/components/EventStream.tsx`)
   - 直近20件のイベントをリアルタイム表示
   - 危険イベント（ルール発火）は赤/オレンジでハイライト
   - 自動スクロール

5. **資金フローグラフ** (`frontend/src/components/NetworkGraph.tsx`)
   - ライブラリ: `react-force-graph-2d`（npm依存追加）
   - `GET /api/v1/graph` から3秒ポーリングでデータ取得
   - ノード色: ステータスに応じて 緑(`NORMAL`) / 黄(`RESTRICTED_WITHDRAWAL`) / 橙(`UNDER_SURVEILLANCE`) / 赤(`BANNED`)
   - エッジ: 太さで取引額（対数スケール）、矢印で方向表示
   - 検知演出: ステータス変更時にノードがパルスアニメーション（CSSの `@keyframes` で点滅）
   - ダッシュボード最上部に配置（デモの視覚的主役）

6. **AI監査レポート** (`frontend/src/components/AuditReport.tsx`)
   - `ArbitrationResult` をカード形式で表示
   - `risk_score` プログレスバー（色はスコアに応じて緑→黄→赤）
   - `reasoning` を目立つ形で表示（Geminiの判定根拠）
   - `evidence_event_ids` リスト

7. **アカウント管理テーブル** (`frontend/src/components/AccountTable.tsx`)
   - ステータス別のアカウント一覧
   - ステータスに応じたバッジ色（緑/黄/橙/赤）
   - 手動解除ボタン（`UNDER_SURVEILLANCE`のみ有効）

### 完了条件
- ダッシュボードが起動し、バックエンドAPIからデータを取得・表示できる
- デモ制御ボタンでシナリオ注入が実行できる
- 状態遷移がリアルタイムでUI上に反映される
- イベントストリームとアカウント一覧がAPIデータで更新される
- 資金フローグラフにノード・エッジが描画され、ステータス変更で色が変化する

---

## PR7: 統合テスト + デモ準備 ✅ 完了

**所要時間**: 45分  
**ブランチ**: `feat/integration`  
**依存**: PR1〜PR6 全て

### 目的
全コンポーネントを結合し、審査用デモが滞りなく実行できる状態にする。

### タスク

1. **E2E統合テスト**
   - バックエンド起動 → Mock Server開始 → L1検知 → L2裁定 → ダッシュボード反映の一連フロー確認
   - 出金API拒否のデモ確認
   - Gemini APIの実呼び出し確認（APIキー設定済み環境）

2. **デモ安定化**
   - Gemini APIレート制限への対応確認
   - フロントエンドのポーリングが途切れないことを確認
   - エラー時のUI表示（ローディング、リトライ表示）

3. **README.md 更新**
   - プロジェクト概要
   - セットアップ手順（`pip install`, `npm install`, 環境変数設定）
   - 起動方法（バックエンド + フロントエンド）
   - 使用技術・外部API一覧（DQ回避のため必須）
   - デモ実行手順

4. **デモリハーサル用スクリプト**
   - 3分デモ台本（SPEC §8）に沿ったコマンド/操作手順メモ
   - 1分提出動画の撮影手順

5. **DQ回避エビデンス整理**
   - 「今回実装した範囲」と「将来構想」を発表メモで分離
   - 使用OSS/外部APIの出典リンクをREADMEに列挙
   - デモで触るエンドポイントを固定し、当日変更を避ける

### 完了条件
- `README.md` に沿ってゼロからセットアップ → デモ実行が完了する
- 3分デモ台本を通しで実行して問題がない
- 提出フォームに必要な情報（動画URL等）が準備できる状態
- Gemini APIが不安定でもフォールバック経路でデモ継続できる

---

## PR8: Incident Timeline UI ✅ 完了

**所要時間**: 60分  
**ブランチ**: `feat/pr08-incident-timeline`  
**依存**: PR6, PR7

### 目的
審査員が「検知→隔離→裁定→最終状態」を一目で追える時系列ビューを追加し、3分デモの理解速度を上げる。

### タスク

1. **インシデント整形ロジック** (`frontend/src/components/incidentTimeline.ts`)
   - `buildIncidentTimeline(users, events, analyses, limit)` を実装
   - 対象抽出:
     - `NORMAL` 以外のユーザー
     - `analyses` に登場するユーザー
     - 高額/隠語イベントの受信ユーザー
   - ステップ生成:
     - `L1 Flagged`
     - `Withdraw Restricted`
     - `L2 Analyzed`
     - `Final: <STATE>`
   - 優先表示順:
     - `BANNED` > `UNDER_SURVEILLANCE` > `RESTRICTED_WITHDRAWAL` > `NORMAL`
     - 同順位は `risk_score` 降順

2. **Incident Timeline コンポーネント** (`frontend/src/components/IncidentTimeline.tsx`)
   - 対象アカウントごとに時系列チップを表示
   - 現在ステータスをバッジ表示（緑/黄/橙/赤）
   - `reasoning` がある場合はカード下部に表示

3. **ダッシュボード統合** (`frontend/src/App.tsx`)
   - `NetworkGraph` の直下に `IncidentTimeline` を配置
   - 既存ポーリングデータ（users/events/analyses）をそのまま利用

4. **テスト（TDD）**
   - 先に `incidentTimeline` の失敗テストを追加
   - 実装後にテストをグリーン化

### 完了条件
- Timelineで疑わしいアカウントが時系列ステップ付きで表示される
- `BANNED` / `UNDER_SURVEILLANCE` が優先表示される
- `reasoning` が可視化される
- `npm run test:run` が通る

---

## PR9: Demo Director（一発実演モード）🟡 未着手

**所要時間**: 45分  
**ブランチ**: `feat/demo-director`  
**依存**: PR8

### 目的
発表者の操作負荷を下げ、審査時の誤操作リスクを減らすために、主要デモ動線を1アクション化する。

### タスク

1. **ショーケースAPI追加** (`backend/main.py`)
   - `POST /api/v1/demo/showcase/smurfing`
   - 実行順:
     - `rmt-smurfing` 注入
     - `user_boss_01` 出金試行
     - 判定結果/状態を収集して要約返却

2. **レスポンス型追加** (`backend/models.py`)
   - `ShowcaseResult`
   - フィールド:
     - `target_user`
     - `triggered_rules`
     - `withdraw_status_code`
     - `latest_state`
     - `latest_risk_score`
     - `latest_reasoning`

3. **フロント統合** (`frontend/src/api.ts`, `frontend/src/App.tsx`)
   - `runShowcaseSmurfing()` を追加
   - ヘッダーに `Showcase` ボタン追加
   - 実行結果を上部バナー表示

### 完了条件
- `Showcase` 1クリックで 30〜45秒以内に主要シーケンスが再現できる
- 実行結果がUIに要約表示される

---

## PR10: Graph Cinematic Mode（視覚演出強化）🟡 未着手

**所要時間**: 45分  
**ブランチ**: `feat/graph-cinematic`  
**依存**: PR9

### 目的
視覚インパクトを強化し、創造性とデモ得点を引き上げる。

### タスク

1. **ノード演出** (`frontend/src/components/NetworkGraph.tsx`)
   - `RESTRICTED_WITHDRAWAL` 以上への遷移時にハイライトリング
   - `BANNED` で赤グロー表示

2. **エッジ演出**
   - 高額/不審エッジを一定時間太線化

3. **カメラ演出**
   - Showcase時に対象ノードへ軽いズーム/センタリング

4. **アクセシビリティ**
   - `prefers-reduced-motion` 環境では演出を抑制

### 完了条件
- 状態遷移時に視覚演出が発火する
- 低スペック環境でも操作不能にならない
- `prefers-reduced-motion` で過剰演出が無効化される

---

## タイムライン総括

| 順序 | PR | 所要時間 | 累計 | 並行可否 | ステータス |
|:---:|:---|:---:|:---:|:---:|:---:|
| 1 | PR1: 基盤+モデル | 30分 | 0:30 | - | ✅ |
| 2 | PR2: ステートマシン | 30分 | 1:00 | - | ✅ |
| 3 | PR3: L1スクリーニング + グラフAPI | 45分 | 1:45 | PR6と並行可 | ✅ |
| 4 | PR4: L2 Gemini | 60分 | 2:45 | - | ✅ |
| 5 | PR5: Mock Server（グラフ映え対応） | 30分 | 3:15 | PR6と並行可 | ✅ |
| 6 | PR6: ダッシュボード + 資金フローグラフ | 75分 | 4:30 | PR3〜5と並行可 | ✅ |
| 7 | PR7: 統合+デモ準備 | 30分 | 5:00 | - | ✅ |
| 8 | PR8: Incident Timeline UI | 60分 | 6:00 | - | ✅ |
| 9 | PR9: Demo Director | 45分 | 6:45 | PR10と連続推奨 | ⬜ |
| 10 | PR10: Graph Cinematic Mode | 45分 | 7:30 | - | ⬜ |
| | **合計** | **7:30** | | | **PR8まで完了** |

### 時間超過時の削減優先順位

5時間ジャスト計画のため、遅延時は以下の順に削る。

1. グラフのパルスアニメーション演出（静的な色分けだけでも十分伝わる）
2. UIアニメーション（KPIカウント演出）
3. `demo/start` の連続ストリーミング（`scenario` 注入のみで審査は成立）
4. 手動解除UI（APIのみ残し、画面実装は後回し）

### 並行開発の推奨

チームメンバーが複数いる場合:
- **担当A（バックエンド）**: PR1 → PR2 → PR3 → PR4 → PR5
- **担当B（フロントエンド）**: PR1完了後 → PR6（モックデータで開発） → PR7で統合

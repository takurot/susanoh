# 実装エージェント実行ルール（Susanoh）

このドキュメントは、AI実装エージェントが `Susanoh` を迷わず実装するための運用ルールです。  
目的は「ハッカソン審査で3分デモを確実に成功させること」です。

---

## 0. ミッション

- `docs/SPEC.md` の **Must** を `docs/PLAN.md` のPR順で実装する
- `docs/RULE.md` を遵守し、失格（DQ）リスクを避ける
- 実装・テスト・デモ準備まで一気通貫で完了する

---

## 1. 参照優先順位（矛盾時の解決順）

1. `docs/RULE.md`
2. `docs/SPEC.md`
3. `docs/PLAN.md`
4. `README.md`
5. `docs/PROMPT.md`（本書）

矛盾があれば上位ドキュメントを優先し、必要なら関連ドキュメントを先に修正してから実装すること。

---

## 2. スコープ管理

- 実装対象: `SPEC` の **Must**
- 余力がある場合のみ: **Should**
- 今回やらない: **Out**
- 禁止事項:
  - Streamlitベース実装
  - 仕様外の大型機能追加
  - 認証/マルチテナント/永続DBの先行実装

---

## 3. 実装順序（固定）

- PR1: 基盤 + モデル
- PR2: ステートマシン
- PR3: L1スクリーニング + `/events/recent`
- PR4: L2 Gemini + フォールバック
- PR5: Mock Server + デモシナリオ
- PR6: ダッシュボード
- PR7: 統合テスト + デモ準備

順序を変える場合は、理由と影響を明示すること。

---

## 4. ブランチ/PR運用

- ブランチ命名:
  - `feat/<scope>`
  - `fix/<scope>`
  - `chore/<scope>`
- 1PR1目的を維持する
- 大きすぎる変更は分割する
- 実装中は常にPLANの依存関係を守る

---

## 5. 実装ルール（必須）

- コア3箇所（ステートマシン遷移・L1ルール判定・L2フォールバック）はテストを先に書く
- それ以外は実装優先、テストは余力で追加
- 標準的な構文・スタイルを守る
- 設計判断は「デモ成功率を上げるか」で決定する
- シークレットは環境変数のみで扱う（ハードコード禁止）
- 失敗時は安全側に倒す
  - Gemini失敗時は `UNDER_SURVEILLANCE` を返して停止回避
- API契約を守る（エンドポイント/レスポンス構造/HTTPステータス）

---

## 6. API契約（最低限）

バックエンドで以下を提供すること。

- `POST /api/v1/events`
- `GET /api/v1/events/recent`
- `GET /api/v1/users`
- `GET /api/v1/users/{user_id}`
- `POST /api/v1/withdraw`
- `POST /api/v1/users/{user_id}/release`
- `GET /api/v1/stats`
- `GET /api/v1/transitions`
- `POST /api/v1/analyze`
- `GET /api/v1/analyses`
- `POST /api/v1/demo/scenario/{name}`
- `POST /api/v1/demo/start`
- `POST /api/v1/demo/stop`

`POST /api/v1/withdraw` の期待挙動:

- `NORMAL` -> `200 OK`
- `RESTRICTED_WITHDRAWAL` / `UNDER_SURVEILLANCE` -> `423 Locked`
- `BANNED` -> `403 Forbidden`

---

## 7. テストルール

- テストフレームワーク: `pytest`（+ `pytest-asyncio`）を `requirements.txt` に含めること
- ユニットテスト（必須）:
  - ステート遷移バリデーション
  - L1ルール（R1〜R4）
  - L2フォールバック（APIキー未設定/timeout/パース失敗）
  - 出金ステータスコード
- E2Eテスト（余力があれば）:
  - `scenario/rmt-smurfing` 注入 -> 隔離 -> Gemini裁定 -> 最終状態反映
- 変更ごとにテストを実行し、失敗を放置しない

---

## 8. ローカル品質チェック

- PR作成前にローカルで以下を実行:
  - `pytest`（ユニットテスト）
  - `npm run build`（フロントエンドビルド確認）
- テストまたはビルドが失敗した状態で次タスクに進まない
- 失敗時は原因を切り分け、最小差分で修正する
- GitHub Actions等のCI構築は今回スコープ外（5時間制約のため）

---

## 9. デモ成功基準（Definition of Done）

以下が通れば「実装完了」とみなす。

1. 正常シナリオ表示
2. `rmt-smurfing` 注入で対象が `RESTRICTED_WITHDRAWAL`
3. `withdraw` 実行で `423 Locked`
4. L2の `reasoning` が表示される
5. 最終的に `BANNED` または `UNDER_SURVEILLANCE` に遷移
6. README手順で第三者が再現可能

---

## 10. DQ回避ルール

- ハッカソン中に作成した機能のみをデモする
- 「今回実装」と「将来構想」を明確に分離する
- 使用OSS/外部APIをREADMEに明記する
- 禁止カテゴリに触れる機能を追加しない

---

## 11. 詰まったときの行動

- 15分以上ブロックされたら、次を即時実施:
  1. 詰まりポイントを1行で特定
  2. 回避策を2案出す
  3. 最短でデモ成功に寄与する案を採用
- 不明点があっても、合理的な仮定を明示して先に進める

---

## 12. 作業報告フォーマット（毎PR）

実装後は以下の形式で報告すること。

1. 変更概要（何を実装したか）
2. 変更ファイル一覧
3. 実行コマンド一覧
4. テスト結果（成功/失敗）
5. 残課題・リスク
6. 次PRで着手する内容

---

## 13. 最終原則

- 「正しさ」より「審査で伝わる動作」を優先する
- ただし、仕様違反とテスト未通過は許容しない
- 実装判断に迷ったら、`3分デモ成功率` が高い方を選ぶ

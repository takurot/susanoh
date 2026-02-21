# Susanoh

AI駆動型 経済圏防衛ミドルウェア（Hackathon Demo Project）

## 概要

`Susanoh` は、オンラインゲーム経済圏の不正取引（RMT・資金洗浄）対策を、ゲームサーバーからのイベント送信だけで導入できる開発者向けミドルウェアです。

コアは以下の3点です。

- `L1` 高速ルール判定（即時隔離）
- `L2` Geminiによる文脈判定（誤検知抑制）
- ハニーポット制御（入金は許可し、出金のみブロック）

## ハッカソン適合

- 対象: `docs/RULE.md` の **ステートメント2（ゲーム開発ツール強化）**
- デモ方針: スライドではなく、実際に動くAPI/UIの挙動を提示
- DQ回避: ハッカソン期間中に実装した範囲と将来構想を明確に分離

## 仕様ドキュメント

- ルール: `docs/RULE.md`
- 機能仕様（審査向け）: `docs/SPEC.md`

`docs/SPEC.md` には、審査基準への対応、3分デモ台本、1分提出動画構成、提出前チェックリストを定義しています。

## 現在のリポジトリ状態

現時点では仕様策定段階です。実装はこれから追加します。

```text
susanoh/
├── docs/
│   ├── RULE.md
│   └── SPEC.md
└── README.md
```

## 実装予定構成（SPEC準拠）

```text
backend/
  main.py
  state_machine.py
  l1_screening.py
  l2_gemini.py
  models.py
  mock_server.py
frontend/
  src/
    App.tsx
    components/
```

## デモで見せる価値（3分）

1. 正常トラフィックを表示
2. 攻撃シナリオを注入
3. L1で即時隔離（出金ロック）
4. L2 Geminiが根拠付きで裁定
5. `BANNED` までの状態遷移を可視化

詳細台本は `docs/SPEC.md` の「3分デモ台本」を参照してください。

## 環境変数（実装時）

```bash
GEMINI_API_KEY=<Google AI Studio API Key>
GEMINI_MODEL=gemini-2.0-flash
```

## ライセンス

ハッカソン用プロトタイプ。必要に応じて後続で定義します。

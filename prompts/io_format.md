# TD判断AI — 入出力フォーマット定義 v0.1

---

## INPUT FORMAT

### 必須項目

```json
{
  "situation": "状況の詳細説明（自然言語・日本語または英語）",
  "tournament_phase": "Day 1 / Day 2 / Final Table / Bubble / etc",
  "blinds": "2000-4000 / BB ante 4000",
  "players_involved": [
    {"seat": 1, "chips": 125000, "position": "BTN"},
    {"seat": 3, "chips": 87000, "position": "BB"}
  ]
}
```

### 任意項目

```json
{
  "game_type": "NLHE / PLO / HORSE",
  "stakes": "Main Event / Side Event",
  "timing": "Street (preflop/flop/turn/river/showdown)",
  "prior_actions": "ベッティング履歴（例: preflop 3bet, BTN call, flop checked through, turn bet 15k, BB raise to 45k...）",
  "house_rules_override": "ハウスルールで上書きされている項目",
  "videos_or_logs": "録画リンク・ハンド履歴（将来拡張）"
}
```

### 簡易入力（CLI版）

```bash
python cli.py "状況の自然言語説明" [--phase Day1] [--blinds 2000-4000]
```

単一の自然言語でも動くように設計。構造化が必要なら追加プロンプトで聞き返す。

---

## OUTPUT FORMAT

### 標準レスポンス

```json
{
  "situation_summary": "状況の1-2行要約",
  "applicable_rules": [
    {
      "id": "Rule-45",
      "title": "Multiple Chip Betting Using an Overchip",
      "citation": "該当箇所の引用（50-150文字）"
    }
  ],
  "recommended_judgment": "推奨するTD裁定（1-3文）",
  "reasoning": "判断の根拠（ルール解釈+Rule 1原則との接続）",
  "alternatives": [
    {
      "option": "代替案の内容",
      "condition": "この案が適用される条件"
    }
  ],
  "penalty": {
    "level": "none | verbal_warning | missed_hand | missed_round | disqualification",
    "description": "ペナルティの詳細"
  },
  "confirmation_needed": [
    "TDに確認してほしい事実1",
    "事実2"
  ],
  "confidence": "high | medium | low",
  "human_override": "最終判断は現場の人間TDが行うこと"
}
```

### 人間向け整形（Markdown出力）

```markdown
## 🎯 TD判断AI レスポンス

### 📋 状況の要約
[要約]

### ⚖️ 適用ルール
- **Rule-XX**: [タイトル]
  > [該当箇所の引用]

### ✅ 推奨判断
[判断内容]

### 🧠 根拠
[理由]

### 🔄 代替案
（あれば）
- **選択肢A**: [内容] — 条件: [...]

### 🚨 ペナルティ
[該当ペナルティ]

### ❓ 確認事項
- [...]

### 🎚️ 確信度
[high / medium / low]

---
⚠️ **最終判断は現場の人間TDに委ねられます**
© 2024 Poker TDA (https://www.pokertda.com)
```

---

## ERROR HANDLING

### 入力不足の場合
```json
{
  "status": "need_more_info",
  "missing_fields": ["blinds", "game_type"],
  "questions": [
    "ブラインドレベルを教えてください",
    "ゲーム種目（NLHE/PLO等）を教えてください"
  ]
}
```

### ルール未該当の場合
```json
{
  "status": "no_matching_rule",
  "note": "TDAルールに明示的な該当条文がありません",
  "recommendation": "ハウスルールまたはフロア裁量（Rule 1）で判断してください"
}
```

### 矛盾・曖昧な状況
```json
{
  "status": "ambiguous",
  "clarification_needed": "状況の曖昧な点",
  "possible_interpretations": [
    {"interpretation": "...", "implied_judgment": "..."}
  ]
}
```

---

## テストケース例（中野さんから受領予定）

### 例1: Undercall
```
入力:
  blinds: 2000-4000
  prior: UTG bets 12000, BTN calls 8000（誤って少なく）
  question: 差分4000を足させるか、フォールド扱いか

期待出力:
  Rule-52 Undercalls
  判断: The player must make the call of 12,000 full
  根拠: undercallは意図が明確なcallと解釈され、差分を補填
```

### 例2: Angle Shooting
```
入力:
  状況: プレイヤーAが手札を見せる前に「勝った」と宣言し、
        実際には負けていた。他プレイヤーがフォールドした後に発覚。

期待出力:
  Rule-65 Etiquette / Rule 71 Penalty
  判断: 当該ハンドはフォールドしたプレイヤーの手が戻らない
       プレイヤーAに口頭警告、繰り返しならmissed round
  代替案: 状況次第で disqualification（意図的angle shooting）
```

### 例3: Electronic Device
```
入力:
  状況: Day2途中、プレイヤーがライブハンド中にスマホでソルバーを見ていた

期待出力:
  Rule-5D
  判断: 即座にペナルティ（Rule-71）
  推奨ペナルティ: 1 round missed + デバイス没収（次break復帰）
  繰り返しなら disqualification
```

---

## 設計メモ（開発中の判断記録）

- **なぜJSONとMarkdown両方？** → JSONはAPI連携用、Markdownは現場での即時読了用
- **なぜconfidenceを返す？** → グレーゾーンの自己申告で、TD側が裁量を働かせる余地を作る
- **なぜ最後に必ず「人間TDに委ねる」？** → 責任の所在明示・法務リスク低減

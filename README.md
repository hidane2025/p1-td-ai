# TD判断AI — P1事業 差別化武器

> Tournament Director Judgment AI
> P1事業のTD判断を標準化・属人化排除する差別化武器
>
> **成長メカニクス搭載版**: 実戦で使うほど精度が上がる学習ループを Phase 0 から組み込み済み

---

## 🧬 コアコンセプト

**「単なるLLM+ルール参照」は1ヶ月で真似される。しかし「実戦ケース数万件+フィードバック履歴+プロンプト進化ログ」は2年のリードが追いつけない。**

このシステムは最初から**成長する設計**になっています：

```
  判断  →  ログ保存  →  現場TDフィードバック  →  判例自動蓄積
                                 ↓
  プロンプト進化  ←  メトリクス分析  ←  失敗パターン抽出
```

---

## 📁 フォルダ構成

```
TD-AI/
├── README.md                    # 本ファイル
├── data/
│   ├── tda-rules/              # TDA公式ルール（原文・JSON化済み）
│   │   ├── tda_2024_rules_structured.json  # 93項目 (Rule 1-71 + RP 1-22)
│   │   ├── TDA_2024_Rules_FullText.txt     # 原文フルテキスト
│   │   └── tda_2024_illustration_addendum.txt
│   ├── cases/
│   │   └── judgment_cases.json # 判例（初期5件、拡張中）
│   └── td_ai.db                # SQLite: judgments/feedback/versions/cases
├── src/
│   ├── cli.py                  # CLIエントリポイント（サブコマンド方式）
│   ├── judge.py                # 判断ロジック（search+prompt+API）
│   ├── db.py                   # SQLiteデータアクセス層
│   └── metrics.py              # メトリクス・月次レポート生成
├── prompts/
│   ├── system.md               # 最新システムプロンプト（作業用）
│   ├── io_format.md            # 入出力フォーマット定義
│   └── versions/
│       └── system_v0.1.md      # バージョン管理された履歴
└── tests/
    └── run_tests.py            # 判例テストランナー
```

---

## 🚀 Phase 0 セットアップ

```bash
# 1. Python ライブラリ
pip3 install anthropic pypdf

# 2. API キー
export ANTHROPIC_API_KEY=sk-ant-...

# 3. DB 初期化 + 判例シード + プロンプト v0.1 登録
python3 src/cli.py init

# 4. 判断を1件試す
python3 src/cli.py judge "UTG が 10000 bet、BTN が無言で 5,000×2 を出した"

# 5. フィードバックを残す
python3 src/cli.py feedback j_xxxx correct --comment "完璧"

# 6. 対話モード（判断→即フィードバック）
python3 src/cli.py interactive

# 7. メトリクス確認
python3 src/cli.py metrics
```

---

## 📖 CLI コマンドリファレンス

### 初期化

```bash
cli.py init
# - SQLite DB 作成
# - judgment_cases.json から判例をシード
# - prompts/versions/system_v0.1.md をプロンプト v0.1 として登録・有効化
```

### 判断

```bash
cli.py judge "状況..." [--phase Day1] [--blinds 2000-4000] [--game-type NLHE]
cli.py judge --file situation.txt
cli.py judge "..." --prompt-version v0.2   # 特定バージョンで判断（A/Bテスト）
cli.py judge "..." --model claude-opus-4-6  # モデル指定
```

### フィードバック（成長ループの核心）

```bash
# 正しかった
cli.py feedback j_abc123 correct --comment "完璧"

# 部分的に正しい
cli.py feedback j_abc123 partial --comment "ルール引用は正しいが推奨判断が甘い"

# 間違っていた → 正しい判断を記録
cli.py feedback j_abc123 wrong \
  --correct "本件は Rule 52 ではなく Rule 45B 該当" \
  --comment "50% standard の適用ミス" \
  --category "ベッティング関連"
```

**wrong フィードバックを入れると、そのケースを判例DBに追加する案内が出ます。**
この判例はその後の判断で参照され、次第に同種ミスを減らします。

### 一覧・詳細

```bash
cli.py list-judgments --limit 20
cli.py show-judgment j_abc123
cli.py list-cases [--category "ベッティング関連"] [--source mina]
cli.py list-prompts
```

### ケース追加（手動 or 自動フォロー）

```bash
cli.py add-case \
  --source real \
  --category "ベッティング関連" \
  --situation "..." \
  --expected-judgment "..." \
  --expected-rules "Rule-45,Rule-52" \
  --expected-reasoning "..." \
  --derived-from j_abc123  # 元となった判断ID
```

### プロンプト進化

```bash
# 新バージョンを作成
cp prompts/versions/system_v0.1.md prompts/versions/system_v0.2.md
# 手動で編集

# 登録して有効化
python3 -c "
from src.db import register_prompt_version
register_prompt_version(
    version='v0.2',
    path='prompts/versions/system_v0.2.md',
    parent_version='v0.1',
    change_notes='Rule 5 (electronic device) の判断基準を明確化',
    activate=True
)
"

# 切り替え
cli.py activate-prompt v0.1  # ロールバック
cli.py activate-prompt v0.2  # 新版で判断
```

### メトリクス

```bash
cli.py metrics                      # 全期間サマリ
cli.py metrics --month 2026-04      # 月次
cli.py metrics --export report.md   # Markdown 出力
```

---

## 🔄 成長ループの運用フロー

### 週次（現場TD）
1. 実戦で判断AIを使う（`judge`）
2. 判断を見た後、必ず `feedback` を入れる（10秒で済む）
3. 間違いは `wrong` で記録し、正解も入れる

### 月次（運用担当 / ミナ）
1. `cli.py metrics --month YYYY-MM` で月次レポート生成
2. **正答率・苦手Rule・頻出カテゴリ** を確認
3. 苦手パターンを抽出してプロンプト改訂 → 新バージョン登録
4. 新バージョンで直近1週間を A/B テスト
5. 結果良好なら永続切り替え、悪ければロールバック

### 四半期（ミナ＋中野さん）
1. 蓄積判例を Rule 別にレビュー
2. TDA公式ルール改訂時の対応（2025版発表時など）
3. 新機能検討（多言語・音声入力・Slack Bot 等）

---

## 🎯 Phase 0 の成功基準

- [x] TDA 2024年版ルールを完全パース（71 Rules + 22 RPs）
- [x] CLI で動く
- [x] 判断ログ・フィードバック・プロンプト履歴が DB に蓄積
- [x] メトリクス・月次レポートが出る
- [ ] 判例10件中8件以上で「正しい判断」を返す ← API キー設定後テスト
- [ ] 中野さんが「使える」と言う ← 実測

---

## 🔮 Phase 1 以降の展望

### Phase 1（2週間）
- **Vector search RAG**: Supabase Vector に移行、keyword → embedding
- **TDA ルール完全実装**: Illustration Addendum も検索対象に
- **多言語対応**: 英語・韓国語・中国語プロンプト

### Phase 2（2週間）
- **Slack Bot / LINE Bot**: CLIから脱却
- **Web ダッシュボード**: Next.js + Supabase
- **フィードバックUI**: 現場TD向け1タップ評価

### Phase 3（1週間）
- **音声入力**: Whisper API 統合
- **リアルタイム判断**: 大会現場での即時利用

### Phase 4（1週間）
- **国際展開**: APL/USOP/EPT 提供
- **ブランド化**: "P1 TD-AI" 商標出願

### Phase 5（4-8週間）
- **現場β運用**: P1 大会で実測
- **特許出願**: アルゴリズムの知財化

---

## 📚 技術スタック（確定）

- **LLM**: Claude Sonnet 4.5 (Phase 0) → Opus 4.6 for edge cases
- **Language**: Python 3.9+
- **DB (Phase 0)**: SQLite（`data/td_ai.db`）
- **DB (Phase 2+)**: Supabase PostgreSQL（`plsyhqlqiaqatshcoerx`）
- **RAG (Phase 0)**: Keyword search
- **RAG (Phase 1+)**: Supabase Vector + Voyage embeddings
- **Deploy**: Vercel（Web UI）+ Supabase（バックエンド）

---

## ⚖️ 著作権

### TDA ルール使用
```
"TDA rules used by permission of the Poker TDA, Copyright 2024,
https://www.pokertda.com, All rights reserved."
```
出典明記の条件で全文・部分利用・商用利用OK。本プロジェクトのAI組み込みは許諾範囲内。

### 本プロジェクトの知財
- ソースコード: 著作権自動保護
- **アルゴリズム+学習履歴**: 特許出願対象（Phase 1完了後に法務相談）
- ブランド: 「P1 TD-AI」商標出願対象（日本・米国・韓国・マレーシア・中国）

---

## 🚨 既知の制約

1. **事実認定はできない** — AI は「〇〇と主張しているが確認不能」の形で挙げる
2. **ハウスルール依存部分** — 明示的に「ハウスルールに従う」と返す
3. **TDA 2024年版まで** — 2025年以降の改訂は未対応（手動アップデート）
4. **Phase 0 は英語ルール＋日本語プロンプト** — 英文入力は可だが英語出力は未テスト

---

**プロジェクト責任者**: 中野（P1事業責任者）
**AI実装・運用**: 瀬戸ミナ（AI-013）
**開始日**: 2026-04-08

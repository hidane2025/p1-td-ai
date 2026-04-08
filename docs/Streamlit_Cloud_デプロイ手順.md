# Streamlit Cloud デプロイ手順（中野さん専用）

> 2026-04-09 瀬戸ミナ作成
> 所要時間: **10 分**（初回のみ、中野さんの操作が必要な作業）

---

## 🎯 このガイドが終わると何が起きる？

- `https://td-ai-p1.streamlit.app`（※URL は自動生成される）のような URL が発行される
- 中野さんや契約店舗 TD がブラウザでアクセス → パスワード入力 → 使える
- ミナのローカル PC を起動する必要なし（クラウドで 24 時間稼働）

---

## ✅ 事前準備（今やる）

### 1. **新しい Anthropic API Key を発行する**

**セキュリティのため、前回チャットに貼ったキーを破棄して新しいのを作ります**。

1. https://console.anthropic.com/settings/keys を開く
2. 前回のキー（P1-TD-AI 名義）を **Delete**
3. 「Create Key」→ 名前「P1-TD-AI-Production」→ 作成
4. `sk-ant-api03-...` で始まる文字列を**一度だけコピー**（閉じたら 2 度と見られない）
5. どこかに仮で保存（メモ帳等）

### 2. **クレジットを $10 チャージ**

1. https://console.anthropic.com/settings/billing
2. 「Add Credits」→ $10（約 1,500 円）
3. クレカで支払い
4. → これで**1 大会 100 判断 × 3 大会分**をカバー

---

## 🚀 Streamlit Cloud デプロイ手順

### Step 1: Streamlit Cloud アカウント作成（無料・1 分）

1. https://share.streamlit.io/ を開く
2. 「**Continue with GitHub**」をクリック
3. GitHub アカウント（`hidane2025`）でログイン
4. 「Authorize Streamlit Cloud」をクリック
5. アカウント作成完了 ✅

### Step 2: 新しいアプリを作成

ダッシュボードで「**Create app**」→「**Deploy a public app from GitHub**」

以下を入力：

| 項目 | 値 |
|---|---|
| **Repository** | `hidane2025/Hidane-AI` |
| **Branch** | `main` |
| **Main file path** | `AI基盤/TD-AI/ui/app.py` |
| **App URL** | `p1-td-ai`（好きな名前、短い方がよい） |

> ⚠️ **Main file path は正確にコピペしてください**。「AI基盤」は日本語です。

### Step 3: **Secrets を設定**（最重要）

「**Advanced settings**」→「**Secrets**」の欄に、以下を**そのままコピペ**：

```toml
ANTHROPIC_API_KEY = "ここに Step 1 で発行した新しい API Key を貼る"
AUTH_PASSWORD_HASH = "585304184ef262f1aef3e08ce70a9a5a1e7ed014049ee8614e69d2ff78a3f1e0"
```

> 📝 **パスワード**: `P1-TD-2026`（このパスワードで現場 TD がログインします）
>
> 今後変更したい場合は、ミナに「新しいパスワードは○○で」と言えば再計算します。

### Step 4: **Deploy** ボタンを押す

1. 「**Deploy!**」をクリック
2. 待つ（2-5 分）
   - パッケージをインストール中…
   - アプリを起動中…
3. 画面が切り替わって、自動で TD判断AI のログイン画面が表示される

### Step 5: **動作確認**

1. 発行された URL（例: `https://p1-td-ai.streamlit.app`）をブックマーク
2. パスワード `P1-TD-2026` を入力してログイン
3. 試しに判断を 1 つ生成してみる
4. 「動いた」ことを確認

---

## 🎉 完了後にやること

### URL をミナに共有

デプロイ成功したら、生成された URL をミナに教えてください：

```
例: https://p1-td-ai.streamlit.app
```

SESSION_BOARD やメモリに記録します。

### スマホのホーム画面に追加（推奨）

**iPhone Safari の場合**:
1. URL を Safari で開く
2. 下部の共有ボタン（四角+↑）をタップ
3. 「ホーム画面に追加」
4. アイコンがホーム画面に追加される
5. ワンタップで起動できる（アプリ感覚）

### 現場 TD にパスワードを共有

- パスワード: `P1-TD-2026`
- URL: （デプロイで発行されたもの）
- スマホでアクセスすれば即使える

---

## ❓ よくある質問

### Q: GitHub リポジトリが Private なのですが？
A: 問題なし。Streamlit Cloud は Private リポジトリにも対応。OAuth で承認すれば読めます。

### Q: デプロイ中にエラーが出た
A: ほとんどの場合「パッケージのインストール失敗」。時間を置いて再デプロイボタンを押せば解決します。解決しなければスクショをミナに送ってください。

### Q: パスワードを変えたい
A: ミナに「新しいパスワードは○○に変えて」と言えば、新しいハッシュを計算します。それを Streamlit Cloud の Secrets 欄で更新するだけです。

### Q: 複数の TD に別々のパスワードを発行できる？
A: Phase 5 では「1 つのパスワード」方式です。店舗ごとの個別アカウントは Phase 6（本格会員制）で実装します。それまでは中野さんが信頼する TD に共有する運用で。

### Q: 判断データはどこに保存される？
A: Streamlit Cloud のサーバー上の SQLite に保存されます。ただし**Streamlit Cloud の無料プランではサーバー再起動時に消える可能性**があります。永続化は Phase 6 で Supabase 移行で解決します。

### Q: 再デプロイ（コード更新）は？
A: ミナが GitHub に push すると、Streamlit Cloud が自動で再デプロイします。中野さんの操作不要。

---

## 🆘 困ったら

全てのエラー・分からない項目は**スクショを撮ってミナに送る**だけで OK。私が対処します。

---

**ゴール**: 10 分後、中野さんは「URL にアクセスしてパスワード入れるだけ」で TD判断AI を使える状態になります。

あと 10 分、頑張ってください 💪

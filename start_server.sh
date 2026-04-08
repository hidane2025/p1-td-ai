#!/bin/bash
# TD判断AI — 現場用サーバー起動スクリプト
# 使い方: bash start_server.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚖️  TD判断AI — 現場用サーバー起動"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. API Key check (optional .env load)
if [ -z "$ANTHROPIC_API_KEY" ]; then
  if [ -f ".env" ]; then
    echo "📄 .env ファイルから環境変数を読み込みます..."
    set -a
    source .env
    set +a
  fi
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "❌ ANTHROPIC_API_KEY が設定されていません。"
  echo ""
  echo "方法 1: 環境変数で設定"
  echo "   export ANTHROPIC_API_KEY=sk-ant-xxxxx"
  echo ""
  echo "方法 2: .env ファイルを作成"
  echo "   cp .env.example .env"
  echo "   # その後 .env を編集して API Key を記入"
  echo ""
  exit 1
fi

# 2. Dependency check
echo "🔍 依存関係チェック..."
python3 -c "import streamlit, anthropic, sklearn" 2>/dev/null || {
  echo "⚠️  必要なライブラリが不足しています。インストール中..."
  pip3 install streamlit anthropic scikit-learn pypdf --quiet
}

# 3. Initialize DB if not exists
if [ ! -f "data/td_ai.db" ]; then
  echo "🗄️  データベースを初期化します..."
  python3 src/cli.py init
fi

# 4. Get local IP for mobile access
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "不明")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ サーバーを起動します"
echo ""
echo "📍 アクセス URL:"
echo "   PC:     http://localhost:8501"
if [ "$LOCAL_IP" != "不明" ]; then
  echo "   スマホ: http://$LOCAL_IP:8501"
fi
echo ""
echo "🛑 停止: Ctrl+C"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 5. Start Streamlit
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
streamlit run ui/app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --browser.gatherUsageStats false \
  --server.headless false

#!/usr/bin/env python3
"""
TD判断AI — 現場用 Web UI (Streamlit) v0.4 Phase 7C

現場の TD・フロアスタッフがスマホ or PC から使えるシンプルな Web UI。

## 起動方法
    export ANTHROPIC_API_KEY=sk-ant-...
    cd AI基盤/TD-AI
    streamlit run ui/app.py

## ブラウザでアクセス
    ローカル: http://localhost:8501
    同一ネットワーク: http://[PCのIP]:8501
    （スマホからもアクセス可能）
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

# Path setup
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from judge import judge  # noqa: E402

# Phase 7A: db モジュールを importlib で明示リロード
# Streamlit Cloud のモジュールキャッシュ対策
import importlib
import db as _db_module  # noqa: E402
importlib.reload(_db_module)

init_db = _db_module.init_db
save_feedback = _db_module.save_feedback
list_recent_judgments = _db_module.list_recent_judgments
get_judgment = _db_module.get_judgment
get_feedback_for_judgment = _db_module.get_feedback_for_judgment
list_prompt_versions = _db_module.list_prompt_versions
get_active_prompt_version = _db_module.get_active_prompt_version

# Phase 7B: DB 永続化対策関数（なければダミー）
count_judgments = getattr(_db_module, "count_judgments", lambda: 0)
count_feedback = getattr(_db_module, "count_feedback", lambda: 0)
export_all_judgments = getattr(
    _db_module, "export_all_judgments",
    lambda: {"judgments": [], "feedback": [], "prompt_versions": []}
)
import_judgments_dump = getattr(
    _db_module, "import_judgments_dump",
    lambda dump: (0, 0)
)

# search_judgments は Phase 7A で追加。古い DB モジュールでも動くようフォールバック
if hasattr(_db_module, "search_judgments"):
    search_judgments = _db_module.search_judgments
else:
    def search_judgments(keyword=None, confidence=None, rule_id=None, limit=200):
        """フォールバック: DB モジュールが古い場合の代替実装"""
        import sqlite3
        import json as _json
        db_path = BASE_DIR / "data" / "td_ai.db"
        if not db_path.exists():
            return []
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            query = (
                "SELECT id, created_at, situation, confidence, prompt_version, "
                "referenced_rules, response_text FROM judgments WHERE 1=1"
            )
            params = []
            if keyword:
                query += " AND (situation LIKE ? OR response_text LIKE ?)"
                like = f"%{keyword}%"
                params.extend([like, like])
            if confidence:
                query += " AND confidence = ?"
                params.append(confidence)
            if rule_id:
                query += " AND referenced_rules LIKE ?"
                params.append(f"%{rule_id}%")
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

from evaluator import evaluate  # noqa: E402


# ===== HTML rendering helper =====
def _render_html(html: str) -> None:
    """Streamlit Markdown の 4 スペース=コードブロック誤認を回避する安全 HTML レンダー"""
    dedented = textwrap.dedent(html).strip()
    collapsed = re.sub(r"\n\s*", "", dedented)
    st.markdown(collapsed, unsafe_allow_html=True)


# ===== TDA 英語原文ロード =====
@st.cache_data
def load_tda_rules() -> dict[str, dict]:
    """
    data/tda-rules/tda_2024_rules_structured.json を読み込み、
    rule_id → { title, body } の辞書を返す。
    """
    rules_path = BASE_DIR / "data" / "tda-rules" / "tda_2024_rules_structured.json"
    if not rules_path.exists():
        return {}
    with open(rules_path, "r", encoding="utf-8") as f:
        rules_list = json.load(f)
    return {r["id"]: r for r in rules_list}


# ===== 判断レスポンスのセクション抽出 =====
def parse_judgment_sections(response_text: str) -> dict[str, str]:
    """AI 応答テキストから主要セクションを抽出する (v0.3 format)"""
    sections: dict[str, str] = {}

    m = re.search(r"【推奨判断】\s*\n+([\s\S]*?)(?=\n【|\Z)", response_text)
    if m:
        sections["conclusion"] = m.group(1).strip()

    m = re.search(r"【適用ルール】\s*\n+([\s\S]*?)(?=\n【|\Z)", response_text)
    if m:
        rules_block = m.group(1).strip()
        first_line = rules_block.split("\n")[0].strip()
        cleaned = re.sub(r"^[-・•]\s*", "", first_line).strip()
        cleaned = cleaned.replace("**", "").strip()
        cleaned = re.sub(r"[(\(（]主要[）)\)]", "", cleaned).strip()
        sections["main_rule"] = cleaned

    m = re.search(r"【根拠】\s*\n+([\s\S]*?)(?=\n【|\Z)", response_text)
    if m:
        sections["reason"] = m.group(1).strip()

    m = re.search(r"【ペナルティ】[^\n]*\n+([\s\S]*?)(?=\n【|\Z)", response_text)
    if m:
        pen = m.group(1).strip()
        if pen and pen != "なし":
            sections["penalty"] = pen

    return sections


# ===== 🔐 会員制認証 + 4時間セッション =====
AUTH_TIMEOUT_HOURS = 4  # Phase 7A: セッション 4 時間に延長


def _get_password_hash() -> str | None:
    try:
        if hasattr(st, "secrets") and "AUTH_PASSWORD_HASH" in st.secrets:
            return st.secrets["AUTH_PASSWORD_HASH"]
    except Exception:
        pass
    return os.environ.get("AUTH_PASSWORD_HASH")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def check_auth() -> bool:
    password_hash = _get_password_hash()
    if not password_hash:
        return True

    # Phase 7A: セッション有効期限チェック
    if st.session_state.get("authenticated", False):
        auth_time_str = st.session_state.get("auth_time")
        if auth_time_str:
            try:
                auth_time = datetime.fromisoformat(auth_time_str)
                if datetime.now() - auth_time < timedelta(hours=AUTH_TIMEOUT_HOURS):
                    return True
                # 期限切れ
                st.session_state.authenticated = False
                st.session_state.pop("auth_time", None)
            except Exception:
                st.session_state.authenticated = False

    st.set_page_config(
        page_title="TD判断AI — ログイン",
        page_icon="🔐",
        layout="centered",
    )

    st.markdown("# 🔐 TD判断AI")
    st.markdown("P1事業 契約店舗向け")
    st.markdown("---")

    with st.form("login_form"):
        password = st.text_input(
            "パスワード",
            type="password",
            placeholder="契約時にお伝えしたパスワード",
        )
        login = st.form_submit_button("ログイン", type="primary", use_container_width=True)

    if login:
        if _hash_password(password) == password_hash:
            st.session_state.authenticated = True
            st.session_state.auth_time = datetime.now().isoformat()
            st.rerun()
        else:
            st.error("❌ パスワードが違います")

    st.markdown("---")
    st.caption(
        "このシステムは P1 事業と契約した店舗・TD のみアクセス可能です。"
        " パスワードをお持ちでない方は中野までお問い合わせください。"
    )
    st.caption(f"© 2024 Poker TDA. TD判断AI v0.4 — P1 Tournament Director Advisor")
    st.caption(f"セッション有効期限: {AUTH_TIMEOUT_HOURS} 時間（試合中は切断されません）")
    return False


# === 認証チェック ===
if not check_auth():
    st.stop()


# ===== Page Config =====
st.set_page_config(
    page_title="TD判断AI — P1事業",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="auto",  # Phase 7B: PCは開、スマホは閉
)

# ===== Custom CSS (Phase 7A: スマホ縦画面対応) =====
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1a1a1a;
        margin-bottom: 0;
    }
    .subtitle {
        font-size: 1rem;
        color: #666;
        margin-top: 0;
        margin-bottom: 1.5rem;
    }
    .judgment-container {
        padding: 1rem;
        border-radius: 8px;
        background: #f9f9f9;
        border-left: 4px solid #FF6B35;
        margin-top: 1rem;
    }
    .metric-card {
        padding: 0.8rem;
        background: #fff;
        border-radius: 6px;
        border: 1px solid #e0e0e0;
        text-align: center;
    }
    .footer {
        margin-top: 3rem;
        padding-top: 1rem;
        border-top: 1px solid #e0e0e0;
        color: #999;
        font-size: 0.85rem;
        text-align: center;
    }
    .warning-banner {
        padding: 0.8rem;
        background: #fff3cd;
        border-left: 4px solid #ffc107;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    /* Quick template buttons */
    .stButton > button {
        min-height: 44px;  /* Touch target */
        font-size: 0.9rem;
    }
    /* Mobile 対応: 縦画面でカラムを積み上げる */
    @media (max-width: 640px) {
        .main-title {
            font-size: 1.6rem;
        }
        .subtitle {
            font-size: 0.85rem;
        }
        div[data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            margin-bottom: 0.4rem;
        }
        .stButton > button {
            min-height: 48px !important;
            font-size: 1rem !important;
        }
        textarea {
            font-size: 16px !important; /* iOS zoom 防止 */
        }
        input[type="text"],
        input[type="password"] {
            font-size: 16px !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ===== Initialize DB =====
init_db()

# ===== Header =====
st.markdown('<div class="main-title">⚖️ TD判断AI</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">P1事業 — Tournament Director 判断支援システム / TDA 2024準拠 / v0.4</div>',
    unsafe_allow_html=True,
)

# ===== Check API Key =====
if not os.environ.get("ANTHROPIC_API_KEY"):
    try:
        if hasattr(st, "secrets") and "ANTHROPIC_API_KEY" in st.secrets:
            os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.error(
        "❌ システム設定エラー: API Key が設定されていません。\n\n"
        "管理者（中野）にお問い合わせください。"
    )
    st.stop()

# ===== Session state =====
if "last_judgment" not in st.session_state:
    st.session_state.last_judgment = None
if "feedback_submitted" not in st.session_state:
    st.session_state.feedback_submitted = {}
if "situation_input" not in st.session_state:
    st.session_state.situation_input = ""

# ===== Sidebar: Settings and History =====
with st.sidebar:
    if _get_password_hash():
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.markdown("#### 👤 ログイン中")
        with col_b:
            if st.button("🚪", key="logout_btn", help="ログアウト"):
                st.session_state.authenticated = False
                st.rerun()

        # セッション残時間表示
        auth_time_str = st.session_state.get("auth_time")
        if auth_time_str:
            try:
                auth_time = datetime.fromisoformat(auth_time_str)
                remaining = timedelta(hours=AUTH_TIMEOUT_HOURS) - (datetime.now() - auth_time)
                if remaining.total_seconds() > 0:
                    hours = int(remaining.total_seconds() // 3600)
                    minutes = int((remaining.total_seconds() % 3600) // 60)
                    st.caption(f"⏱️ セッション残: {hours}h {minutes}m")
            except Exception:
                pass
        st.markdown("---")

    st.markdown("### ⚙️ 設定")

    active_version = get_active_prompt_version()
    current_version = active_version["version"] if active_version else "v0.3"

    versions = list_prompt_versions()
    version_options = [v["version"] for v in versions] if versions else ["v0.3"]

    selected_version = st.selectbox(
        "プロンプトバージョン",
        options=version_options,
        index=version_options.index(current_version) if current_version in version_options else 0,
    )

    st.markdown("---")
    st.markdown("### 💾 DB バックアップ")
    st.caption("⚠️ Streamlit Cloud は再起動時に DB が消える可能性があります。定期的にエクスポートしてください。")

    try:
        _jc = count_judgments()
        _fc = count_feedback()
        st.caption(f"📊 現在: 判断 {_jc} 件 / フィードバック {_fc} 件")
    except Exception:
        _jc = 0
        _fc = 0

    try:
        _dump = export_all_judgments()
        _dump_bytes = json.dumps(_dump, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "📥 全データを JSON でダウンロード",
            data=_dump_bytes,
            file_name=f"td_ai_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
            help="全判断・フィードバック・プロンプトをバックアップ",
        )
    except Exception as e:
        st.caption(f"エクスポート準備エラー: {e}")

    _restore_file = st.file_uploader(
        "📤 バックアップを復元",
        type=["json"],
        key="restore_upload",
        help="DBが消えた時に、ダウンロードしたJSONをアップロードして復元",
    )
    if _restore_file is not None:
        try:
            _restore_dump = json.loads(_restore_file.read().decode("utf-8"))
            j_added, f_added = import_judgments_dump(_restore_dump)
            st.success(f"✅ 復元完了: 判断 {j_added} 件 / FB {f_added} 件を追加")
        except Exception as e:
            st.error(f"復元エラー: {e}")

    st.markdown("---")
    st.markdown("### 📊 直近の判断")

    recent = list_recent_judgments(limit=10)
    if recent:
        for r in recent:
            with st.expander(
                f"🕐 {r['created_at'][:16]} — {r['situation'][:30]}..."
            ):
                st.text(f"ID: {r['id']}")
                st.text(f"Version: {r['prompt_version']}")
                st.text(f"Confidence: {r['confidence'] or '?'}")
                if st.button("詳細", key=f"detail_{r['id']}"):
                    detail = get_judgment(r["id"])
                    if detail:
                        st.session_state.last_judgment = {
                            "judgment_id": detail["id"],
                            "response": detail["response_text"],
                            "prompt_version": detail["prompt_version"],
                            "model": detail["model"],
                            "latency_ms": detail["latency_ms"] or 0,
                            "confidence": detail["confidence"],
                            "token_usage": json.loads(detail["token_usage"]) if detail["token_usage"] else {},
                            "referenced_rules_context": json.loads(detail["referenced_rules"]) if detail["referenced_rules"] else [],
                        }
                        st.rerun()
    else:
        st.caption("まだ判断履歴はありません")


# ===== Tabs: 判断 / 履歴検索 =====
tab_judge, tab_search = st.tabs(["⚖️ 判断を取得", "📚 判断履歴検索"])

# =========================================================================
# TAB 1: 判断を取得（クイックテンプレ + フォーム）
# =========================================================================
with tab_judge:
    # ===== ⚡ ワンタップテンプレ 20 種 =====
    st.markdown("#### ⚡ クイック選択（タップで入力欄にテンプレが入ります）")

    # Phase 7B: 軽量フレーム化 — ○ プレースホルダー撤廃
    # 各テンプレは「状況の枠組み + 確認すべきポイント」だけ。
    # 具体数値は TD が自由記述で追加する方式（入力が早い & 間違えにくい）
    QUICK_TEMPLATES = [
        # ベッティング関連
        ("💰 OOT fold",
         "状況: プレイヤーが順番前に fold を宣言した（OOT fold）。その後、前のアクションが変更された可能性あり。\n\n"
         "確認すべき点:\n"
         "- スキップされたプレイヤーは誰か\n"
         "- OOT 後にアクションが変わったか\n"
         "- この OOT fold は binding するか（Rule 53A）"),
        ("💰 アンダーコール",
         "状況: プレイヤーが無言で、コール額より少ない額のチップを押し出した（アンダーコール）。\n\n"
         "確認すべき点:\n"
         "- コール額はいくらか\n"
         "- 実際に出されたチップ額はいくらか\n"
         "- 発言はあったか（Rule 52 該当）"),
        ("💰 Multi-chip bet",
         "状況: プレイヤーが無言で複数枚のチップを押し出した（合計額が不明瞭）。\n\n"
         "確認すべき点:\n"
         "- コール額はいくらか\n"
         "- 出されたチップの内訳（デノミ×枚数）\n"
         "- 最小チップ 1 枚を引いた額が call 額未満か（Rule 45A）"),
        ("💰 String bet",
         "状況: プレイヤーが「raise」と宣言せず、チップを 2 回以上に分けて前に出した。\n\n"
         "確認すべき点:\n"
         "- call 額はいくらか\n"
         "- 1 回目と 2 回目の間隔\n"
         "- 宣言の有無（Rule 42/44）"),
        ("💰 Oversized chip",
         "状況: コール額に対して、プレイヤーが無言で大きな単一デノミのチップ 1 枚だけを出した（オーバーチップ）。\n\n"
         "確認すべき点:\n"
         "- コール額とチップ額の比率\n"
         "- 発言の有無（Rule 44）"),
        # 誤配
        ("🃏 Misdeal カード露出",
         "状況: Preflop dealing 中、ディーラーがカードを表向きに露出してしまった。\n\n"
         "確認すべき点:\n"
         "- 何枚目（何人目）のカードか\n"
         "- プレイヤーがそのカードを見たか\n"
         "- まだアクション前か（Rule 35/37）"),
        ("🃏 スキップ配",
         "状況: ディーラーがプレイヤーを飛ばしてカードを配り始めた。\n\n"
         "確認すべき点:\n"
         "- 何人飛ばされたか\n"
         "- いつ気づいたか\n"
         "- SA（Substantial Action）成立前か（Rule 35/36）"),
        # ショーダウン
        ("🎴 Muck 前 showdown",
         "状況: River action 完了後、last aggressor が muck しようとしている（相手のカードはまだ非公開）。\n\n"
         "確認すべき点:\n"
         "- 誰が last aggressor か\n"
         "- All-in か否か（Rule 16）"),
        ("🎴 Raise then muck",
         "状況: プレイヤーが raise した後、call を待たずに自ら muck してしまった。\n\n"
         "確認すべき点:\n"
         "- raise 額\n"
         "- その時点で call したプレイヤーはいるか\n"
         "- Rule 65A（Raise then muck return）該当"),
        ("🎴 All-in face up",
         "状況: プレイヤーが all-in で call された後、showdown でカードを見せずに muck しようとしている。\n\n"
         "確認すべき点:\n"
         "- 全員 all-in か\n"
         "- Rule 16 により muck 不可"),
        # 電子機器
        ("📱 Phone at table",
         "状況: プレイヤーがライブハンド中に携帯電話を操作した。\n\n"
         "確認すべき点:\n"
         "- 通話か画面操作か\n"
         "- 何を操作したか\n"
         "- 累積ペナルティ数（Rule 5C）"),
        ("📱 Solver 疑惑",
         "状況: プレイヤーがハンド中に戦略ツール（ソルバー / アプリ / チャート）を参照した疑い。\n\n"
         "確認すべき点:\n"
         "- 何のツールか\n"
         "- 証拠の有無\n"
         "- ハンド進行中か（Rule 5D — 2024 改訂で DQ レベル）"),
        # プレイヤー行為
        ("⚠️ Collusion 疑惑",
         "状況: 特定のプレイヤー同士で、chip dumping / soft play の疑われる行動パターンが繰り返された。\n\n"
         "確認すべき点:\n"
         "- 具体的なパターンと回数\n"
         "- 証拠の強さ\n"
         "- 関係性（同国籍 / 同宿泊 等）"),
        ("⚠️ Soft play",
         "状況: 親しい 2 人のプレイヤーが対戦時、明らかに互いを避けている（check it down 等）。\n\n"
         "確認すべき点:\n"
         "- 関係性\n"
         "- パターン頻度\n"
         "- 他プレイヤーへの影響（Rule 71）"),
        ("⚠️ Dodging blinds",
         "状況: プレイヤーが BB 直前で繰り返し席を立ち、BB ポジションを回避している疑い。\n\n"
         "確認すべき点:\n"
         "- 連続回数\n"
         "- 体調不良か意図的か（Rule 33/71）"),
        # チップ管理
        ("🔢 Pocket chips",
         "状況: プレイヤーがチップをポケットやカバン等、テーブルから見えない場所に移動させた。\n\n"
         "確認すべき点:\n"
         "- 意図的か\n"
         "- チップの額（Rule 63 — 没収対象）"),
        ("🔢 Chip race",
         "状況: Chip race で最小デノミが廃止される際、プレイヤーが raced out になりそう。\n\n"
         "確認すべき点:\n"
         "- 残チップ数\n"
         "- Rule 24A の「最後 1 チップは raced out 禁止」該当"),
        # トーナメント構造
        ("⏰ Clock call",
         "状況: プレイヤーが長考中、他プレイヤーがクロックを要求（25 秒 + 10 秒カウントダウン）。\n\n"
         "確認すべき点:\n"
         "- すでに何秒経過しているか\n"
         "- 時間切れ寸前の action 判定（Rule 29/30）"),
        ("⏰ Dead button",
         "状況: プレイヤーが bust out した次のハンドで、ボタン位置の進行が不明。\n\n"
         "確認すべき点:\n"
         "- bust したポジション\n"
         "- 現在のブラインド順（Rule 32 dead button）"),
        ("⏰ Late reg cap",
         "状況: Late reg 最終レベルで受付処理中にレベルアップした。\n\n"
         "確認すべき点:\n"
         "- seat card を打ったか\n"
         "- チップを置いたか\n"
         "- 受付完了の定義（Rule 8）"),
    ]

    # 5 列 × 4 行で配置
    template_cols_per_row = 5
    for i in range(0, len(QUICK_TEMPLATES), template_cols_per_row):
        cols = st.columns(template_cols_per_row)
        for j, (label, template_text) in enumerate(QUICK_TEMPLATES[i:i + template_cols_per_row]):
            with cols[j]:
                if st.button(label, key=f"qt_{i+j}", use_container_width=True):
                    st.session_state.situation_input = template_text
                    st.rerun()

    st.markdown("---")
    st.markdown("### 📝 状況の入力")

    with st.form("judgment_form", clear_on_submit=False):
        situation = st.text_area(
            "状況の詳細を入力してください",
            value=st.session_state.situation_input,
            height=180,
            placeholder="例: Day 1 後半、NLHE、Blinds 2,000-4,000。UTG が 12,000 オープン、CO が無言で 5,000×2+1,000×2 = 12,000 を押し出した。これは call か raise か？",
            help="実際の状況を自然な日本語で入力してください。プレイヤー位置、ブラインド、アクション履歴を含めると精度が上がります。",
            key="situation_textarea",
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            tournament_phase = st.text_input(
                "トーナメントフェーズ (任意)",
                placeholder="例: Day 1 後半 / Final Table",
            )
        with col2:
            blinds = st.text_input(
                "ブラインド (任意)",
                placeholder="例: 2,000-4,000 BBA 4,000",
            )
        with col3:
            game_type = st.selectbox(
                "ゲーム種目",
                options=["", "NLHE", "PLO", "HORSE", "Stud", "Razz"],
                index=1,
            )

        submitted = st.form_submit_button(
            "⚖️ 判断を取得",
            use_container_width=True,
            type="primary",
        )

    if submitted:
        if not situation.strip():
            st.warning("状況を入力してください")
            st.stop()

        with st.spinner("AI が判断を生成中...（約 30-60 秒、初回は少し長め）"):
            extra = {}
            if tournament_phase:
                extra["tournament_phase"] = tournament_phase
            if blinds:
                extra["blinds"] = blinds
            if game_type:
                extra["game_type"] = game_type

            try:
                result = judge(
                    situation=situation.strip(),
                    extra_context=extra or None,
                    prompt_version=selected_version,
                )
                st.session_state.last_judgment = result
                st.session_state.feedback_submitted[result["judgment_id"]] = False
                # テンプレ再表示防止
                st.session_state.situation_input = ""
            except Exception as e:
                st.error(f"判断生成中にエラー: {e}")
                st.stop()

    # ===== Display result =====
    if st.session_state.last_judgment:
        result = st.session_state.last_judgment

        st.markdown("---")

        # Parse
        sections = parse_judgment_sections(result["response"])
        conclusion = sections.get("conclusion", "").strip()
        main_rule = sections.get("main_rule", "").strip()
        reason = sections.get("reason", "").strip()
        penalty = sections.get("penalty", "").strip()
        confidence = result.get("confidence") or "—"

        # 1行目: 判断
        if conclusion:
            _render_html(f"""
                <div style="padding:1.2rem 1.4rem;border-radius:10px;background:linear-gradient(135deg,#FFF4ED 0%,#FFE8D6 100%);border-left:6px solid #FF6B35;margin-bottom:0.6rem;">
                  <div style="font-size:0.85rem;color:#8B4513;font-weight:600;margin-bottom:0.3rem;">⚖️ 推奨判断</div>
                  <div style="font-size:1.25rem;font-weight:700;color:#1a1a1a;line-height:1.5;">{conclusion}</div>
                </div>
            """)
        else:
            st.warning("判断セクションを抽出できませんでした。生の応答を表示します。")

        # 2行目: 主要ルール
        if main_rule:
            _render_html(f"""
                <div style="padding:0.7rem 1rem;border-radius:6px;background:#F0F8FF;border-left:4px solid #4A90E2;margin-bottom:0.6rem;">
                  <span style="font-size:0.9rem;color:#2E4A66;">📖 <b>適用ルール</b>: {main_rule}</span>
                </div>
            """)

        # 確信度バッジ
        conf_bg = (
            "#E8F5E9" if confidence == "high"
            else "#FFF8E1" if confidence == "medium"
            else "#FFEBEE"
        )
        conf_fg = (
            "#2E7D32" if confidence == "high"
            else "#F57C00" if confidence == "medium"
            else "#C62828"
        )
        conf_badge = (
            f'<span style="padding:0.3rem 0.8rem;background:{conf_bg};'
            f'border-radius:20px;font-size:0.85rem;color:{conf_fg};'
            f'font-weight:600;margin-right:0.5rem;">🎚️ 確信度: {confidence}</span>'
        )
        st.markdown(
            f'<div style="margin-bottom:1rem;">{conf_badge}</div>',
            unsafe_allow_html=True,
        )

        # ペナルティ
        if penalty:
            penalty_oneline = " ・ ".join(
                line.strip() for line in penalty.split("\n") if line.strip()
            )
            _render_html(f"""
                <div style="padding:0.7rem 1rem;border-radius:6px;background:#FFEBEE;border-left:4px solid #C62828;margin-bottom:1rem;font-size:0.9rem;color:#8B0000;">
                  ⚠️ <b>ペナルティ</b>: {penalty_oneline}
                </div>
            """)

        # ===== Phase 7B: 即時アクション行（上位配置） =====
        # B-3: 新しい判断 + コピー、Hidden #11: FB ボタン即横
        already_submitted_top = st.session_state.feedback_submitted.get(
            result["judgment_id"], False
        )
        jid = result["judgment_id"]

        action_cols = st.columns([1, 1, 1, 1, 1, 1])
        with action_cols[0]:
            if st.button("🔄 新しい判断", key=f"new_judgment_top_{jid}", use_container_width=True, help="状況をクリアして次の判断へ"):
                st.session_state.last_judgment = None
                st.session_state.situation_input = ""
                st.rerun()
        with action_cols[1]:
            # コピー用: プレイヤー説明のショート版を生成
            copy_text = f"【TD判断】{conclusion}"
            if main_rule:
                copy_text += f"\n【適用ルール】{main_rule}"
            if penalty:
                copy_text += f"\n【ペナルティ】{penalty.splitlines()[0] if penalty else ''}"
            copy_text += f"\n\n(TD判断AI v0.3 より / TDA 2024準拠)"
            if st.button("📋 コピー用", key=f"copy_btn_{jid}", use_container_width=True, help="判断テキストを表示してコピー可"):
                st.session_state[f"show_copy_{jid}"] = True

        # フィードバックボタンを即横に
        with action_cols[2]:
            if already_submitted_top:
                st.caption("✅ 保存済")
            else:
                if st.button("✅ 正しい", key=f"fb_top_correct_{jid}", use_container_width=True):
                    save_feedback(
                        judgment_id=jid,
                        rating="correct",
                        comment="UIから（上位FB）",
                        reviewer="field_ui",
                    )
                    st.session_state.feedback_submitted[jid] = True
                    st.rerun()
        with action_cols[3]:
            if not already_submitted_top:
                if st.button("🟡 部分的", key=f"fb_top_partial_{jid}", use_container_width=True):
                    save_feedback(
                        judgment_id=jid,
                        rating="partial",
                        comment="UIから（上位FB）",
                        reviewer="field_ui",
                    )
                    st.session_state.feedback_submitted[jid] = True
                    st.rerun()
        with action_cols[4]:
            if not already_submitted_top:
                if st.button("❌ 間違い", key=f"fb_top_wrong_{jid}", use_container_width=True):
                    save_feedback(
                        judgment_id=jid,
                        rating="wrong",
                        comment="UIから（上位FB）",
                        reviewer="field_ui",
                    )
                    st.session_state.feedback_submitted[jid] = True
                    st.rerun()

        # コピー用テキスト表示（押されたら）
        if st.session_state.get(f"show_copy_{jid}"):
            st.code(copy_text, language=None)
            st.caption("☝️ 右上のコピーアイコンでテキストをクリップボードへコピーできます")

        # 詳細折りたたみ
        with st.expander("🔽 詳細（根拠・補足・全文）を見る"):
            if reason:
                st.markdown("**📌 根拠**")
                st.markdown(reason)
                st.markdown("---")
            st.markdown("**📄 全文**")
            st.markdown(result["response"])

        # ===== 📜 TDA 英語原文（Phase 7A Task 2） =====
        with st.expander("📜 TDA 英語原文（引用ルール）", expanded=False):
            rules_map = load_tda_rules()
            ref_rules = result.get("referenced_rules_context", [])

            # レスポンス中に登場したルールも追加
            response_rules = result.get("referenced_rules_response", [])
            all_refs = list(dict.fromkeys(ref_rules + response_rules))[:5]

            if not all_refs:
                st.caption("引用されたルール情報がありません。")
            else:
                for rid in all_refs:
                    rule = rules_map.get(rid)
                    if rule:
                        st.markdown(f"### {rule['id']}: {rule.get('title', '')}")
                        body = rule.get("body", "")
                        # 長すぎる場合は折りたたみ
                        if len(body) > 800:
                            st.markdown(body[:800] + "...")
                            with st.expander(f"{rid} 全文"):
                                st.markdown(body)
                        else:
                            st.markdown(body)
                        st.markdown("---")

            st.caption(
                "💡 プレイヤーへの説明時はこの英語原文をコピーして見せると効果的です。"
            )

        # 免責事項
        st.caption(
            "⚠️ 最終判断は現場の人間 TD に委ねられます。AI は「推奨」を提示するのみです。"
        )

        # メトリクス
        with st.expander("📊 判断メタデータ（確認用）"):
            mcol1, mcol2, mcol3, mcol4 = st.columns(4)
            with mcol1:
                st.metric("確信度", result.get("confidence") or "—")
            with mcol2:
                latency = result.get("latency_ms") or result.get("total_latency_ms") or 0
                st.metric("応答時間", f"{latency/1000:.1f}s")
            with mcol3:
                tok = result.get("token_usage", {})
                st.metric("tokens", f"in={tok.get('input',0)} out={tok.get('output',0)}")
            with mcol4:
                cost_in = tok.get("input", 0) / 1e6 * 3.0
                cost_out = tok.get("output", 0) / 1e6 * 15.0
                cost_cache = tok.get("cache_read", 0) / 1e6 * 0.30
                cost_cache_w = tok.get("cache_creation", 0) / 1e6 * 3.75
                cost_total = cost_in + cost_out + cost_cache + cost_cache_w
                cost_jpy = cost_total * 150
                st.metric("コスト", f"約 {cost_jpy:.1f}円")

            st.json(
                {
                    "judgment_id": result["judgment_id"],
                    "prompt_version": result.get("prompt_version"),
                    "model": result.get("model"),
                    "cache_hit": result.get("cache_hit", False),
                    "referenced_rules": result.get("referenced_rules_context", []),
                    "response_rules": result.get("referenced_rules_response", []),
                }
            )

        # フィードバック
        st.markdown("---")
        st.markdown("### 📮 この判断はどうでしたか？")

        already_submitted = st.session_state.feedback_submitted.get(
            result["judgment_id"], False
        )

        if already_submitted:
            st.success("✅ フィードバックを記録しました。ありがとうございます！")
        else:
            fcol1, fcol2, fcol3, _ = st.columns([1, 1, 1, 2])
            with fcol1:
                if st.button("✅ 正しい", key=f"fb_correct_{result['judgment_id']}", use_container_width=True):
                    save_feedback(
                        judgment_id=result["judgment_id"],
                        rating="correct",
                        comment="UIから",
                        reviewer="field_ui",
                    )
                    st.session_state.feedback_submitted[result["judgment_id"]] = True
                    st.rerun()
            with fcol2:
                if st.button("🟡 部分的", key=f"fb_partial_{result['judgment_id']}", use_container_width=True):
                    save_feedback(
                        judgment_id=result["judgment_id"],
                        rating="partial",
                        comment="UIから",
                        reviewer="field_ui",
                    )
                    st.session_state.feedback_submitted[result["judgment_id"]] = True
                    st.rerun()
            with fcol3:
                if st.button("❌ 間違い", key=f"fb_wrong_{result['judgment_id']}", use_container_width=True):
                    save_feedback(
                        judgment_id=result["judgment_id"],
                        rating="wrong",
                        comment="UIから",
                        reviewer="field_ui",
                    )
                    st.session_state.feedback_submitted[result["judgment_id"]] = True
                    st.rerun()

            with st.expander("💬 詳細コメントを追加（任意）"):
                comment = st.text_input(
                    "コメント",
                    key=f"comment_{result['judgment_id']}",
                    placeholder="現場の実際の判断との差異、改善点など",
                )
                correct_judgment = st.text_input(
                    "正しい判断（間違い/部分的の場合）",
                    key=f"correct_{result['judgment_id']}",
                    placeholder="実際の TD はどう判断したか",
                )
                reviewer = st.text_input(
                    "入力者名",
                    key=f"reviewer_{result['judgment_id']}",
                    placeholder="中野 / TD名など",
                )
                if st.button("💾 コメント付きで保存", key=f"save_comment_{result['judgment_id']}"):
                    save_feedback(
                        judgment_id=result["judgment_id"],
                        rating="partial",
                        correct_judgment=correct_judgment or None,
                        comment=comment or None,
                        reviewer=reviewer or "field_ui",
                    )
                    st.session_state.feedback_submitted[result["judgment_id"]] = True
                    st.rerun()


# =========================================================================
# TAB 2: 判断履歴検索（Phase 7A Task 5）
# =========================================================================
with tab_search:
    st.markdown("### 📚 判断履歴検索")
    st.caption("過去の判断を全件検索。「先週の misdeal 判断もう一度見たい」に対応。")

    search_col1, search_col2, search_col3 = st.columns([3, 1, 1])
    with search_col1:
        search_keyword = st.text_input(
            "🔍 キーワード",
            placeholder="例: misdeal / muck / Negreanu / 75,000",
            key="search_kw",
        )
    with search_col2:
        search_confidence = st.selectbox(
            "確信度",
            options=["(すべて)", "high", "medium", "low"],
            key="search_conf",
        )
    with search_col3:
        search_rule = st.text_input(
            "ルール ID",
            placeholder="Rule-45",
            key="search_rule",
        )

    if st.button("🔍 検索", type="primary", use_container_width=True):
        st.session_state.search_triggered = True

    if st.session_state.get("search_triggered"):
        kw = search_keyword.strip() or None
        conf = None if search_confidence == "(すべて)" else search_confidence
        rid = search_rule.strip() or None

        try:
            results = search_judgments(
                keyword=kw,
                confidence=conf,
                rule_id=rid,
                limit=200,
            )
        except Exception as e:
            st.error(f"検索エラー: {e}")
            results = []

        st.markdown(f"**ヒット数: {len(results)} 件**")

        if not results:
            st.info("該当する判断が見つかりませんでした。")
        else:
            for r in results:
                with st.expander(
                    f"🕐 {r['created_at'][:16]} — "
                    f"[{r.get('confidence') or '?'}] {r['situation'][:50]}..."
                ):
                    st.markdown(f"**ID**: `{r['id']}`")
                    st.markdown(f"**Prompt**: {r.get('prompt_version', '?')}")
                    st.markdown(f"**確信度**: {r.get('confidence') or '—'}")

                    ref_rules = r.get("referenced_rules")
                    if ref_rules:
                        try:
                            rules_list = json.loads(ref_rules)
                            st.markdown(f"**参照ルール**: {', '.join(rules_list[:5])}")
                        except Exception:
                            pass

                    st.markdown("**状況**:")
                    st.text(r["situation"])

                    st.markdown("**判断レスポンス**:")
                    st.markdown(r.get("response_text", "(なし)"))

                    if st.button(
                        "📋 この判断をメイン画面で開く",
                        key=f"open_{r['id']}",
                    ):
                        detail = get_judgment(r["id"])
                        if detail:
                            st.session_state.last_judgment = {
                                "judgment_id": detail["id"],
                                "response": detail["response_text"],
                                "prompt_version": detail["prompt_version"],
                                "model": detail["model"],
                                "latency_ms": detail["latency_ms"] or 0,
                                "confidence": detail["confidence"],
                                "token_usage": json.loads(detail["token_usage"]) if detail["token_usage"] else {},
                                "referenced_rules_context": json.loads(detail["referenced_rules"]) if detail["referenced_rules"] else [],
                            }
                            st.rerun()


# ===== Footer =====
st.markdown(
    """
    <div class="footer">
    © 2024 Poker TDA (<a href="https://www.pokertda.com">pokertda.com</a>) — TDA rules used by permission.
    | P1 TD判断AI v0.3 Phase 7A — 瀬戸ミナ (AI-013) 開発
    </div>
    """,
    unsafe_allow_html=True,
)

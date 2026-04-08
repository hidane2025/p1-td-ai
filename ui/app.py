#!/usr/bin/env python3
"""
TD判断AI — 現場用 Web UI (Streamlit)

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
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

# Path setup
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from judge import judge  # noqa: E402
from db import (  # noqa: E402
    init_db,
    save_feedback,
    list_recent_judgments,
    get_judgment,
    get_feedback_for_judgment,
    list_prompt_versions,
    get_active_prompt_version,
)
from evaluator import evaluate  # noqa: E402


# ===== 🔐 会員制認証（Phase 5） =====
def _get_password_hash() -> str | None:
    """Streamlit Secrets or env var からパスワードハッシュを取得"""
    # Streamlit Cloud Secrets
    try:
        if hasattr(st, "secrets") and "AUTH_PASSWORD_HASH" in st.secrets:
            return st.secrets["AUTH_PASSWORD_HASH"]
    except Exception:
        pass
    # Environment variable (local dev)
    return os.environ.get("AUTH_PASSWORD_HASH")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def check_auth() -> bool:
    """パスワードゲート。成功したら True を返す。

    パスワード未設定時は認証スキップ（ローカル開発用）。
    """
    password_hash = _get_password_hash()
    if not password_hash:
        # 認証未設定 = ローカル運用モード
        return True

    # Session state で認証状態を管理
    if st.session_state.get("authenticated", False):
        return True

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
    st.caption(f"© 2024 Poker TDA. TD判断AI v0.2 — P1 Tournament Director Advisor")
    return False


# === 認証チェック（画面描画前） ===
if not check_auth():
    st.stop()


# ===== Page Config =====
st.set_page_config(
    page_title="TD判断AI — P1事業",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ===== Custom CSS =====
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
    </style>
    """,
    unsafe_allow_html=True,
)

# ===== Initialize DB =====
init_db()

# ===== Header =====
st.markdown('<div class="main-title">⚖️ TD判断AI</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">P1事業 — Tournament Director 判断支援システム / TDA 2024準拠</div>',
    unsafe_allow_html=True,
)

# ===== Check API Key =====
# Streamlit Cloud Secrets or env var
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

# ===== Sidebar: Settings and History =====
with st.sidebar:
    # Logout button if authenticated
    if _get_password_hash():
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.markdown("#### 👤 ログイン中")
        with col_b:
            if st.button("🚪", key="logout_btn", help="ログアウト"):
                st.session_state.authenticated = False
                st.rerun()
        st.markdown("---")

    st.markdown("### ⚙️ 設定")

    active_version = get_active_prompt_version()
    current_version = active_version["version"] if active_version else "v0.2"

    versions = list_prompt_versions()
    version_options = [v["version"] for v in versions] if versions else ["v0.2"]

    selected_version = st.selectbox(
        "プロンプトバージョン",
        options=version_options,
        index=version_options.index(current_version) if current_version in version_options else 0,
    )

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
                        }
                        st.rerun()
    else:
        st.caption("まだ判断履歴はありません")

# ===== Main form =====
st.markdown("### 📝 状況の入力")

with st.form("judgment_form", clear_on_submit=False):
    situation = st.text_area(
        "状況の詳細を入力してください",
        height=180,
        placeholder="例: Day 1 後半、NLHE、Blinds 2,000-4,000。UTG が 12,000 オープン、CO が無言で 5,000×2+1,000×2 = 12,000 を押し出した。これは call か raise か？",
        help="実際の状況を自然な日本語で入力してください。プレイヤー位置、ブラインド、アクション履歴を含めると精度が上がります。",
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

    with st.spinner("AI が判断を生成中...（約 10-30 秒）"):
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
        except Exception as e:
            st.error(f"判断生成中にエラー: {e}")
            st.stop()

# ===== Display result =====
if st.session_state.last_judgment:
    result = st.session_state.last_judgment

    st.markdown("---")
    st.markdown("### ⚖️ 判断結果")

    # Top metrics
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
        cost_jpy = cost_total * 150  # USD to JPY
        st.metric("コスト", f"約 {cost_jpy:.1f}円")

    st.markdown(
        '<div class="warning-banner">⚠️ <b>最終判断は現場の人間TDに委ねられます。</b> AIは「推奨」を提示するのみです。</div>',
        unsafe_allow_html=True,
    )

    # Response body
    st.markdown(result["response"])

    # Metadata
    with st.expander("🔍 判断メタデータ"):
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

    # Feedback section
    st.markdown("---")
    st.markdown("### 📮 この判断はどうでしたか？")

    already_submitted = st.session_state.feedback_submitted.get(
        result["judgment_id"], False
    )

    if already_submitted:
        st.success("✅ フィードバックを記録しました。ありがとうございます！")
    else:
        fcol1, fcol2, fcol3, fcol4 = st.columns([1, 1, 1, 2])
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
                    rating="partial",  # コメントのみの場合は partial 扱い
                    correct_judgment=correct_judgment or None,
                    comment=comment or None,
                    reviewer=reviewer or "field_ui",
                )
                st.session_state.feedback_submitted[result["judgment_id"]] = True
                st.rerun()

# ===== Footer =====
st.markdown(
    """
    <div class="footer">
    © 2024 Poker TDA (<a href="https://www.pokertda.com">pokertda.com</a>) — TDA rules used by permission.
    | P1 TD判断AI v0.2 — 瀬戸ミナ (AI-013) 開発
    </div>
    """,
    unsafe_allow_html=True,
)

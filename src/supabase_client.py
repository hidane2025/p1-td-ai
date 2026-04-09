"""
TD判断AI — Supabase データアクセス層

SQLite (db.py) と同じインターフェースで Supabase PostgreSQL に書き込む。
環境変数 SUPABASE_URL + SUPABASE_SERVICE_KEY が設定されている場合に有効化。

設計:
- save_judgment_to_supabase() → SQLite の save_judgment() と同じ引数
- save_feedback_to_supabase() → SQLite の save_feedback() と同じ引数
- is_available() → Supabase が使えるか判定
- 呼び出し側（judge.py, ui/app.py）は db.py の後に supabase_client を呼ぶ（dual-write）
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_client = None
_available: bool | None = None


def is_available() -> bool:
    """Supabase が設定済みで接続可能かを返す"""
    global _available, _client
    if _available is not None:
        return _available

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    if not url or not key:
        _available = False
        return False

    try:
        from supabase import create_client
        _client = create_client(url, key)
        _available = True
        logger.info("Supabase client initialized")
    except Exception as e:
        logger.warning(f"Supabase unavailable: {e}")
        _available = False

    return _available


def _get_client():
    if not is_available():
        raise RuntimeError("Supabase not available")
    return _client


def save_judgment_to_supabase(
    *,
    judgment_id: str,
    situation: str,
    extra_context: dict | None,
    prompt_version: str,
    model: str,
    referenced_rules: list[str],
    response_text: str,
    response_json: dict | None = None,
    confidence: str | None = None,
    latency_ms: int | None = None,
    token_usage: dict | None = None,
) -> bool:
    """Supabase に判断を保存。成功で True、失敗で False。"""
    try:
        client = _get_client()
        row = {
            "id": judgment_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "situation": situation,
            "extra_context": extra_context,
            "prompt_version": prompt_version,
            "model": model,
            "referenced_rules": referenced_rules,
            "response_text": response_text,
            "response_json": response_json,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "token_usage": token_usage,
        }
        client.table("td_ai_judgments").upsert(row).execute()
        logger.info(f"Judgment {judgment_id} saved to Supabase")
        return True
    except Exception as e:
        logger.warning(f"Supabase save_judgment failed: {e}")
        return False


def save_feedback_to_supabase(
    *,
    feedback_id: str,
    judgment_id: str,
    rating: str,
    correct_judgment: str | None = None,
    comment: str | None = None,
    reviewer: str | None = None,
) -> bool:
    """Supabase にフィードバックを保存。成功で True、失敗で False。"""
    try:
        client = _get_client()
        row = {
            "id": feedback_id,
            "judgment_id": judgment_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "rating": rating,
            "correct_judgment": correct_judgment,
            "comment": comment,
            "reviewer": reviewer,
        }
        client.table("td_ai_feedback").upsert(row).execute()
        logger.info(f"Feedback {feedback_id} saved to Supabase")
        return True
    except Exception as e:
        logger.warning(f"Supabase save_feedback failed: {e}")
        return False


def list_recent_judgments_from_supabase(limit: int = 20) -> list[dict] | None:
    """Supabase から直近の判断を取得。失敗時は None（SQLite fallback 用）。"""
    try:
        client = _get_client()
        result = (
            client.table("td_ai_judgments")
            .select("id, created_at, situation, confidence, prompt_version")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.warning(f"Supabase list_recent failed: {e}")
        return None


def get_judgment_count() -> int | None:
    """Supabase の判断総数を取得"""
    try:
        client = _get_client()
        result = (
            client.table("td_ai_judgments")
            .select("id", count="exact")
            .execute()
        )
        return result.count
    except Exception:
        return None


def search_judgments_supabase(
    keyword: str | None = None,
    confidence: str | None = None,
    limit: int = 50,
) -> list[dict] | None:
    """Supabase で判断を検索"""
    try:
        client = _get_client()
        query = client.table("td_ai_judgments").select(
            "id, created_at, situation, confidence, prompt_version, "
            "referenced_rules, response_text"
        )

        if keyword:
            query = query.or_(
                f"situation.ilike.%{keyword}%,response_text.ilike.%{keyword}%"
            )
        if confidence:
            query = query.eq("confidence", confidence)

        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data
    except Exception as e:
        logger.warning(f"Supabase search failed: {e}")
        return None

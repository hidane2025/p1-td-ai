"""
TD判断AI — SQLite データアクセス層 v0.1

設計原則:
- すべての判断は `judgments` に記録
- フィードバックは `feedback` で紐付け
- プロンプトバージョンは `prompt_versions` で履歴管理
- ケース追加は `cases` で独立管理（判例DBと同じshape）

将来の移行:
- Phase 2で Supabase PostgreSQL に置き換え
- 同じスキーマを維持（テーブル名・カラム名そのまま）
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "td_ai.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS judgments (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    situation TEXT NOT NULL,
    extra_context TEXT,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    referenced_rules TEXT,          -- JSON array of rule IDs retrieved
    response_text TEXT NOT NULL,
    response_json TEXT,             -- Parsed structured response if available
    confidence TEXT,                -- high | medium | low
    latency_ms INTEGER,
    token_usage TEXT                -- JSON {input, output, cache_read}
);

CREATE INDEX IF NOT EXISTS idx_judgments_created ON judgments(created_at);
CREATE INDEX IF NOT EXISTS idx_judgments_version ON judgments(prompt_version);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    judgment_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rating TEXT NOT NULL,           -- correct | partial | wrong
    correct_judgment TEXT,          -- What the human TD actually decided
    comment TEXT,
    reviewer TEXT,                  -- Who reviewed (TD name or ID)
    FOREIGN KEY (judgment_id) REFERENCES judgments(id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_judgment ON feedback(judgment_id);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);

CREATE TABLE IF NOT EXISTS prompt_versions (
    version TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    path TEXT NOT NULL,             -- Relative path to prompts/versions/system_vX.md
    parent_version TEXT,            -- For lineage tracking
    change_notes TEXT,
    active BOOLEAN NOT NULL DEFAULT 0,
    FOREIGN KEY (parent_version) REFERENCES prompt_versions(version)
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source TEXT,                    -- mina | real | imported
    category TEXT,
    situation TEXT NOT NULL,
    tournament_phase TEXT,
    blinds TEXT,
    game_type TEXT,
    expected_judgment TEXT,
    expected_rules TEXT,            -- JSON array
    expected_reasoning TEXT,
    notes TEXT,
    derived_from_judgment_id TEXT,  -- If auto-added from a wrong judgment
    FOREIGN KEY (derived_from_judgment_id) REFERENCES judgments(id)
);

CREATE INDEX IF NOT EXISTS idx_cases_category ON cases(category);
CREATE INDEX IF NOT EXISTS idx_cases_source ON cases(source);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with connect() as conn:
        conn.executescript(SCHEMA_SQL)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str = "j") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ===== Judgment operations =====

def save_judgment(
    *,
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
) -> str:
    """Persist a judgment and return its id."""
    judgment_id = new_id("j")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO judgments (
                id, created_at, situation, extra_context,
                prompt_version, model, referenced_rules,
                response_text, response_json, confidence,
                latency_ms, token_usage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                judgment_id,
                now_iso(),
                situation,
                json.dumps(extra_context, ensure_ascii=False) if extra_context else None,
                prompt_version,
                model,
                json.dumps(referenced_rules),
                response_text,
                json.dumps(response_json, ensure_ascii=False) if response_json else None,
                confidence,
                latency_ms,
                json.dumps(token_usage) if token_usage else None,
            ),
        )
    return judgment_id


def get_judgment(judgment_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM judgments WHERE id = ?", (judgment_id,)
        ).fetchone()
        return dict(row) if row else None


def list_recent_judgments(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, situation, confidence, prompt_version "
            "FROM judgments ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def search_judgments(
    keyword: str | None = None,
    confidence: str | None = None,
    rule_id: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """
    判断の全文検索 + フィルタリング。

    Args:
        keyword: situation / response_text に含まれる部分文字列
        confidence: high / medium / low でフィルタ
        rule_id: referenced_rules JSON 内に含まれるルール ID
        limit: 取得上限
    """
    query = (
        "SELECT id, created_at, situation, confidence, prompt_version, "
        "referenced_rules, response_text FROM judgments WHERE 1=1"
    )
    params: list = []
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

    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ===== Feedback operations =====

def save_feedback(
    *,
    judgment_id: str,
    rating: str,
    correct_judgment: str | None = None,
    comment: str | None = None,
    reviewer: str | None = None,
) -> str:
    """Record feedback on a judgment. Rating must be correct|partial|wrong."""
    if rating not in {"correct", "partial", "wrong"}:
        raise ValueError(f"Invalid rating: {rating}")
    fb_id = new_id("fb")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO feedback (
                id, judgment_id, created_at, rating,
                correct_judgment, comment, reviewer
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (fb_id, judgment_id, now_iso(), rating, correct_judgment, comment, reviewer),
        )
    return fb_id


def get_feedback_for_judgment(judgment_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM feedback WHERE judgment_id = ? ORDER BY created_at",
            (judgment_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ===== Prompt version operations =====

def register_prompt_version(
    version: str,
    path: str,
    parent_version: str | None = None,
    change_notes: str | None = None,
    activate: bool = False,
) -> None:
    """Register a new prompt version. Set activate=True to make it the current one."""
    with connect() as conn:
        if activate:
            conn.execute("UPDATE prompt_versions SET active = 0")
        conn.execute(
            """
            INSERT OR REPLACE INTO prompt_versions (
                version, created_at, path, parent_version, change_notes, active
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (version, now_iso(), path, parent_version, change_notes, 1 if activate else 0),
        )


def get_active_prompt_version() -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM prompt_versions WHERE active = 1 LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def list_prompt_versions() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM prompt_versions ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def activate_prompt_version(version: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE prompt_versions SET active = 0")
        conn.execute("UPDATE prompt_versions SET active = 1 WHERE version = ?", (version,))


# ===== Case operations =====

def add_case(
    *,
    source: str,
    category: str,
    situation: str,
    tournament_phase: str | None = None,
    blinds: str | None = None,
    game_type: str | None = None,
    expected_judgment: str | None = None,
    expected_rules: list[str] | None = None,
    expected_reasoning: str | None = None,
    notes: str | None = None,
    derived_from_judgment_id: str | None = None,
) -> str:
    case_id = new_id("c")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO cases (
                id, created_at, source, category, situation,
                tournament_phase, blinds, game_type,
                expected_judgment, expected_rules, expected_reasoning,
                notes, derived_from_judgment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                now_iso(),
                source,
                category,
                situation,
                tournament_phase,
                blinds,
                game_type,
                expected_judgment,
                json.dumps(expected_rules or []),
                expected_reasoning,
                notes,
                derived_from_judgment_id,
            ),
        )
    return case_id


def list_cases(category: str | None = None, source: str | None = None) -> list[dict]:
    query = "SELECT * FROM cases WHERE 1=1"
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category)
    if source:
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY created_at DESC"
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ===== Initial seed from JSON =====

def seed_cases_from_json(json_path: Path) -> int:
    """Import cases from the initial JSON file. Idempotent by id."""
    import json as json_mod
    if not json_path.exists():
        return 0
    with open(json_path, "r", encoding="utf-8") as f:
        data = json_mod.load(f)
    count = 0
    with connect() as conn:
        for c in data:
            # Use the JSON id as primary key for idempotent seeding
            exists = conn.execute(
                "SELECT id FROM cases WHERE id = ?", (c["id"],)
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO cases (
                    id, created_at, source, category, situation,
                    tournament_phase, blinds, game_type,
                    expected_judgment, expected_rules, expected_reasoning,
                    notes, derived_from_judgment_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    c["id"],
                    now_iso(),
                    c.get("created_by", "seed"),
                    c.get("category"),
                    c.get("situation", ""),
                    c.get("tournament_phase"),
                    c.get("blinds"),
                    c.get("game_type"),
                    c.get("expected_judgment"),
                    json_mod.dumps(c.get("expected_rules", [])),
                    c.get("expected_reasoning"),
                    c.get("notes"),
                    None,
                ),
            )
            count += 1
    return count

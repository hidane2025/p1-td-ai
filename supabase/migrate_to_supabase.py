#!/usr/bin/env python3
"""
SQLite (ローカル) → Supabase PostgreSQL マイグレーション

Phase 7E: 完全実装版。Supabase REST API 経由で TDA ルール・判例・
判断・フィードバック・プロンプトを一括移行する。

## 前提
- Supabase プロジェクト plsyhqlqiaqatshcoerx が稼働中
- pgvector 拡張が enabled
- schema_td_ai.sql 実行済み
- SUPABASE_URL, SUPABASE_SERVICE_KEY が環境変数に設定済み

## 使い方
    export SUPABASE_URL=https://plsyhqlqiaqatshcoerx.supabase.co
    export SUPABASE_SERVICE_KEY=eyJhbGc...
    python3 supabase/migrate_to_supabase.py --step dry-run       # 確認のみ
    python3 supabase/migrate_to_supabase.py --step rules         # ルールのみ
    python3 supabase/migrate_to_supabase.py --step illustrations # 例示
    python3 supabase/migrate_to_supabase.py --step cases         # 判例
    python3 supabase/migrate_to_supabase.py --step judgments     # 判断+FB
    python3 supabase/migrate_to_supabase.py --step all           # 全工程
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))


def _get_supabase_client():
    """Supabase クライアントを初期化"""
    try:
        from supabase import create_client
    except ImportError:
        print("❌ supabase not installed. Run: pip3 install supabase")
        sys.exit(1)

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("❌ SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    return create_client(url, key)


def _load_rules() -> list[dict]:
    path = BASE_DIR / "data" / "tda-rules" / "tda_2024_rules_structured.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_cases() -> list[dict]:
    path = BASE_DIR / "data" / "cases" / "judgment_cases.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_illustrations() -> list[dict]:
    path = BASE_DIR / "data" / "tda-rules" / "tda_2024_illustration_examples.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_jp_keyword_rev_map() -> dict[str, list[str]]:
    """judge.py の KEYWORD_MAP から逆マップを作成"""
    from judge import KEYWORD_MAP
    rev: dict[str, list[str]] = {}
    for kw, rule_ids in KEYWORD_MAP.items():
        for rid in rule_ids:
            rev.setdefault(rid, []).append(kw)
    return rev


def _load_sqlite_judgments() -> tuple[list[dict], list[dict]]:
    """SQLite から判断とフィードバックを読み込む"""
    from db import connect
    with connect() as conn:
        j_rows = conn.execute(
            "SELECT * FROM judgments ORDER BY created_at"
        ).fetchall()
        f_rows = conn.execute(
            "SELECT * FROM feedback ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in j_rows], [dict(r) for r in f_rows]


def _load_sqlite_prompt_versions() -> list[dict]:
    from db import connect
    with connect() as conn:
        rows = conn.execute("SELECT * FROM prompt_versions").fetchall()
    return [dict(r) for r in rows]


# ===== Migration Steps =====

def migrate_rules(dry_run: bool = False) -> int:
    """TDA ルールを Supabase td_ai_rules テーブルに移行"""
    rules = _load_rules()
    jp_kw = _build_jp_keyword_rev_map()

    if dry_run:
        print(f"  Would migrate {len(rules)} rules to td_ai_rules")
        for r in rules[:3]:
            print(f"    {r['id']}: {r['title'][:50]}  kw={jp_kw.get(r['id'], [])[:5]}")
        return len(rules)

    client = _get_supabase_client()
    migrated = 0

    for r in rules:
        row = {
            "id": r["id"],
            "rule_number": r["number"],
            "kind": r["kind"],
            "title": r["title"],
            "body": r["body"],
            "jp_keywords": jp_kw.get(r["id"], []),
        }
        try:
            client.table("td_ai_rules").upsert(row).execute()
            migrated += 1
        except Exception as e:
            print(f"    ⚠️ {r['id']}: {e}")

    print(f"  ✅ Rules migrated: {migrated}/{len(rules)}")
    return migrated


def migrate_illustrations(dry_run: bool = False) -> int:
    """Illustration Addendum を Supabase td_ai_illustrations テーブルに移行"""
    illustrations = _load_illustrations()

    if dry_run:
        print(f"  Would migrate {len(illustrations)} illustrations")
        for e in illustrations[:3]:
            print(f"    {e['rule_id']}{e.get('subpart','')}: {e.get('title_snippet','')[:50]}")
        return len(illustrations)

    client = _get_supabase_client()
    migrated = 0

    for e in illustrations:
        row = {
            "rule_id": e["rule_id"],
            "subpart": e.get("subpart", ""),
            "title_snippet": e.get("title_snippet", ""),
            "body": e.get("body", ""),
        }
        try:
            client.table("td_ai_illustrations").insert(row).execute()
            migrated += 1
        except Exception as e_err:
            print(f"    ⚠️ {e.get('rule_id','?')}: {e_err}")

    print(f"  ✅ Illustrations migrated: {migrated}/{len(illustrations)}")
    return migrated


def migrate_cases(dry_run: bool = False) -> int:
    """判例を Supabase td_ai_cases テーブルに移行"""
    cases = _load_cases()

    if dry_run:
        print(f"  Would migrate {len(cases)} cases to td_ai_cases")
        for c in cases[:3]:
            print(f"    {c['id']}: req={c.get('required_rules')} rec={c.get('recommended_rules')}")
        return len(cases)

    client = _get_supabase_client()
    migrated = 0

    for c in cases:
        row = {
            "id": c["id"],
            "source": c.get("created_by", "seed"),
            "category": c.get("category"),
            "situation": c.get("situation", ""),
            "tournament_phase": c.get("tournament_phase"),
            "blinds": c.get("blinds"),
            "game_type": c.get("game_type"),
            "expected_judgment": c.get("expected_judgment"),
            "expected_rules": c.get("expected_rules", []),
            "required_rules": c.get("required_rules", []),
            "recommended_rules": c.get("recommended_rules", []),
            "expected_reasoning": c.get("expected_reasoning"),
            "notes": c.get("notes"),
        }
        try:
            client.table("td_ai_cases").upsert(row).execute()
            migrated += 1
        except Exception as e:
            print(f"    ⚠️ {c['id']}: {e}")

    print(f"  ✅ Cases migrated: {migrated}/{len(cases)}")
    return migrated


def migrate_judgments(dry_run: bool = False) -> int:
    """判断 + フィードバックを Supabase に移行"""
    judgments, feedback = _load_sqlite_judgments()
    prompt_versions = _load_sqlite_prompt_versions()

    if dry_run:
        print(f"  Would migrate {len(judgments)} judgments + {len(feedback)} feedback + {len(prompt_versions)} prompt versions")
        return len(judgments)

    client = _get_supabase_client()
    j_migrated = 0
    f_migrated = 0

    # Prompt versions first
    for pv in prompt_versions:
        row = {
            "version": pv["version"],
            "created_at": pv.get("created_at"),
            "path": pv.get("path", ""),
            "parent_version": pv.get("parent_version"),
            "change_notes": pv.get("change_notes"),
            "active": pv.get("active", False),
        }
        try:
            client.table("td_ai_prompt_versions").upsert(row).execute()
        except Exception as e:
            print(f"    ⚠️ prompt {pv['version']}: {e}")

    # Judgments
    for j in judgments:
        # Parse JSON fields
        ref_rules = j.get("referenced_rules")
        if isinstance(ref_rules, str):
            try:
                ref_rules = json.loads(ref_rules)
            except json.JSONDecodeError:
                ref_rules = []

        token_usage = j.get("token_usage")
        if isinstance(token_usage, str):
            try:
                token_usage = json.loads(token_usage)
            except json.JSONDecodeError:
                token_usage = {}

        extra_context = j.get("extra_context")
        if isinstance(extra_context, str):
            try:
                extra_context = json.loads(extra_context)
            except json.JSONDecodeError:
                extra_context = None

        response_json = j.get("response_json")
        if isinstance(response_json, str):
            try:
                response_json = json.loads(response_json)
            except json.JSONDecodeError:
                response_json = None

        row = {
            "id": j["id"],
            "created_at": j.get("created_at"),
            "situation": j.get("situation", ""),
            "extra_context": extra_context,
            "prompt_version": j.get("prompt_version", "v0.1"),
            "model": j.get("model", ""),
            "referenced_rules": ref_rules or [],
            "response_text": j.get("response_text", ""),
            "response_json": response_json,
            "confidence": j.get("confidence"),
            "latency_ms": j.get("latency_ms"),
            "token_usage": token_usage,
        }
        try:
            client.table("td_ai_judgments").upsert(row).execute()
            j_migrated += 1
        except Exception as e:
            print(f"    ⚠️ judgment {j['id']}: {e}")

    # Feedback
    for f in feedback:
        row = {
            "id": f["id"],
            "judgment_id": f["judgment_id"],
            "created_at": f.get("created_at"),
            "rating": f.get("rating", "partial"),
            "correct_judgment": f.get("correct_judgment"),
            "comment": f.get("comment"),
            "reviewer": f.get("reviewer"),
        }
        try:
            client.table("td_ai_feedback").upsert(row).execute()
            f_migrated += 1
        except Exception as e:
            print(f"    ⚠️ feedback {f['id']}: {e}")

    print(f"  ✅ Judgments: {j_migrated}/{len(judgments)}, Feedback: {f_migrated}/{len(feedback)}")
    return j_migrated


def main() -> int:
    parser = argparse.ArgumentParser(description="TD判断AI — Supabase Migration")
    parser.add_argument(
        "--step",
        choices=["rules", "illustrations", "cases", "judgments", "all", "dry-run"],
        default="dry-run",
        help="Migration step to execute",
    )
    args = parser.parse_args()
    dry_run = args.step == "dry-run"

    print("=" * 60)
    print(f"TD判断AI — Supabase Migration {'(DRY RUN)' if dry_run else ''}")
    print("=" * 60)
    print()

    steps = {
        "rules": ["rules"],
        "illustrations": ["illustrations"],
        "cases": ["cases"],
        "judgments": ["judgments"],
        "all": ["rules", "illustrations", "cases", "judgments"],
        "dry-run": ["rules", "illustrations", "cases", "judgments"],
    }

    for step in steps[args.step]:
        print(f"--- {step} ---")
        if step == "rules":
            migrate_rules(dry_run=dry_run)
        elif step == "illustrations":
            migrate_illustrations(dry_run=dry_run)
        elif step == "cases":
            migrate_cases(dry_run=dry_run)
        elif step == "judgments":
            migrate_judgments(dry_run=dry_run)
        print()

    if dry_run:
        print("ℹ️  Dry run complete. To execute migration:")
        print("   1. Run schema_td_ai.sql on Supabase SQL Editor")
        print("   2. Set environment variables:")
        print("      export SUPABASE_URL=https://plsyhqlqiaqatshcoerx.supabase.co")
        print("      export SUPABASE_SERVICE_KEY=<your-service-key>")
        print("   3. Run: python3 supabase/migrate_to_supabase.py --step all")

    return 0


if __name__ == "__main__":
    sys.exit(main())

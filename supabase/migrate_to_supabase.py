#!/usr/bin/env python3
"""
SQLite (ローカル) → Supabase PostgreSQL マイグレーション

Phase 3 準備用。Supabase Vector に TDA ルール・判例・判断・フィードバック・プロンプトを
一括移行する。Voyage AI embedding API で vector 化する。

## 前提
- Supabase プロジェクト plsyhqlqiaqatshcoerx が稼働中
- pgvector 拡張が enabled
- schema_td_ai.sql 実行済み
- SUPABASE_URL, SUPABASE_SERVICE_KEY が環境変数に設定済み
- VOYAGE_API_KEY が環境変数に設定済み (Voyage embeddings 用)

## 使い方
    export SUPABASE_URL=https://plsyhqlqiaqatshcoerx.supabase.co
    export SUPABASE_SERVICE_KEY=eyJhbGc...
    export VOYAGE_API_KEY=pa-...
    python3 supabase/migrate_to_supabase.py --step rules       # ルールのみ
    python3 supabase/migrate_to_supabase.py --step illustrations
    python3 supabase/migrate_to_supabase.py --step cases
    python3 supabase/migrate_to_supabase.py --step all         # 全工程

NOTE: Phase 2 時点では未実装・設計のみ。
      Phase 3 で中野さんの承認+環境変数設定後に実装する。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _check_env() -> bool:
    required = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "VOYAGE_API_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"❌ Missing env vars: {', '.join(missing)}")
        print()
        print("Setup guide:")
        print("  1. Supabase: Dashboard → Settings → API → copy service_role key")
        print("  2. Voyage:   https://www.voyageai.com/ → create API key")
        print("  3. Set env:  export SUPABASE_URL=... SUPABASE_SERVICE_KEY=... VOYAGE_API_KEY=...")
        return False
    return True


def _load_sqlite_rules() -> list[dict]:
    path = BASE_DIR / "data" / "tda-rules" / "tda_2024_rules_structured.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_sqlite_cases() -> list[dict]:
    path = BASE_DIR / "data" / "cases" / "judgment_cases.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_illustrations() -> list[dict]:
    path = BASE_DIR / "data" / "tda-rules" / "tda_2024_illustration_examples.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_jp_keyword_rev_map() -> dict[str, list[str]]:
    """judge.py の KEYWORD_MAP から逆マップ"""
    sys.path.insert(0, str(BASE_DIR / "src"))
    from judge import KEYWORD_MAP
    rev: dict[str, list[str]] = {}
    for kw, rule_ids in KEYWORD_MAP.items():
        for rid in rule_ids:
            rev.setdefault(rid, []).append(kw)
    return rev


def migrate_rules_dry_run() -> None:
    """Rules の dry-run（実際の Supabase 挿入はしない）"""
    rules = _load_sqlite_rules()
    jp_kw = _build_jp_keyword_rev_map()
    print(f"Would migrate {len(rules)} rules to td_ai_rules table")
    for r in rules[:3]:
        print(f"  {r['id']}: {r['title'][:40]}")
        print(f"    jp_keywords: {jp_kw.get(r['id'], [])[:5]}")
        print(f"    embedding: (would generate via Voyage voyage-3)")


def migrate_illustrations_dry_run() -> None:
    illustrations = _load_illustrations()
    print(f"Would migrate {len(illustrations)} illustration entries")
    for e in illustrations[:3]:
        print(f"  {e['rule_id']}{e['subpart']}: {e['title_snippet'][:50]}")


def migrate_cases_dry_run() -> None:
    cases = _load_sqlite_cases()
    print(f"Would migrate {len(cases)} cases to td_ai_cases table")
    for c in cases[:3]:
        print(f"  {c['id']}: req={c.get('required_rules')} rec={c.get('recommended_rules')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=["rules", "illustrations", "cases", "all", "dry-run"], default="dry-run")
    args = parser.parse_args()

    if args.step == "dry-run":
        print("=== DRY RUN (no Supabase calls) ===\n")
        migrate_rules_dry_run()
        print()
        migrate_illustrations_dry_run()
        print()
        migrate_cases_dry_run()
        return 0

    if not _check_env():
        return 1

    print("⚠️  Phase 2 時点ではマイグレーション実装は未完成です。")
    print("    Phase 3 で中野さんの環境変数設定後に有効化します。")
    print()
    print("Dry run で移行内容を確認するには:")
    print("    python3 supabase/migrate_to_supabase.py --step dry-run")
    return 1


if __name__ == "__main__":
    sys.exit(main())

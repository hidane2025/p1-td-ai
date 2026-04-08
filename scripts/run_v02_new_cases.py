#!/usr/bin/env python3
"""
新規判例 (case-011〜015) を v0.2 プロンプトでテスト

使い方:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 scripts/run_v02_new_cases.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from judge import judge  # noqa: E402
from db import init_db, save_feedback, seed_cases_from_json  # noqa: E402
from evaluator import evaluate  # noqa: E402


CASES_JSON = BASE_DIR / "data" / "cases" / "judgment_cases.json"


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set")
        return 1

    init_db()
    # Re-seed cases (idempotent)
    seed_cases_from_json(CASES_JSON)

    with open(CASES_JSON, "r", encoding="utf-8") as f:
        all_cases = json.load(f)

    target_ids = {
        "case-011-clock-call-absent-player",
        "case-012-verbal-chip-conflict",
        "case-013-short-all-in-reopen",
        "case-014-player-exposed-own-hand",
        "case-015-dead-button",
    }
    cases = [c for c in all_cases if c["id"] in target_ids]
    cases.sort(key=lambda c: c["id"])

    print("=" * 80)
    print(f"v0.2 新規5判例テスト")
    print("=" * 80)
    print()

    results: list[dict] = []
    for i, c in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {c['id']} — {c['category']}")
        extra = {
            k: c[k]
            for k in ("tournament_phase", "blinds", "game_type")
            if c.get(k)
        }
        result = judge(
            situation=c["situation"],
            extra_context=extra or None,
            prompt_version="v0.2",
        )
        ev = evaluate(result["response"], c["required_rules"], c.get("recommended_rules", []))
        print(f"  {ev.summary()}")
        print(f"  judgment_id: {result['judgment_id']}")
        print(f"  latency: {result['latency_ms']}ms  tokens: in={result['token_usage']['input']} out={result['token_usage']['output']}")

        save_feedback(
            judgment_id=result["judgment_id"],
            rating=ev.rating,
            comment=(
                f"新規判例テスト (v0.2): req {ev.required_hits}/{ev.required_total}, "
                f"rec {ev.recommended_hits}/{ev.recommended_total}, quality {ev.quality_score:.2f}"
            ),
            reviewer="run_v02_new_cases",
        )
        results.append({"case": c, "eval": ev, "result": result})
        print()

    # Summary
    print("=" * 80)
    print("📊 新規5判例 v0.2 テスト結果")
    print("=" * 80)
    correct = sum(1 for r in results if r["eval"].rating == "correct")
    partial = sum(1 for r in results if r["eval"].rating == "partial")
    wrong = sum(1 for r in results if r["eval"].rating == "wrong")
    avg_q = sum(r["eval"].quality_score for r in results) / len(results) if results else 0
    total_in = sum(r["result"]["token_usage"]["input"] for r in results)
    total_out = sum(r["result"]["token_usage"]["output"] for r in results)
    cost = (total_in / 1e6) * 3.0 + (total_out / 1e6) * 15.0

    print(f"  correct: {correct} / partial: {partial} / wrong: {wrong}")
    print(f"  avg quality: {avg_q:.2f}")
    print(f"  tokens: in={total_in:,} out={total_out:,}")
    print(f"  cost: ${cost:.4f}")

    return 0 if correct >= len(results) * 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())

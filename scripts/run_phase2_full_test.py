#!/usr/bin/env python3
"""
Phase 2 フルテスト — 20 判例 × v0.2 + TF-IDF/keyword ハイブリッド retriever

使い方:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 scripts/run_phase2_full_test.py
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
    seed_cases_from_json(CASES_JSON)

    with open(CASES_JSON, "r", encoding="utf-8") as f:
        cases = json.load(f)
    cases.sort(key=lambda c: c["id"])

    print("=" * 80)
    print(f"Phase 2 フルテスト — 20判例 × v0.2 + hybrid retriever")
    print("=" * 80)
    print()

    results: list[dict] = []
    for i, c in enumerate(cases, 1):
        print(f"[{i:2d}/{len(cases)}] {c['id']}")
        extra = {
            k: c[k]
            for k in ("tournament_phase", "blinds", "game_type")
            if c.get(k)
        }
        try:
            result = judge(
                situation=c["situation"],
                extra_context=extra or None,
                prompt_version="v0.2",
            )
        except Exception as e:
            print(f"    ❌ ERROR: {e}")
            continue

        ev = evaluate(
            result["response"],
            c.get("required_rules", c.get("expected_rules", [])),
            c.get("recommended_rules", []),
        )
        print(f"    {ev.summary()}")
        print(
            f"    latency={result['latency_ms']}ms  "
            f"tokens in={result['token_usage']['input']} out={result['token_usage']['output']}"
        )

        save_feedback(
            judgment_id=result["judgment_id"],
            rating=ev.rating,
            comment=(
                f"Phase 2 フルテスト: req {ev.required_hits}/{ev.required_total}, "
                f"rec {ev.recommended_hits}/{ev.recommended_total}, "
                f"quality {ev.quality_score:.2f}"
            ),
            reviewer="run_phase2_full_test",
        )
        results.append({"case": c, "eval": ev, "result": result})

    # Summary
    print()
    print("=" * 80)
    print("📊 Phase 2 Full Test Summary")
    print("=" * 80)
    correct = sum(1 for r in results if r["eval"].rating == "correct")
    partial = sum(1 for r in results if r["eval"].rating == "partial")
    wrong = sum(1 for r in results if r["eval"].rating == "wrong")
    avg_q = sum(r["eval"].quality_score for r in results) / len(results) if results else 0
    total_in = sum(r["result"]["token_usage"]["input"] for r in results)
    total_out = sum(r["result"]["token_usage"]["output"] for r in results)
    total_lat = sum(r["result"]["latency_ms"] for r in results) / len(results) if results else 0
    cost = (total_in / 1e6) * 3.0 + (total_out / 1e6) * 15.0

    print(f"  件数       : {len(results)}")
    print(f"  correct    : {correct} ({correct/len(results)*100:.0f}%)")
    print(f"  partial    : {partial} ({partial/len(results)*100:.0f}%)")
    print(f"  wrong      : {wrong} ({wrong/len(results)*100:.0f}%)")
    print(f"  avg quality: {avg_q:.3f}")
    print(f"  avg latency: {total_lat:.0f} ms")
    print(f"  tokens     : in={total_in:,} out={total_out:,}")
    print(f"  cost       : ${cost:.4f}")

    # Per-category breakdown
    from collections import defaultdict
    by_cat: dict[str, list] = defaultdict(list)
    for r in results:
        by_cat[r["case"]["category"]].append(r["eval"].rating)

    print()
    print("  === By Category ===")
    for cat, ratings in sorted(by_cat.items()):
        c_correct = ratings.count("correct")
        c_total = len(ratings)
        print(f"  {cat:40s}  {c_correct}/{c_total}")

    # Wrong cases detail
    wrongs = [r for r in results if r["eval"].rating == "wrong"]
    if wrongs:
        print()
        print("  === Wrong cases (detail) ===")
        for r in wrongs:
            c = r["case"]
            ev = r["eval"]
            print(f"  {c['id']}: req_missing={ev.required_missing}")

    return 0 if correct >= len(results) * 0.9 else 1


if __name__ == "__main__":
    sys.exit(main())

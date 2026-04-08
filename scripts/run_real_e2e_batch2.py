#!/usr/bin/env python3
"""
Phase 0 本番E2Eテスト第2弾 — 新規判例5件（case-006〜case-010）

使い方:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 scripts/run_real_e2e_batch2.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from judge import judge  # noqa: E402
from db import init_db, save_feedback, list_cases  # noqa: E402


def rule_matches(rule_id: str, text: str) -> bool:
    prefix = "RP" if rule_id.startswith("RP-") else "Rule"
    num = rule_id.replace("Rule-", "").replace("RP-", "")
    return any(p in text for p in [f"{prefix}-{num}", f"{prefix} {num}", f"{prefix}{num}"])


def evaluate(response_text: str, expected_rules: list[str]) -> tuple[str, int, int]:
    if not expected_rules:
        return "correct", 0, 0
    hits = sum(1 for r in expected_rules if rule_matches(r, response_text))
    ratio = hits / len(expected_rules)
    if ratio >= 1.0:
        return "correct", hits, len(expected_rules)
    elif ratio >= 0.5:
        return "partial", hits, len(expected_rules)
    return "wrong", hits, len(expected_rules)


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set")
        return 1

    init_db()
    cases = list_cases()

    target_ids = {
        "case-006-all-in-showdown-muck",
        "case-007-verbal-bet-trick",
        "case-008-string-bet-raise",
        "case-009-soft-play-collusion-suspicion",
        "case-010-big-blind-ante-dispute",
    }
    target_cases = [c for c in cases if c["id"] in target_ids]
    target_cases.sort(key=lambda c: c["id"])

    if not target_cases:
        print("❌ Target cases not found in DB")
        return 1

    print("=" * 70)
    print(f"Phase 0 本番E2E 第2弾 — {len(target_cases)} 判例")
    print("=" * 70)
    print()

    results: list[dict] = []
    for i, c in enumerate(target_cases, 1):
        print(f"[{i}/{len(target_cases)}] {c['id']} — {c['category']}")
        print(f"    situation: {c['situation'][:70]}...")

        extra = {}
        if c.get("tournament_phase"):
            extra["tournament_phase"] = c["tournament_phase"]
        if c.get("blinds"):
            extra["blinds"] = c["blinds"]
        if c.get("game_type"):
            extra["game_type"] = c["game_type"]

        try:
            result = judge(
                situation=c["situation"],
                extra_context=extra or None,
            )
        except Exception as e:
            print(f"    ❌ ERROR: {e}")
            print()
            continue

        expected_rules = json.loads(c["expected_rules"]) if c["expected_rules"] else []
        rating, hits, total = evaluate(result["response"], expected_rules)

        icon = {"correct": "✅", "partial": "🟡", "wrong": "❌"}[rating]
        print(
            f"    {icon} {rating.upper()}  "
            f"rules {hits}/{total}  "
            f"confidence={result['confidence']}  "
            f"latency={result['latency_ms']}ms  "
            f"tokens in={result['token_usage']['input']} out={result['token_usage']['output']}"
        )
        print(f"    judgment_id: {result['judgment_id']}")

        save_feedback(
            judgment_id=result["judgment_id"],
            rating=rating,
            correct_judgment=None,
            comment=f"E2E batch2 自動評価: expected_rules {hits}/{total} 一致。期待: {expected_rules}",
            reviewer="run_real_e2e_batch2",
        )

        results.append({"rating": rating, "hits": hits, "total": total,
                        "tokens": result["token_usage"], "latency": result["latency_ms"]})
        print()

    # Summary
    print("=" * 70)
    print("📊 E2E Batch2 結果サマリ")
    print("=" * 70)
    correct = sum(1 for r in results if r["rating"] == "correct")
    partial = sum(1 for r in results if r["rating"] == "partial")
    wrong = sum(1 for r in results if r["rating"] == "wrong")
    total_in = sum(r["tokens"]["input"] for r in results)
    total_out = sum(r["tokens"]["output"] for r in results)
    avg_lat = sum(r["latency"] for r in results) / len(results) if results else 0
    cost = (total_in / 1e6) * 3.0 + (total_out / 1e6) * 15.0

    print(f"  件数       : {len(results)}")
    print(f"  correct    : {correct}")
    print(f"  partial    : {partial}")
    print(f"  wrong      : {wrong}")
    print(f"  正答率     : {correct/len(results)*100:.0f}%" if results else "—")
    print(f"  平均latency: {avg_lat:.0f} ms")
    print(f"  tokens     : in={total_in:,} / out={total_out:,}")
    print(f"  cost概算   : ${cost:.4f}")

    return 0 if correct >= len(results) * 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())

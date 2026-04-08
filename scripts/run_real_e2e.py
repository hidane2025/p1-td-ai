#!/usr/bin/env python3
"""
Phase 0 本番E2Eテスト — 実際のClaude API呼び出し版

judgment_cases.json の5判例を順に judge() に投入し、
実際のAI応答を取得してDBに記録、expected_rulesとの一致率で
自動的に correct/partial/wrong を判定する。

使い方:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 scripts/run_real_e2e.py
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


def evaluate(response_text: str, expected_rules: list[str]) -> tuple[str, int, int]:
    """
    Return (rating, hits, total)
    rating: correct | partial | wrong

    Matches Rule-XX and "Rule XX" variants because models vary in formatting.
    """
    if not expected_rules:
        return "correct", 0, 0

    def rule_matches(rule_id: str, text: str) -> bool:
        # Normalize "Rule-45" to match both "Rule-45", "Rule 45", "Rule45"
        num = rule_id.replace("Rule-", "").replace("RP-", "")
        prefix = "RP" if rule_id.startswith("RP-") else "Rule"
        patterns = [
            f"{prefix}-{num}",    # Rule-45
            f"{prefix} {num}",    # Rule 45
            f"{prefix}{num}",     # Rule45 (rare)
        ]
        return any(p in text for p in patterns)

    hits = sum(1 for r in expected_rules if rule_matches(r, response_text))
    ratio = hits / len(expected_rules)
    if ratio >= 1.0:
        rating = "correct"
    elif ratio >= 0.5:
        rating = "partial"
    else:
        rating = "wrong"
    return rating, hits, len(expected_rules)


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set")
        return 1

    init_db()
    cases = list_cases()
    if not cases:
        print("❌ No cases in DB. Run: python3 src/cli.py init")
        return 1

    # Only run cases seeded by Mina (not dynamically added later)
    target_ids = {
        "case-001-multi-chip-bet",
        "case-002-oot-action-changes",
        "case-003-misdeal-exposed-downcards",
        "case-004-electronic-device-live-hand",
        "case-005-one-player-to-a-hand",
    }
    cases = [c for c in cases if c["id"] in target_ids]
    cases.sort(key=lambda c: c["id"])

    print("=" * 70)
    print(f"Phase 0 本番E2Eテスト — {len(cases)}判例")
    print("=" * 70)
    print()

    results: list[dict] = []
    for i, c in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {c['id']} — {c['category']}")
        print(f"    状況: {c['situation'][:70]}...")

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

        status_icon = {"correct": "✅", "partial": "🟡", "wrong": "❌"}[rating]
        print(
            f"    {status_icon} {rating.upper()}  "
            f"rules {hits}/{total}  "
            f"confidence={result['confidence']}  "
            f"latency={result['latency_ms']}ms  "
            f"tokens in={result['token_usage']['input']} out={result['token_usage']['output']}"
        )
        print(f"    judgment_id: {result['judgment_id']}")

        # Save feedback
        save_feedback(
            judgment_id=result["judgment_id"],
            rating=rating,
            correct_judgment=None,
            comment=(
                f"自動評価: expected_rules {hits}/{total} 一致。"
                f"期待ルール: {expected_rules}"
            ),
            reviewer="run_real_e2e",
        )

        results.append(
            {
                "case_id": c["id"],
                "judgment_id": result["judgment_id"],
                "rating": rating,
                "hits": hits,
                "total": total,
                "confidence": result["confidence"],
                "latency_ms": result["latency_ms"],
                "tokens": result["token_usage"],
            }
        )
        print()

    # Summary
    print("=" * 70)
    print("📊 E2E テスト結果サマリ")
    print("=" * 70)
    correct_count = sum(1 for r in results if r["rating"] == "correct")
    partial_count = sum(1 for r in results if r["rating"] == "partial")
    wrong_count = sum(1 for r in results if r["rating"] == "wrong")
    total_tokens_in = sum(r["tokens"]["input"] for r in results)
    total_tokens_out = sum(r["tokens"]["output"] for r in results)
    avg_latency = sum(r["latency_ms"] for r in results) / len(results) if results else 0
    cost = (total_tokens_in / 1e6) * 3.0 + (total_tokens_out / 1e6) * 15.0

    print(f"  判断件数     : {len(results)}")
    print(f"  correct      : {correct_count}")
    print(f"  partial      : {partial_count}")
    print(f"  wrong        : {wrong_count}")
    print(f"  正答率       : {correct_count/len(results)*100:.0f}%" if results else "—")
    print(f"  平均latency  : {avg_latency:.0f} ms")
    print(f"  総tokens     : in={total_tokens_in:,} / out={total_tokens_out:,}")
    print(f"  コスト概算   : ${cost:.4f}")
    print()

    # Pass/fail
    target_pass = 4  # Phase 0 success criterion: 4/5 or better (80%)
    if correct_count >= target_pass:
        print(f"🎉 Phase 0 成功基準クリア ({correct_count}/{len(results)} ≥ {target_pass}/5)")
    else:
        print(f"⚠️  Phase 0 成功基準未達 ({correct_count}/{len(results)} < {target_pass}/5)")
        print("    プロンプトv0.2改訂が必要")

    print()
    print("次のコマンドで詳細確認:")
    print("  python3 src/cli.py list-judgments")
    print("  python3 src/cli.py metrics")
    print("  python3 src/cli.py show-judgment <judgment_id>")

    return 0 if correct_count >= target_pass else 1


if __name__ == "__main__":
    sys.exit(main())

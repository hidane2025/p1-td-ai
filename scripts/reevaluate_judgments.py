#!/usr/bin/env python3
"""
既存の judgments を再評価して正しいフィードバックを付与するスクリプト。

run_real_e2e.py の初回実行時、評価ロジックが "Rule-45" という正規表現しか
マッチしなかったため、モデルが返す "Rule 45"（スペース区切り）を認識できず
全件 wrong と誤判定された。本スクリプトは修正後のマッチャーで再評価する。

使い方:
    python3 scripts/reevaluate_judgments.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from db import (  # noqa: E402
    list_recent_judgments,
    get_judgment,
    list_cases,
    save_feedback,
    get_feedback_for_judgment,
)


CASE_ID_BY_SITUATION_KEYWORD: dict[str, str] = {
    "5,000チップ2枚 + 1,000チップ2枚": "case-001-multi-chip-bet",
    "HJ（順番的にはまだアクションしていない）": "case-002-oot-action-changes",
    "配り始めた1周目": "case-003-misdeal-exposed-downcards",
    "膝の上でスマホの画面": "case-004-electronic-device-live-hand",
    "観戦者": "case-005-one-player-to-a-hand",
}


def normalize_rule_match(rule_id: str, text: str) -> bool:
    """Rule-45 matches both 'Rule-45', 'Rule 45', 'Rule45'."""
    prefix = "RP" if rule_id.startswith("RP-") else "Rule"
    num = rule_id.replace("Rule-", "").replace("RP-", "")
    patterns = [
        f"{prefix}-{num}",
        f"{prefix} {num}",
        f"{prefix}{num}",
    ]
    return any(p in text for p in patterns)


def evaluate(response_text: str, expected_rules: list[str]) -> tuple[str, int, int]:
    if not expected_rules:
        return "correct", 0, 0
    hits = sum(1 for r in expected_rules if normalize_rule_match(r, response_text))
    ratio = hits / len(expected_rules)
    if ratio >= 1.0:
        rating = "correct"
    elif ratio >= 0.5:
        rating = "partial"
    else:
        rating = "wrong"
    return rating, hits, len(expected_rules)


def match_case(judgment: dict, all_cases: list[dict]) -> dict | None:
    """Match a judgment back to its source case by situation keyword."""
    situation = judgment.get("situation", "")
    for keyword, case_id in CASE_ID_BY_SITUATION_KEYWORD.items():
        if keyword in situation:
            return next((c for c in all_cases if c["id"] == case_id), None)
    return None


def main() -> int:
    cases = list_cases()

    # Pull all recent judgments (last 20 should cover the test runs)
    recent = list_recent_judgments(limit=20)
    if not recent:
        print("❌ No judgments to re-evaluate")
        return 1

    # Filter to real-model judgments (not session-mock)
    real_judgments: list[dict] = []
    for summary in recent:
        full = get_judgment(summary["id"])
        if not full:
            continue
        if full.get("model", "").endswith("[session-mock]"):
            continue
        real_judgments.append(full)

    if not real_judgments:
        print("❌ No real-API judgments found (only session-mock)")
        return 1

    print("=" * 70)
    print(f"既存判断の再評価 — {len(real_judgments)}件")
    print("=" * 70)
    print()

    for j in real_judgments:
        case = match_case(j, cases)
        if not case:
            print(f"⚠️  Case not matched for {j['id']}")
            continue
        expected_rules = json.loads(case["expected_rules"]) if case["expected_rules"] else []
        rating, hits, total = evaluate(j["response_text"], expected_rules)

        icon = {"correct": "✅", "partial": "🟡", "wrong": "❌"}[rating]
        print(f"{icon} {j['id']}  case={case['id']}")
        print(f"   {rating}  rules {hits}/{total}")

        # Check if latest feedback is already the correct one
        existing = get_feedback_for_judgment(j["id"])
        if existing and existing[-1].get("reviewer") == "reeval_v1":
            print(f"   (already re-evaluated, skipping)")
            continue

        save_feedback(
            judgment_id=j["id"],
            rating=rating,
            correct_judgment=None,
            comment=(
                f"再評価 (v1): 正規表現マッチャー修正後。"
                f"expected_rules {hits}/{total} 一致。"
                f"期待: {expected_rules}"
            ),
            reviewer="reeval_v1",
        )
        print(f"   ✓ feedback updated")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

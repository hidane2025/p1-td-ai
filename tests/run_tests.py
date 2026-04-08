#!/usr/bin/env python3
"""
TD判断AI テストランナー v0.1
judgment_cases.json の各ケースで judge() を呼び、期待される判断と比較する。

使い方:
  export ANTHROPIC_API_KEY=sk-ant-...
  python tests/run_tests.py
  python tests/run_tests.py --verbose
"""

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from cli import judge, load_cases  # noqa: E402


def check_rule_match(response_text: str, expected_rules: list[str]) -> tuple[int, int]:
    """応答に期待するルールIDがどれだけ含まれるか"""
    hit = sum(1 for rule_id in expected_rules if rule_id in response_text)
    return hit, len(expected_rules)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="先頭N件だけテスト")
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]

    if not cases:
        print("❌ テストケースがありません。data/cases/judgment_cases.json を更新してください")
        return 1

    print(f"=== TD判断AI テスト ({len(cases)}件) ===\n")
    pass_count = 0
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}: {case['situation'][:60]}...")
        extra = {
            k: case[k]
            for k in ("tournament_phase", "blinds", "game_type")
            if k in case
        }
        try:
            response = judge(case["situation"], extra or None)
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            continue

        hit, total = check_rule_match(response, case.get("expected_rules", []))
        passed = total == 0 or hit >= total
        status = "✅ PASS" if passed else f"❌ FAIL ({hit}/{total})"
        print(f"  {status}")
        if passed:
            pass_count += 1
        if args.verbose or not passed:
            print("  --- Response ---")
            for line in response.split("\n")[:30]:
                print(f"  {line}")
            print("  ---")
        print()

    print(f"\n=== 結果: {pass_count}/{len(cases)} PASS ===")
    return 0 if pass_count == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())

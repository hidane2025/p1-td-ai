#!/usr/bin/env python3
"""
Phase 1 A/B テスト — prompt v0.1 vs v0.2

全10判例について v0.1 と v0.2 で judge() を呼び、required/recommended
分離式 evaluator で rating + quality_score を比較する。

v0.1 については可能なら既存 DB の最新判断を再利用（コスト節約）。
v0.2 については新規 API 呼び出しを行う。

使い方:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 scripts/ab_test_v01_vs_v02.py
    python3 scripts/ab_test_v01_vs_v02.py --rerun-v01  # v0.1 も新規実行
    python3 scripts/ab_test_v01_vs_v02.py --only case-001-multi-chip-bet
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from judge import judge  # noqa: E402
from db import (  # noqa: E402
    init_db,
    save_feedback,
    connect,
)
from evaluator import evaluate, EvalResult  # noqa: E402


CASES_JSON_PATH = BASE_DIR / "data" / "cases" / "judgment_cases.json"


def load_cases_with_required_recommended() -> list[dict]:
    """JSON から cases を読み、required_rules/recommended_rules を持つものだけ返す"""
    with open(CASES_JSON_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)
    return [c for c in cases if "required_rules" in c]


def find_latest_v01_judgment(case_situation_keyword: str) -> dict | None:
    """DBから指定ケースの v0.1 judgment で最も新しいものを返す。
    session-mock は除外（実APIのみ）。"""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM judgments
            WHERE prompt_version = 'v0.1'
              AND situation LIKE ?
              AND model NOT LIKE '%session-mock%'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (f"%{case_situation_keyword}%",),
        ).fetchone()
        return dict(rows) if rows else None


# ケースごとに v0.1 判断を特定するためのキーワード
CASE_SITUATION_KEY: dict[str, str] = {
    "case-001-multi-chip-bet": "5,000チップ2枚",
    "case-002-oot-action-changes": "HJ（順番的にはまだアクションしていない）",
    "case-003-misdeal-exposed-downcards": "配り始めた1周目",
    "case-004-electronic-device-live-hand": "膝の上でスマホ",
    "case-005-one-player-to-a-hand": "heads-up ハンド",
    "case-006-all-in-showdown-muck": "muck の動作",
    "case-007-verbal-bet-trick": "『I bet』",
    "case-008-string-bet-raise": "約 1 秒後に追加",
    "case-009-soft-play-collusion-suspicion": "you got it, buddy",
    "case-010-big-blind-ante-dispute": "BBA",
}


def run_judge_v02(case: dict) -> dict:
    """v0.2 で judgment を作成"""
    extra = {
        k: case[k]
        for k in ("tournament_phase", "blinds", "game_type")
        if case.get(k)
    }
    return judge(
        situation=case["situation"],
        extra_context=extra or None,
        prompt_version="v0.2",
    )


def compare_case(case: dict, rerun_v01: bool) -> dict:
    required = case["required_rules"]
    recommended = case.get("recommended_rules", [])

    # v0.1 side
    v01_text: str | None = None
    v01_latency: int | None = None
    v01_tokens: dict | None = None
    v01_judgment_id: str | None = None

    if rerun_v01:
        print(f"  → v0.1 rerun...")
        result = judge(
            situation=case["situation"],
            extra_context={k: case[k] for k in ("tournament_phase", "blinds", "game_type") if case.get(k)} or None,
            prompt_version="v0.1",
        )
        v01_text = result["response"]
        v01_latency = result["latency_ms"]
        v01_tokens = result["token_usage"]
        v01_judgment_id = result["judgment_id"]
    else:
        kw = CASE_SITUATION_KEY.get(case["id"])
        if kw:
            existing = find_latest_v01_judgment(kw)
            if existing:
                v01_text = existing["response_text"]
                v01_latency = existing["latency_ms"]
                v01_tokens = json.loads(existing["token_usage"]) if existing["token_usage"] else None
                v01_judgment_id = existing["id"]

    if v01_text is None:
        print(f"  ⚠️  v0.1 判断が見つからず、新規実行します")
        result = judge(
            situation=case["situation"],
            extra_context={k: case[k] for k in ("tournament_phase", "blinds", "game_type") if case.get(k)} or None,
            prompt_version="v0.1",
        )
        v01_text = result["response"]
        v01_latency = result["latency_ms"]
        v01_tokens = result["token_usage"]
        v01_judgment_id = result["judgment_id"]

    v01_eval = evaluate(v01_text, required, recommended)

    # v0.2 side
    print(f"  → v0.2 judging...")
    v02_result = run_judge_v02(case)
    v02_text = v02_result["response"]
    v02_latency = v02_result["latency_ms"]
    v02_tokens = v02_result["token_usage"]
    v02_judgment_id = v02_result["judgment_id"]
    v02_eval = evaluate(v02_text, required, recommended)

    # Save feedback for v0.2 judgment
    save_feedback(
        judgment_id=v02_judgment_id,
        rating=v02_eval.rating,
        comment=(
            f"A/B テスト (v0.2): required {v02_eval.required_hits}/{v02_eval.required_total}, "
            f"recommended {v02_eval.recommended_hits}/{v02_eval.recommended_total}, "
            f"quality {v02_eval.quality_score:.2f}"
        ),
        reviewer="ab_test_v01_vs_v02",
    )

    # If v0.1 was a rerun, also save feedback for it
    if rerun_v01:
        save_feedback(
            judgment_id=v01_judgment_id,
            rating=v01_eval.rating,
            comment=(
                f"A/B テスト (v0.1 rerun): required {v01_eval.required_hits}/{v01_eval.required_total}, "
                f"recommended {v01_eval.recommended_hits}/{v01_eval.recommended_total}, "
                f"quality {v01_eval.quality_score:.2f}"
            ),
            reviewer="ab_test_v01_vs_v02",
        )

    return {
        "case_id": case["id"],
        "category": case["category"],
        "v01": {
            "judgment_id": v01_judgment_id,
            "eval": v01_eval.to_dict(),
            "latency_ms": v01_latency,
            "tokens": v01_tokens,
        },
        "v02": {
            "judgment_id": v02_judgment_id,
            "eval": v02_eval.to_dict(),
            "latency_ms": v02_latency,
            "tokens": v02_tokens,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerun-v01", action="store_true", help="Re-run v0.1 with fresh API calls")
    parser.add_argument("--only", help="Only test this case_id")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set")
        return 1

    init_db()
    cases = load_cases_with_required_recommended()
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
        if not cases:
            print(f"❌ Case not found: {args.only}")
            return 1

    print("=" * 80)
    print(f"Phase 1 A/B テスト — v0.1 vs v0.2 ({len(cases)}判例)")
    print("=" * 80)
    print()

    results: list[dict] = []
    for i, c in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {c['id']} — {c['category']}")
        try:
            result = compare_case(c, rerun_v01=args.rerun_v01)
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            continue
        results.append(result)
        v01_e = result["v01"]["eval"]
        v02_e = result["v02"]["eval"]
        icon_v01 = {"correct": "✅", "partial": "🟡", "wrong": "❌"}[v01_e["rating"]]
        icon_v02 = {"correct": "✅", "partial": "🟡", "wrong": "❌"}[v02_e["rating"]]
        delta = v02_e["quality_score"] - v01_e["quality_score"]
        delta_str = f"+{delta:.2f}" if delta >= 0 else f"{delta:.2f}"
        print(
            f"  v0.1: {icon_v01} {v01_e['rating']:7s} req={v01_e['required_hits']}/{v01_e['required_total']} "
            f"rec={v01_e['recommended_hits']}/{v01_e['recommended_total']} "
            f"quality={v01_e['quality_score']:.2f}"
        )
        print(
            f"  v0.2: {icon_v02} {v02_e['rating']:7s} req={v02_e['required_hits']}/{v02_e['required_total']} "
            f"rec={v02_e['recommended_hits']}/{v02_e['recommended_total']} "
            f"quality={v02_e['quality_score']:.2f}  Δ {delta_str}"
        )
        print()

    # === Summary ===
    print("=" * 80)
    print("📊 A/B Summary")
    print("=" * 80)
    v01_correct = sum(1 for r in results if r["v01"]["eval"]["rating"] == "correct")
    v02_correct = sum(1 for r in results if r["v02"]["eval"]["rating"] == "correct")
    v01_partial = sum(1 for r in results if r["v01"]["eval"]["rating"] == "partial")
    v02_partial = sum(1 for r in results if r["v02"]["eval"]["rating"] == "partial")
    v01_wrong = sum(1 for r in results if r["v01"]["eval"]["rating"] == "wrong")
    v02_wrong = sum(1 for r in results if r["v02"]["eval"]["rating"] == "wrong")
    v01_avg_quality = sum(r["v01"]["eval"]["quality_score"] for r in results) / len(results) if results else 0
    v02_avg_quality = sum(r["v02"]["eval"]["quality_score"] for r in results) / len(results) if results else 0

    print(f"  {'':15s}  v0.1   v0.2   Δ")
    print(f"  {'correct':15s}  {v01_correct:3d}    {v02_correct:3d}    {v02_correct - v01_correct:+d}")
    print(f"  {'partial':15s}  {v01_partial:3d}    {v02_partial:3d}    {v02_partial - v01_partial:+d}")
    print(f"  {'wrong':15s}  {v01_wrong:3d}    {v02_wrong:3d}    {v02_wrong - v01_wrong:+d}")
    print(f"  {'avg quality':15s}  {v01_avg_quality:.2f}   {v02_avg_quality:.2f}   {v02_avg_quality - v01_avg_quality:+.2f}")

    # Token & cost
    v02_in = sum(r["v02"]["tokens"]["input"] for r in results if r["v02"]["tokens"])
    v02_out = sum(r["v02"]["tokens"]["output"] for r in results if r["v02"]["tokens"])
    v02_cost = (v02_in / 1e6) * 3.0 + (v02_out / 1e6) * 15.0
    print(f"\n  v0.2 total tokens: in={v02_in:,}  out={v02_out:,}  cost=${v02_cost:.4f}")

    # Verdict
    print()
    if v02_correct > v01_correct or v02_avg_quality > v01_avg_quality + 0.05:
        print("🎉 v0.2 の勝ち — 本番プロンプトを v0.2 に切り替え推奨")
    elif v02_correct < v01_correct or v02_avg_quality < v01_avg_quality - 0.05:
        print("⚠️  v0.2 の負け — プロンプトを再改訂")
    else:
        print("🤝 有意差なし — 追加判例で再テスト推奨")

    # Export detail JSON
    report_path = BASE_DIR / "reports" / "ab_test_v01_vs_v02.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": {
                    "v01_correct": v01_correct,
                    "v02_correct": v02_correct,
                    "v01_avg_quality": v01_avg_quality,
                    "v02_avg_quality": v02_avg_quality,
                },
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n✅ Detail report: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

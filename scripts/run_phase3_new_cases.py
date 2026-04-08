#!/usr/bin/env python3
"""
Phase 3 テスト — 新規10判例 (case-021〜030) × v0.2 + prompt caching

使い方:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 -u scripts/run_phase3_new_cases.py
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
        print("❌ ANTHROPIC_API_KEY not set", flush=True)
        return 1

    init_db()
    seed_cases_from_json(CASES_JSON)

    with open(CASES_JSON, "r", encoding="utf-8") as f:
        all_cases = json.load(f)

    target_ids = {f"case-{i:03d}" for i in range(21, 31)}
    cases = [c for c in all_cases if any(c["id"].startswith(tid) for tid in target_ids)]
    cases.sort(key=lambda c: c["id"])

    print("=" * 80, flush=True)
    print(f"Phase 3 新規10判例テスト — v0.2 + prompt caching", flush=True)
    print("=" * 80, flush=True)
    print(flush=True)

    results: list[dict] = []
    for i, c in enumerate(cases, 1):
        print(f"[{i:2d}/{len(cases)}] {c['id']} — {c['category']}", flush=True)
        extra = {
            k: c[k] for k in ("tournament_phase", "blinds", "game_type") if c.get(k)
        }
        try:
            result = judge(
                situation=c["situation"],
                extra_context=extra or None,
                prompt_version="v0.2",
            )
        except Exception as e:
            print(f"    ❌ ERROR: {e}", flush=True)
            continue

        ev = evaluate(
            result["response"],
            c.get("required_rules", c.get("expected_rules", [])),
            c.get("recommended_rules", []),
        )
        tok = result["token_usage"]
        cache_tag = "🟢CACHE" if result.get("cache_hit") else "  ----"
        print(
            f"    {ev.summary()}  {cache_tag}  "
            f"latency={result['latency_ms']}ms  "
            f"in={tok['input']} out={tok['output']} "
            f"cache_read={tok.get('cache_read',0)} cache_write={tok.get('cache_creation',0)}",
            flush=True,
        )

        save_feedback(
            judgment_id=result["judgment_id"],
            rating=ev.rating,
            comment=(
                f"Phase 3 新規10: req {ev.required_hits}/{ev.required_total}, "
                f"rec {ev.recommended_hits}/{ev.recommended_total}, "
                f"quality {ev.quality_score:.2f}, cache_hit={result.get('cache_hit')}"
            ),
            reviewer="run_phase3_new_cases",
        )
        results.append({"case": c, "eval": ev, "result": result})

    print(flush=True)
    print("=" * 80, flush=True)
    print("📊 Phase 3 新規10判例 結果", flush=True)
    print("=" * 80, flush=True)
    correct = sum(1 for r in results if r["eval"].rating == "correct")
    partial = sum(1 for r in results if r["eval"].rating == "partial")
    wrong = sum(1 for r in results if r["eval"].rating == "wrong")
    avg_q = sum(r["eval"].quality_score for r in results) / len(results) if results else 0
    total_in = sum(r["result"]["token_usage"]["input"] for r in results)
    total_out = sum(r["result"]["token_usage"]["output"] for r in results)
    cache_reads = sum(r["result"]["token_usage"].get("cache_read", 0) for r in results)
    cache_writes = sum(r["result"]["token_usage"].get("cache_creation", 0) for r in results)
    cache_hits = sum(1 for r in results if r["result"].get("cache_hit"))

    # Sonnet 4.5 pricing: $3/M in, $15/M out, $0.30/M cache read, $3.75/M cache write
    cost = (
        (total_in / 1e6) * 3.0
        + (total_out / 1e6) * 15.0
        + (cache_reads / 1e6) * 0.30
        + (cache_writes / 1e6) * 3.75
    )
    cost_no_cache = (total_in + cache_reads + cache_writes) / 1e6 * 3.0 + (total_out / 1e6) * 15.0
    savings = cost_no_cache - cost

    print(f"  件数        : {len(results)}", flush=True)
    print(f"  correct     : {correct} ({correct/len(results)*100:.0f}%)", flush=True)
    print(f"  partial     : {partial}", flush=True)
    print(f"  wrong       : {wrong}", flush=True)
    print(f"  avg quality : {avg_q:.3f}", flush=True)
    print(f"  cache hits  : {cache_hits}/{len(results)}", flush=True)
    print(f"  tokens in   : {total_in:,}  (cache_read {cache_reads:,}, cache_write {cache_writes:,})", flush=True)
    print(f"  tokens out  : {total_out:,}", flush=True)
    print(f"  cost        : ${cost:.4f}", flush=True)
    print(f"  (no cache)  : ${cost_no_cache:.4f}", flush=True)
    print(f"  savings     : ${savings:.4f} ({savings/cost_no_cache*100:.0f}%)", flush=True)

    wrongs = [r for r in results if r["eval"].rating != "correct"]
    if wrongs:
        print(flush=True)
        print("  === Non-correct cases ===", flush=True)
        for r in wrongs:
            c = r["case"]
            ev = r["eval"]
            print(f"  {r['eval'].rating}: {c['id']} req_missing={ev.required_missing}", flush=True)

    return 0 if correct >= len(results) * 0.9 else 1


if __name__ == "__main__":
    sys.exit(main())

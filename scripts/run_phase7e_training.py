#!/usr/bin/env python3
"""
Phase 7E トレーニング — 新規34判例 (case-107〜140) バッチ評価

使い方:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 -u scripts/run_phase7e_training.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from judge import judge  # noqa: E402
from db import init_db, save_feedback, seed_cases_from_json  # noqa: E402
from evaluator import evaluate  # noqa: E402

CASES_JSON = BASE_DIR / "data" / "cases" / "judgment_cases.json"
REPORT_PATH = BASE_DIR / "reports" / f"phase7e_training_{datetime.now().strftime('%Y-%m-%d')}.md"


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set", flush=True)
        return 1

    init_db()
    seed_cases_from_json(CASES_JSON)

    with open(CASES_JSON, "r", encoding="utf-8") as f:
        all_cases = json.load(f)

    # Target: case-107 to case-140 (Phase 7E new cases)
    target_ids = {f"case-{i:03d}" for i in range(107, 141)}
    cases = [c for c in all_cases if any(c["id"].startswith(tid) for tid in target_ids)]
    cases.sort(key=lambda c: c["id"])

    if not cases:
        print("❌ No target cases found", flush=True)
        return 1

    print("=" * 80, flush=True)
    print(f"Phase 7E Training — {len(cases)} new cases", flush=True)
    print(f"Active prompt: v0.5 | Model: claude-sonnet-4-5", flush=True)
    print("=" * 80, flush=True)
    print(flush=True)

    results: list[dict] = []
    errors: list[str] = []

    for i, c in enumerate(cases, 1):
        print(f"[{i:2d}/{len(cases)}] {c['id']} — {c['category']}", flush=True)
        extra = {
            k: c[k] for k in ("tournament_phase", "blinds", "game_type") if c.get(k)
        }
        try:
            result = judge(
                situation=c["situation"],
                extra_context=extra or None,
            )
        except Exception as e:
            print(f"    ❌ ERROR: {e}", flush=True)
            errors.append(f"{c['id']}: {e}")
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
            f"cache_read={tok.get('cache_read',0)}",
            flush=True,
        )

        save_feedback(
            judgment_id=result["judgment_id"],
            rating=ev.rating,
            comment=(
                f"Phase 7E: req {ev.required_hits}/{ev.required_total}, "
                f"rec {ev.recommended_hits}/{ev.recommended_total}, "
                f"quality {ev.quality_score:.2f}"
            ),
            reviewer="run_phase7e_training",
        )
        results.append({"case": c, "eval": ev, "result": result})

        # Rate limiting: small delay between calls
        if i < len(cases):
            time.sleep(0.5)

    # === Summary ===
    print(flush=True)
    print("=" * 80, flush=True)
    print(f"📊 Phase 7E Training Results — {len(results)}/{len(cases)} evaluated", flush=True)
    print("=" * 80, flush=True)

    if not results:
        print("No results to summarize.", flush=True)
        return 1

    correct = sum(1 for r in results if r["eval"].rating == "correct")
    partial = sum(1 for r in results if r["eval"].rating == "partial")
    wrong = sum(1 for r in results if r["eval"].rating == "wrong")
    avg_q = sum(r["eval"].quality_score for r in results) / len(results)
    total_in = sum(r["result"]["token_usage"]["input"] for r in results)
    total_out = sum(r["result"]["token_usage"]["output"] for r in results)
    cache_reads = sum(r["result"]["token_usage"].get("cache_read", 0) for r in results)
    cache_writes = sum(r["result"]["token_usage"].get("cache_creation", 0) for r in results)
    cache_hits = sum(1 for r in results if r["result"].get("cache_hit"))

    # Sonnet pricing
    cost = (
        (total_in / 1e6) * 3.0
        + (total_out / 1e6) * 15.0
        + (cache_reads / 1e6) * 0.30
        + (cache_writes / 1e6) * 3.75
    )
    accuracy = correct / len(results) * 100

    print(f"  件数        : {len(results)}", flush=True)
    print(f"  correct     : {correct} ({accuracy:.1f}%)", flush=True)
    print(f"  partial     : {partial}", flush=True)
    print(f"  wrong       : {wrong}", flush=True)
    print(f"  avg quality : {avg_q:.3f}", flush=True)
    print(f"  cache hits  : {cache_hits}/{len(results)}", flush=True)
    print(f"  cost        : ${cost:.4f} (¥{cost * 150:.0f})", flush=True)

    wrongs = [r for r in results if r["eval"].rating != "correct"]
    if wrongs:
        print(flush=True)
        print("  === Non-correct cases ===", flush=True)
        for r in wrongs:
            c = r["case"]
            ev = r["eval"]
            print(f"  {ev.rating}: {c['id']} ({c['category']}) req_missing={ev.required_missing}", flush=True)

    if errors:
        print(flush=True)
        print(f"  === Errors ({len(errors)}) ===", flush=True)
        for e in errors:
            print(f"  {e}", flush=True)

    # === Generate Report ===
    report = f"""# Phase 7E Training Report — {datetime.now().strftime('%Y-%m-%d')}

## Summary

| Metric | Value |
|--------|-------|
| Cases evaluated | {len(results)}/{len(cases)} |
| Correct | {correct} ({accuracy:.1f}%) |
| Partial | {partial} |
| Wrong | {wrong} |
| Avg Quality | {avg_q:.3f} |
| Cache Hits | {cache_hits}/{len(results)} |
| Total Cost | ${cost:.4f} (¥{cost * 150:.0f}) |
| Total DB Cases | 107 |
| Rule Coverage | 87/93 |

## Non-Correct Cases

"""
    for r in wrongs:
        c = r["case"]
        ev = r["eval"]
        report += f"### {c['id']} — {c['category']}\n"
        report += f"- Rating: {ev.rating}\n"
        report += f"- Required missing: {ev.required_missing}\n"
        report += f"- Quality: {ev.quality_score:.2f}\n\n"

    if not wrongs:
        report += "None — 100% correct!\n"

    report += f"\n## Errors\n\n"
    if errors:
        for e in errors:
            report += f"- {e}\n"
    else:
        report += "None\n"

    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\n📝 Report saved: {REPORT_PATH}", flush=True)

    return 0 if accuracy >= 95.0 else 1


if __name__ == "__main__":
    sys.exit(main())

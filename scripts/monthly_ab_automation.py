#!/usr/bin/env python3
"""
TD判断AI — 月次 A/B テスト自動化 v0.1 (Phase 3)

月次で最新プロンプトバージョンと candidate バージョンを比較し、勝者を自動 activate する。

### フロー
1. `prompts/versions/system_v{X+1}.md` が存在するか確認
2. 全判例（judgment_cases.json）に対して v{現active} vs v{X+1} で判断生成
3. evaluator で精度と quality を比較
4. candidate が有意に勝った場合、activate を切り替え
5. 結果をレポートとして `reports/monthly_ab_{YYYY-MM}.md` に保存

### 勝利条件（いずれかを満たせば勝ち）
- correct_count が +2 以上
- avg_quality_score が +0.05 以上
- wrong_count が -2 以下

### 使い方
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 scripts/monthly_ab_automation.py                   # dry run（activate しない）
    python3 scripts/monthly_ab_automation.py --apply           # 勝った場合は activate
    python3 scripts/monthly_ab_automation.py --candidate v0.3  # 特定バージョン指定

### cron 例
    # 毎月1日 朝9時に実行
    0 9 1 * * cd /path/to/TD-AI && python3 scripts/monthly_ab_automation.py --apply >> logs/ab.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from judge import judge  # noqa: E402
from db import (  # noqa: E402
    init_db,
    get_active_prompt_version,
    list_prompt_versions,
    activate_prompt_version,
    register_prompt_version,
    save_feedback,
)
from evaluator import evaluate  # noqa: E402

CASES_JSON = BASE_DIR / "data" / "cases" / "judgment_cases.json"
PROMPTS_VERSIONS_DIR = BASE_DIR / "prompts" / "versions"
REPORTS_DIR = BASE_DIR / "reports"


def find_candidate_version(current: str) -> str | None:
    """Look for the next prompt version file.
    Current v0.2 → looks for v0.3, v0.4, etc. Returns first found."""
    # Parse "v0.2" → major=0, minor=2
    try:
        vstr = current.lstrip("v")
        major, minor = vstr.split(".")
        major, minor = int(major), int(minor)
    except Exception:
        return None

    # Try next minor versions
    for i in range(1, 10):
        candidate = f"v{major}.{minor + i}"
        if (PROMPTS_VERSIONS_DIR / f"system_{candidate}.md").exists():
            return candidate
    # Try next major
    next_major_candidate = f"v{major + 1}.0"
    if (PROMPTS_VERSIONS_DIR / f"system_{next_major_candidate}.md").exists():
        return next_major_candidate
    return None


def register_if_missing(version: str) -> None:
    """Register a candidate prompt if not yet in DB"""
    existing = [v["version"] for v in list_prompt_versions()]
    if version in existing:
        return
    register_prompt_version(
        version=version,
        path=f"prompts/versions/system_{version}.md",
        parent_version=None,
        change_notes=f"Auto-registered by monthly_ab_automation ({datetime.now().isoformat()})",
        activate=False,
    )


def run_version_on_cases(version: str, cases: list[dict]) -> list[dict]:
    """Run all cases with the given prompt version and return evaluation results."""
    results = []
    for i, c in enumerate(cases, 1):
        print(f"  [{i:2d}/{len(cases)}] {c['id']}  ({version})", flush=True)
        extra = {
            k: c[k] for k in ("tournament_phase", "blinds", "game_type") if c.get(k)
        }
        try:
            result = judge(
                situation=c["situation"],
                extra_context=extra or None,
                prompt_version=version,
            )
        except Exception as e:
            print(f"     ❌ ERROR: {e}", flush=True)
            continue

        ev = evaluate(
            result["response"],
            c.get("required_rules", c.get("expected_rules", [])),
            c.get("recommended_rules", []),
        )
        save_feedback(
            judgment_id=result["judgment_id"],
            rating=ev.rating,
            comment=f"月次A/B ({version}): req {ev.required_hits}/{ev.required_total}",
            reviewer="monthly_ab_automation",
        )
        results.append({"case_id": c["id"], "eval": ev, "result": result})
    return results


def compute_metrics(results: list[dict]) -> dict:
    if not results:
        return {"count": 0}
    correct = sum(1 for r in results if r["eval"].rating == "correct")
    partial = sum(1 for r in results if r["eval"].rating == "partial")
    wrong = sum(1 for r in results if r["eval"].rating == "wrong")
    avg_q = sum(r["eval"].quality_score for r in results) / len(results)
    tokens_in = sum(r["result"]["token_usage"]["input"] for r in results)
    tokens_out = sum(r["result"]["token_usage"]["output"] for r in results)
    cost = (tokens_in / 1e6) * 3.0 + (tokens_out / 1e6) * 15.0
    return {
        "count": len(results),
        "correct": correct,
        "partial": partial,
        "wrong": wrong,
        "avg_quality": avg_q,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": cost,
    }


def decide_winner(active_metrics: dict, candidate_metrics: dict) -> tuple[bool, list[str]]:
    """Return (candidate_wins, reasons)"""
    reasons = []
    candidate_wins = False

    d_correct = candidate_metrics["correct"] - active_metrics["correct"]
    d_quality = candidate_metrics["avg_quality"] - active_metrics["avg_quality"]
    d_wrong = candidate_metrics["wrong"] - active_metrics["wrong"]

    if d_correct >= 2:
        candidate_wins = True
        reasons.append(f"correct count +{d_correct} (>=2)")
    if d_quality >= 0.05:
        candidate_wins = True
        reasons.append(f"avg_quality +{d_quality:.3f} (>=0.05)")
    if d_wrong <= -2:
        candidate_wins = True
        reasons.append(f"wrong count {d_wrong} (<=-2)")

    if not candidate_wins:
        reasons.append(
            f"Insufficient improvement: Δcorrect={d_correct}, "
            f"Δquality={d_quality:+.3f}, Δwrong={d_wrong}"
        )
    return candidate_wins, reasons


def render_report(active: str, candidate: str, am: dict, cm: dict, win: bool, reasons: list[str]) -> str:
    lines = []
    month = datetime.now().strftime("%Y-%m")
    lines.append(f"# 月次 A/B テストレポート — {month}")
    lines.append("")
    lines.append(f"- Active: **{active}**")
    lines.append(f"- Candidate: **{candidate}**")
    lines.append(f"- Cases: {am['count']}")
    lines.append("")
    lines.append("## 📊 Metrics Comparison")
    lines.append("")
    lines.append("| Metric | Active | Candidate | Δ |")
    lines.append("|---|---|---|---|")
    lines.append(f"| correct | {am['correct']} | {cm['correct']} | {cm['correct']-am['correct']:+d} |")
    lines.append(f"| partial | {am['partial']} | {cm['partial']} | {cm['partial']-am['partial']:+d} |")
    lines.append(f"| wrong | {am['wrong']} | {cm['wrong']} | {cm['wrong']-am['wrong']:+d} |")
    lines.append(f"| avg_quality | {am['avg_quality']:.3f} | {cm['avg_quality']:.3f} | {cm['avg_quality']-am['avg_quality']:+.3f} |")
    lines.append(f"| cost | ${am['cost']:.4f} | ${cm['cost']:.4f} | ${cm['cost']-am['cost']:+.4f} |")
    lines.append("")
    lines.append("## 🏆 Verdict")
    lines.append("")
    if win:
        lines.append(f"🎉 **Candidate {candidate} wins** — recommend activate")
    else:
        lines.append(f"🤝 **No significant improvement** — keep {active} active")
    lines.append("")
    lines.append("### Reasons")
    for r in reasons:
        lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Activate winning candidate")
    parser.add_argument("--candidate", help="Specific candidate version (default: auto-detect)")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set", flush=True)
        return 1

    init_db()

    active = get_active_prompt_version()
    if not active:
        print("❌ No active prompt version", flush=True)
        return 1
    active_version = active["version"]

    candidate_version = args.candidate or find_candidate_version(active_version)
    if not candidate_version:
        print(
            f"ℹ️  No candidate version found. Active: {active_version}. "
            f"Create prompts/versions/system_v{active_version.lstrip('v').split('.')[0]}.{int(active_version.lstrip('v').split('.')[1]) + 1}.md to propose a candidate.",
            flush=True,
        )
        return 0

    register_if_missing(candidate_version)
    print(f"=== Monthly A/B Test ===", flush=True)
    print(f"Active:    {active_version}", flush=True)
    print(f"Candidate: {candidate_version}", flush=True)
    print(flush=True)

    with open(CASES_JSON, "r", encoding="utf-8") as f:
        cases = json.load(f)
    # Only cases with required_rules
    cases = [c for c in cases if c.get("required_rules")]
    print(f"Cases: {len(cases)}", flush=True)
    print(flush=True)

    print(f"Running {active_version}...", flush=True)
    active_results = run_version_on_cases(active_version, cases)
    am = compute_metrics(active_results)

    print(flush=True)
    print(f"Running {candidate_version}...", flush=True)
    candidate_results = run_version_on_cases(candidate_version, cases)
    cm = compute_metrics(candidate_results)

    win, reasons = decide_winner(am, cm)

    report = render_report(active_version, candidate_version, am, cm, win, reasons)
    print(flush=True)
    print(report)

    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"monthly_ab_{datetime.now().strftime('%Y-%m')}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n✅ Report saved: {report_path}", flush=True)

    if win and args.apply:
        activate_prompt_version(candidate_version)
        print(f"🎯 Activated {candidate_version} (--apply)", flush=True)
    elif win:
        print(f"⏸️  Not applied (dry run). Run with --apply to activate {candidate_version}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

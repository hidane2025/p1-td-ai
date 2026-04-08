"""
TD判断AI — メトリクス & 月次レポート v0.1

責務:
- 判断数・フィードバック率・正答率の集計
- Rule 別の得意/苦手カテゴリの抽出
- プロンプトバージョン別の精度比較
- 月次 Markdown レポート生成

使い方:
  python metrics.py                       # 全期間サマリ
  python metrics.py --month 2026-04       # 月次レポート
  python metrics.py --versions            # プロンプト別比較
  python metrics.py --export report.md    # Markdown 出力
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from db import connect, init_db  # noqa: E402


def fetch_all_judgments(month: str | None = None) -> list[dict]:
    query = "SELECT * FROM judgments"
    params: list = []
    if month:
        query += " WHERE created_at LIKE ?"
        params.append(f"{month}%")
    query += " ORDER BY created_at"
    with connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def fetch_all_feedback() -> dict[str, list[dict]]:
    """Return {judgment_id: [feedback rows]}"""
    by_judgment: dict[str, list[dict]] = defaultdict(list)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM feedback ORDER BY created_at").fetchall()
        for r in rows:
            by_judgment[r["judgment_id"]].append(dict(r))
    return by_judgment


def compute_summary(judgments: list[dict], feedback_map: dict[str, list[dict]]) -> dict:
    total = len(judgments)
    if total == 0:
        return {"total": 0}

    confidence_counts: dict[str, int] = defaultdict(int)
    rule_hit_counts: dict[str, int] = defaultdict(int)
    version_counts: dict[str, int] = defaultdict(int)
    latency_ms_sum = 0
    latency_ms_count = 0
    input_tokens_sum = 0
    output_tokens_sum = 0

    feedback_rating_counts: dict[str, int] = defaultdict(int)
    judgments_with_feedback = 0

    for j in judgments:
        confidence_counts[j.get("confidence") or "unknown"] += 1
        version_counts[j.get("prompt_version") or "unknown"] += 1
        if j.get("latency_ms") is not None:
            latency_ms_sum += j["latency_ms"]
            latency_ms_count += 1
        if j.get("token_usage"):
            usage = json.loads(j["token_usage"])
            input_tokens_sum += usage.get("input", 0)
            output_tokens_sum += usage.get("output", 0)
        if j.get("referenced_rules"):
            for r in json.loads(j["referenced_rules"]):
                rule_hit_counts[r] += 1

        fbs = feedback_map.get(j["id"], [])
        if fbs:
            judgments_with_feedback += 1
            # Use the latest rating
            latest = fbs[-1]
            feedback_rating_counts[latest["rating"]] += 1

    feedback_coverage = (
        judgments_with_feedback / total if total else 0
    )
    correct_rate = (
        feedback_rating_counts["correct"] / judgments_with_feedback
        if judgments_with_feedback
        else None
    )
    avg_latency = latency_ms_sum / latency_ms_count if latency_ms_count else 0

    return {
        "total": total,
        "by_confidence": dict(confidence_counts),
        "by_version": dict(version_counts),
        "top_rules_cited": sorted(
            rule_hit_counts.items(), key=lambda x: -x[1]
        )[:10],
        "feedback_coverage": feedback_coverage,
        "feedback_rating_counts": dict(feedback_rating_counts),
        "correct_rate": correct_rate,
        "avg_latency_ms": avg_latency,
        "total_tokens": {
            "input": input_tokens_sum,
            "output": output_tokens_sum,
        },
    }


def render_summary_md(summary: dict, title: str) -> str:
    if summary.get("total", 0) == 0:
        return f"# {title}\n\n判断レコードがありません。\n"

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**生成日時**: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")

    # === Summary ===
    lines.append("## 📊 サマリ")
    lines.append("")
    lines.append(f"- **総判断件数**: {summary['total']}")
    lines.append(f"- **平均レスポンスタイム**: {summary['avg_latency_ms']:.0f} ms")
    tok = summary["total_tokens"]
    lines.append(f"- **累計トークン使用**: input={tok['input']:,} / output={tok['output']:,}")
    # Rough cost estimate for Sonnet 4.5: $3/1M input, $15/1M output
    cost = (tok["input"] / 1e6) * 3.0 + (tok["output"] / 1e6) * 15.0
    lines.append(f"- **累計コスト概算** (Sonnet 4.5): ${cost:.3f}")
    lines.append("")

    # === Confidence distribution ===
    lines.append("## 🎚️ 確信度分布")
    lines.append("")
    for level in ("high", "medium", "low", "unknown"):
        count = summary["by_confidence"].get(level, 0)
        pct = (count / summary["total"]) * 100 if summary["total"] else 0
        lines.append(f"- **{level}**: {count} ({pct:.1f}%)")
    lines.append("")

    # === Feedback ===
    lines.append("## ✅ フィードバック")
    lines.append("")
    lines.append(f"- **フィードバック取得率**: {summary['feedback_coverage']*100:.1f}%")
    if summary["correct_rate"] is not None:
        lines.append(f"- **正答率**: {summary['correct_rate']*100:.1f}%")
    else:
        lines.append("- **正答率**: （フィードバック未収集）")
    for rating in ("correct", "partial", "wrong"):
        count = summary["feedback_rating_counts"].get(rating, 0)
        lines.append(f"  - `{rating}`: {count}")
    lines.append("")

    # === Top rules cited ===
    lines.append("## 📚 参照頻度トップ10ルール")
    lines.append("")
    for rule_id, count in summary["top_rules_cited"]:
        lines.append(f"- **{rule_id}**: {count} 回")
    lines.append("")

    # === Version distribution ===
    lines.append("## 🔁 プロンプトバージョン別")
    lines.append("")
    for version, count in sorted(summary["by_version"].items()):
        lines.append(f"- **{version}**: {count} 件")
    lines.append("")

    # === Action items ===
    lines.append("## 💡 改善提案（ミナから）")
    lines.append("")
    proposals: list[str] = []
    if summary["feedback_coverage"] < 0.3:
        proposals.append(
            "フィードバック取得率が30%未満です。現場TDへのフィードバック入力を促進してください。"
        )
    if summary["correct_rate"] is not None and summary["correct_rate"] < 0.8:
        proposals.append(
            f"正答率が {summary['correct_rate']*100:.0f}% と目標80%を下回っています。"
            "失敗ケースのカテゴリを分析し、プロンプト改訂またはルール補強を検討してください。"
        )
    low_count = summary["by_confidence"].get("low", 0)
    if low_count > summary["total"] * 0.2:
        proposals.append(
            f"confidence=low が {low_count} 件（全体の"
            f"{low_count/summary['total']*100:.0f}%）あります。"
            "これらは RAG 検索で適切なルールがヒットしていない可能性が高いです。"
        )
    if not proposals:
        proposals.append("特筆すべき改善点はありません。順調に蓄積しています。")
    for p in proposals:
        lines.append(f"- {p}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="Month filter (YYYY-MM)")
    parser.add_argument("--export", help="Export Markdown to this path")
    args = parser.parse_args()

    init_db()

    judgments = fetch_all_judgments(month=args.month)
    feedback_map = fetch_all_feedback()
    summary = compute_summary(judgments, feedback_map)

    title = f"TD判断AI メトリクスレポート"
    if args.month:
        title += f" — {args.month}"
    else:
        title += " — 全期間"

    md = render_summary_md(summary, title)

    if args.export:
        Path(args.export).write_text(md, encoding="utf-8")
        print(f"✅ Exported to {args.export}")
    else:
        print(md)

    return 0


if __name__ == "__main__":
    sys.exit(main())

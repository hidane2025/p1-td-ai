#!/usr/bin/env python3
"""
TD判断AI CLI — 成長メカニクス付き v0.2
Phase 0: 学習ループ統合版

## サブコマンド

  init                     DB初期化 + 判例シード + プロンプトv0.1登録
  judge "状況" ...          TD判断を生成（DBに記録）
  feedback <jid> <rating>  判断にフィードバック付与（correct/partial/wrong）
  list-judgments           最近の判断を一覧
  show-judgment <jid>      特定の判断の詳細
  list-cases               判例一覧
  add-case                 判例追加（対話）
  list-prompts             プロンプトバージョン一覧
  activate-prompt <ver>    プロンプトバージョンを切り替え
  interactive              対話モード（judge→即feedback）
  metrics [--month ...]    メトリクスレポート表示

使い方例:
  export ANTHROPIC_API_KEY=sk-ant-...
  python cli.py init
  python cli.py judge "UTGが10000bet、BTNが無言で5kチップ2枚出した"
  python cli.py feedback j_abc123 correct --comment "完璧"
  python cli.py metrics
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from db import (  # noqa: E402
    init_db,
    save_feedback,
    get_judgment,
    list_recent_judgments,
    list_cases,
    add_case as db_add_case,
    list_prompt_versions,
    register_prompt_version,
    activate_prompt_version,
    get_active_prompt_version,
    seed_cases_from_json,
    get_feedback_for_judgment,
)


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize DB, seed cases, register prompt v0.1."""
    init_db()
    print("✅ DB initialized")

    # Seed cases from JSON
    cases_json = BASE_DIR / "data" / "cases" / "judgment_cases.json"
    seeded = seed_cases_from_json(cases_json)
    print(f"✅ Seeded {seeded} cases from judgment_cases.json")

    # Register prompt v0.1 (historical)
    v01_path = BASE_DIR / "prompts" / "versions" / "system_v0.1.md"
    if v01_path.exists():
        register_prompt_version(
            version="v0.1",
            path="prompts/versions/system_v0.1.md",
            parent_version=None,
            change_notes="Initial prompt. 4-element response format. 2024 amendments highlighted.",
            activate=False,
        )
        print("✅ Registered prompt v0.1")

    # Register prompt v0.2 (historical)
    v02_path = BASE_DIR / "prompts" / "versions" / "system_v0.2.md"
    if v02_path.exists():
        register_prompt_version(
            version="v0.2",
            path="prompts/versions/system_v0.2.md",
            parent_version="v0.1",
            change_notes="Added Illustration Addendum awareness + confidence calibration.",
            activate=False,
        )
        print("✅ Registered prompt v0.2")

    # Register prompt v0.3 (historical)
    v03_path = BASE_DIR / "prompts" / "versions" / "system_v0.3.md"
    if v03_path.exists():
        register_prompt_version(
            version="v0.3",
            path="prompts/versions/system_v0.3.md",
            parent_version="v0.2",
            change_notes="公式ルール絶対優先・短文化・結論ファースト・補足情報最小化 (Phase 6)",
            activate=False,
        )
        print("✅ Registered prompt v0.3")

    # Register prompt v0.4 (ACTIVE - Phase 7C 裁量余地明示 + ルール ID 捏造禁止)
    v04_path = BASE_DIR / "prompts" / "versions" / "system_v0.4.md"
    if v04_path.exists():
        register_prompt_version(
            version="v0.4",
            path="prompts/versions/system_v0.4.md",
            parent_version="v0.3",
            change_notes="裁量余地明示・ルール ID 捏造禁止・疑惑温度感調整・補助ルール併記強制 (Phase 7C)",
            activate=True,
        )
        print("✅ Registered prompt v0.4 (ACTIVE)")
    else:
        print("⚠️  system_v0.4.md not found, fallback to v0.3")
        if v03_path.exists():
            from db import activate_prompt_version
            activate_prompt_version("v0.3")

    print("\n🎉 Phase 0 setup complete. Next: export ANTHROPIC_API_KEY and try 'judge'")
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    """Make a judgment and store it."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set")
        print("   export ANTHROPIC_API_KEY=sk-ant-...")
        return 1

    # Lazy import so 'init' doesn't need anthropic installed
    from judge import judge

    situation: str
    if args.file:
        situation = Path(args.file).read_text(encoding="utf-8").strip()
    else:
        situation = args.situation

    extra_context: dict = {}
    if args.phase:
        extra_context["tournament_phase"] = args.phase
    if args.blinds:
        extra_context["blinds"] = args.blinds
    if args.game_type:
        extra_context["game_type"] = args.game_type

    result = judge(
        situation=situation,
        extra_context=extra_context or None,
        prompt_version=args.prompt_version,
        model=args.model or "claude-sonnet-4-5",
    )

    print(result["response"])
    print()
    print("─" * 60)
    print(f"📋 judgment_id: {result['judgment_id']}")
    print(f"🏷️  prompt: {result['prompt_version']} / model: {result['model']}")
    print(f"⏱️  latency: {result['latency_ms']} ms")
    print(f"🎚️  confidence: {result['confidence'] or '?'}")
    print(
        f"🔢 tokens: in={result['token_usage']['input']} out={result['token_usage']['output']}"
    )
    print()
    print("💡 フィードバックを残すには:")
    print(f"   python cli.py feedback {result['judgment_id']} correct")
    print(f"   python cli.py feedback {result['judgment_id']} wrong --correct '...' --comment '...'")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    j = get_judgment(args.judgment_id)
    if not j:
        print(f"❌ Judgment not found: {args.judgment_id}")
        return 1
    fb_id = save_feedback(
        judgment_id=args.judgment_id,
        rating=args.rating,
        correct_judgment=args.correct,
        comment=args.comment,
        reviewer=args.reviewer,
    )
    print(f"✅ Feedback saved: {fb_id}")
    if args.rating == "wrong" and args.correct:
        print()
        print(
            "💡 このケースを判例DBに追加しますか？（次のコマンド）"
        )
        print(
            f"   python cli.py add-case --source real --category '{args.category or '未分類'}' \\"
        )
        print(f"     --situation \"{j['situation'][:80]}...\" \\")
        print(f"     --expected-judgment \"{args.correct[:80]}...\" \\")
        print(f"     --derived-from {args.judgment_id}")
    return 0


def cmd_list_judgments(args: argparse.Namespace) -> int:
    rows = list_recent_judgments(limit=args.limit)
    if not rows:
        print("（判断レコードなし）")
        return 0
    print(f"=== 最近の判断 ({len(rows)}件) ===\n")
    for r in rows:
        sit = r["situation"][:50].replace("\n", " ")
        print(f"  {r['id']}  [{r['prompt_version']}]  confidence={r['confidence'] or '?'}")
        print(f"    {sit}...")
        print(f"    {r['created_at']}")
        print()
    return 0


def cmd_show_judgment(args: argparse.Namespace) -> int:
    j = get_judgment(args.judgment_id)
    if not j:
        print(f"❌ Judgment not found: {args.judgment_id}")
        return 1
    print(f"=== Judgment {j['id']} ===\n")
    print(f"Created: {j['created_at']}")
    print(f"Prompt:  {j['prompt_version']}")
    print(f"Model:   {j['model']}")
    print(f"Latency: {j['latency_ms']} ms")
    print(f"Confidence: {j['confidence']}")
    print()
    print("── Situation ──")
    print(j["situation"])
    if j.get("extra_context"):
        print()
        print("── Extra Context ──")
        print(j["extra_context"])
    print()
    print("── Response ──")
    print(j["response_text"])
    print()
    fbs = get_feedback_for_judgment(j["id"])
    if fbs:
        print(f"── Feedback ({len(fbs)}) ──")
        for fb in fbs:
            print(f"  [{fb['rating']}] {fb['created_at']} by {fb['reviewer'] or 'anonymous'}")
            if fb["correct_judgment"]:
                print(f"    Correct: {fb['correct_judgment']}")
            if fb["comment"]:
                print(f"    Comment: {fb['comment']}")
    else:
        print("── No feedback yet ──")
    return 0


def cmd_list_cases(args: argparse.Namespace) -> int:
    cases = list_cases(category=args.category, source=args.source)
    if not cases:
        print("（判例なし）")
        return 0
    print(f"=== 判例一覧 ({len(cases)}件) ===\n")
    for c in cases:
        print(f"  {c['id']}  [{c['category']}]  source={c['source']}")
        print(f"    {c['situation'][:80]}...")
        if c.get("expected_rules"):
            print(f"    Rules: {c['expected_rules']}")
        print()
    return 0


def cmd_add_case(args: argparse.Namespace) -> int:
    expected_rules: list[str] | None = None
    if args.expected_rules:
        expected_rules = [r.strip() for r in args.expected_rules.split(",")]
    case_id = db_add_case(
        source=args.source,
        category=args.category,
        situation=args.situation,
        tournament_phase=args.phase,
        blinds=args.blinds,
        game_type=args.game_type,
        expected_judgment=args.expected_judgment,
        expected_rules=expected_rules,
        expected_reasoning=args.expected_reasoning,
        notes=args.notes,
        derived_from_judgment_id=args.derived_from,
    )
    print(f"✅ Case added: {case_id}")
    return 0


def cmd_list_prompts(args: argparse.Namespace) -> int:
    versions = list_prompt_versions()
    if not versions:
        print("（プロンプトバージョンなし）")
        return 0
    print("=== プロンプトバージョン ===\n")
    for v in versions:
        marker = "⭐" if v["active"] else "  "
        print(f"  {marker} {v['version']}  (parent: {v['parent_version'] or '-'})")
        print(f"       path: {v['path']}")
        print(f"       created: {v['created_at']}")
        if v.get("change_notes"):
            print(f"       notes: {v['change_notes']}")
        print()
    return 0


def cmd_activate_prompt(args: argparse.Namespace) -> int:
    activate_prompt_version(args.version)
    active = get_active_prompt_version()
    if active and active["version"] == args.version:
        print(f"✅ Activated prompt: {args.version}")
        return 0
    else:
        print(f"❌ Version not found: {args.version}")
        return 1


def cmd_interactive(args: argparse.Namespace) -> int:
    """Interactive mode with immediate feedback capture."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set")
        return 1
    from judge import judge

    print("=== TD判断AI 対話モード ===")
    print("状況を入力してください（空行で送信、'quit'で終了）\n")

    while True:
        lines: list[str] = []
        try:
            while True:
                line = input("> " if not lines else "  ")
                if line.strip().lower() == "quit":
                    return 0
                if not line:
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print("\n終了します")
            return 0

        situation = "\n".join(lines).strip()
        if not situation:
            continue

        print("\n--- 判断中 ---\n")
        result = judge(situation)
        print(result["response"])
        print(f"\n📋 judgment_id: {result['judgment_id']}")
        print(f"🎚️  confidence: {result['confidence']}")
        print()

        # Collect feedback
        try:
            rating_input = input(
                "この判断を評価 [c=correct / p=partial / w=wrong / s=skip]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0

        rating_map = {"c": "correct", "p": "partial", "w": "wrong"}
        if rating_input in rating_map:
            rating = rating_map[rating_input]
            comment = input("コメント（任意・Enterでスキップ）: ").strip() or None
            correct = None
            if rating != "correct":
                correct = input("正しい判断（任意・Enterでスキップ）: ").strip() or None
            fb_id = save_feedback(
                judgment_id=result["judgment_id"],
                rating=rating,
                correct_judgment=correct,
                comment=comment,
                reviewer="interactive",
            )
            print(f"✅ Feedback saved: {fb_id}")

        print("\n" + "=" * 60 + "\n")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    # Delegate to metrics.py main()
    sys.argv = ["metrics.py"]
    if args.month:
        sys.argv += ["--month", args.month]
    if args.export:
        sys.argv += ["--export", args.export]
    from metrics import main as metrics_main
    return metrics_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TD判断AI CLI (Phase 0 with learning loop)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p = sub.add_parser("init", help="Initialize DB, seed cases, register prompts")
    p.set_defaults(func=cmd_init)

    # judge
    p = sub.add_parser("judge", help="Make a TD judgment")
    p.add_argument("situation", nargs="?", help="Natural language situation")
    p.add_argument("--file", help="Read situation from file")
    p.add_argument("--phase", help="Tournament phase (e.g. Day1, Final Table)")
    p.add_argument("--blinds", help="Blinds (e.g. 2000-4000)")
    p.add_argument("--game-type", help="Game type (NLHE/PLO/etc)")
    p.add_argument("--prompt-version", help="Use specific prompt version")
    p.add_argument("--model", help="Override model")
    p.set_defaults(func=cmd_judge)

    # feedback
    p = sub.add_parser("feedback", help="Add feedback to a judgment")
    p.add_argument("judgment_id")
    p.add_argument("rating", choices=["correct", "partial", "wrong"])
    p.add_argument("--correct", help="Correct judgment (for wrong/partial)")
    p.add_argument("--comment", help="Free-form comment")
    p.add_argument("--reviewer", help="Reviewer name/ID")
    p.add_argument("--category", help="Category tag for case DB")
    p.set_defaults(func=cmd_feedback)

    # list-judgments
    p = sub.add_parser("list-judgments", help="List recent judgments")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_list_judgments)

    # show-judgment
    p = sub.add_parser("show-judgment", help="Show judgment detail")
    p.add_argument("judgment_id")
    p.set_defaults(func=cmd_show_judgment)

    # list-cases
    p = sub.add_parser("list-cases", help="List cases in DB")
    p.add_argument("--category")
    p.add_argument("--source")
    p.set_defaults(func=cmd_list_cases)

    # add-case
    p = sub.add_parser("add-case", help="Add a case to DB")
    p.add_argument("--source", required=True, help="mina|real|imported")
    p.add_argument("--category", required=True)
    p.add_argument("--situation", required=True)
    p.add_argument("--phase")
    p.add_argument("--blinds")
    p.add_argument("--game-type")
    p.add_argument("--expected-judgment")
    p.add_argument("--expected-rules", help="Comma-separated rule IDs")
    p.add_argument("--expected-reasoning")
    p.add_argument("--notes")
    p.add_argument("--derived-from", help="Originating judgment_id if any")
    p.set_defaults(func=cmd_add_case)

    # list-prompts
    p = sub.add_parser("list-prompts", help="List prompt versions")
    p.set_defaults(func=cmd_list_prompts)

    # activate-prompt
    p = sub.add_parser("activate-prompt", help="Activate a prompt version")
    p.add_argument("version")
    p.set_defaults(func=cmd_activate_prompt)

    # interactive
    p = sub.add_parser("interactive", help="Interactive judgment + feedback mode")
    p.set_defaults(func=cmd_interactive)

    # metrics
    p = sub.add_parser("metrics", help="Show metrics report")
    p.add_argument("--month", help="YYYY-MM filter")
    p.add_argument("--export", help="Export to Markdown file")
    p.set_defaults(func=cmd_metrics)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

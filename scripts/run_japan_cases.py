#!/usr/bin/env python3
"""
日本 TD 案件 5 件をバッチ実行して結果をマークダウンで出力する。
Phase 7B 評価用。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from judge import judge  # noqa: E402

CASES = [
    {
        "id": "JP-01-masaking",
        "title": "マサキング SHIBUYA POKER FES コール後フォールド事件",
        "expected": "両プレイヤーがハンドを公開した時点で showdown 成立 + 「コルコルコル」発声がコール宣言として有効 → call binding 確定。後付けの fold は認められない。チップを支払う義務あり。Rule 41 (Methods of Calling) + Rule 16 (Face Up for All-Ins)。フロアは事実認定義務を最大限果たすべきだった。",
        "expected_rules": ["Rule-41", "Rule-16"],
        "situation": (
            "状況: SHIBUYA POKER FES の River でプレイヤー① が KT で all-in。"
            "プレイヤー② が「コルコルコル」と発声しながら AT を見せた。"
            "ディーラーが「コールと言わずにショーしたのでコール扱いにならない」と判定。"
            "フロアが呼ばれ、両プレイヤーがハンドを開いたままプレイヤー② のアクション継続を指示。"
            "プレイヤー② はその後 fold を宣言し、チップを払わずハンド終了。"
            "生配信で「コルコルコル」発声の音声証拠が残っている。"
        ),
        "extra": {"tournament_phase": "Live cash / event", "game_type": "NLHE"},
    },
    {
        "id": "JP-02-tpc-collusion",
        "title": "TPC 大阪 ファイナルテーブル 3 人組打ち優勝事件",
        "expected": "Rule 67 (One Player to a Hand) 違反 + Rule 71 ペナルティ階層で DQ レベル。ただし疑惑段階では即 DQ せず、まず別卓分離 + 監視強化、RFID 配信ログを精査して確証を得てから DQ + chip forfeit。確定後は賞金プール返還 or 残プレイヤーへの再分配を TD 裁量で。",
        "expected_rules": ["Rule-67", "Rule-71", "Rule-1"],
        "situation": (
            "状況: TPC（Top of Poker Championship）大阪のファイナルテーブルで、"
            "特定の 3 人のプレイヤーが事前打ち合わせの疑い。お互いを避け、特定 1 人にチップを集中させる動きが繰り返された。"
            "結果として 1 位・2 位・3 位を独占。RFID 配信映像で組打ちが疑われ、SNS で大炎上。"
            "他プレイヤーから複数の苦情申告。TD として疑惑段階でどう対応するか、確定後はどう処分するか。"
        ),
        "extra": {"tournament_phase": "Final Table", "game_type": "NLHE"},
    },
    {
        "id": "JP-03-jopt-privacy",
        "title": "JOPT 公式ツイートで個人情報流出",
        "expected": "本件は TDA Rule の直接射程外（運営オペレーションの注意義務違反）。ただし Rule 1 (best interest of game) の精神に照らせば、運営は参加者保護義務を負う。TD 判断 AI としては「これは TDA Rule で扱う事案ではなく、運営の個人情報保護法対応の範疇」と明示すべき。低確信度（low）が正解。",
        "expected_rules": ["Rule-1"],
        "situation": (
            "状況: JOPT（Japan Open Poker Tour）の公式 X アカウントが Day 2 のシートドローを画像で公開した際、"
            "画像に参加者の住所・電話番号などの個人情報が含まれていた。"
            "数時間後にツイ消し → 後日訂正版を再投稿したが、運営からの説明・謝罪はなし。"
            "個人情報保護法違反の疑いで X 上で炎上。"
            "TD としてこの状況をどう判断するか。"
        ),
        "extra": {"tournament_phase": "Day 2", "game_type": "NLHE"},
    },
    {
        "id": "JP-04-dealer-collected-active",
        "title": "ディーラーがアクティブハンドを誤って回収",
        "expected": "Rule 65A (Players must protect their hands at all times) により、原則としてプレイヤー側の保護義務違反 → ハンド dead。カードプロテクター（チップ等）を置いていなかった場合は救済不可。ただし TD は当時の状況・常連性・ディーラー過失の程度から Rule 1 でベット返却（pot は失う）等の折衷案も検討可能。",
        "expected_rules": ["Rule-65", "Rule-14", "Rule-1"],
        "situation": (
            "状況: NLHE、Day 1 後半、Blinds 2,000-4,000。"
            "プレイヤー A が River でハンドを伏せて考えていた（カードプロテクターなし）。"
            "ディーラーが誤って A のカードを回収し、マック山に混ぜてしまった。"
            "A は「俺のハンドだ、まだ降りてない」と主張。ディーラーは「もう特定できない」と返答。"
            "ポットは 80,000、A のスタックは 120,000、まだリバーアクション前。"
            "フロアに判断を求める。"
        ),
        "extra": {"tournament_phase": "Day 1 後半", "blinds": "2,000-4,000", "game_type": "NLHE"},
    },
    {
        "id": "JP-05-stringbet-2024",
        "title": "2024 ストリングベット新定義の現場混乱",
        "expected": "2024 改訂 Rule 56 で string bet の定義は「1 度ベットしたあと再びスタックに手を伸ばし追加チップをベットする複数の動作」に限定された。「上からチップをバラバラ落とす」「1 本のスタックを前に出して一部を下げる」は string bet ではない（許容）。本件のように上から落とした場合は valid bet として扱う。古い解釈で string bet 判定するのは TD 側のミス。",
        "expected_rules": ["Rule-56", "Rule-42"],
        "situation": (
            "状況: NLHE、Day 2、Blinds 3,000-6,000。"
            "Preflop、UTG オープン 15,000。"
            "CO がチップスタック 1 本（5,000 × 6 枚）を前に押し出したが、上から数枚をバラバラと落とすような動作をした。"
            "宣言なし。総額は 30,000。"
            "ディーラーが「string bet です、コール額（15,000）のみ受け付け」と判定。"
            "プレイヤーは「2024 ルール改訂で上から落とすのは string じゃないはず」と異議。"
            "フロアの判断を求める。"
        ),
        "extra": {"tournament_phase": "Day 2", "blinds": "3,000-6,000 BBA 6,000", "game_type": "NLHE"},
    },
]


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set. exit.")
        sys.exit(1)

    output_path = BASE_DIR / "reports" / "japan_cases_phase7b.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    md = ["# 🃏 日本 TD 案件 5 件 — Phase 7B 出力評価\n\n"]
    md.append(f"実行日時: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    md.append("プロンプト: v0.3 (公式ルール優先 + 短文化)\n\n")
    md.append("---\n\n")

    total_cost = 0.0
    total_latency = 0
    correct_count = 0

    for i, case in enumerate(CASES, 1):
        print(f"\n{'='*70}")
        print(f"🃏 [{i}/{len(CASES)}] {case['title']}")
        print('='*70)
        t0 = time.time()
        try:
            result = judge(
                situation=case["situation"],
                extra_context=case.get("extra"),
                save_to_db=True,
            )
        except Exception as e:
            print(f"❌ Error: {e}")
            md.append(f"## {i}. {case['title']}\n\n❌ ERROR: {e}\n\n---\n\n")
            continue

        latency = result.get("latency_ms", 0)
        total_latency += latency
        tok = result.get("token_usage", {})
        cost_in = tok.get("input", 0) / 1e6 * 3.0
        cost_out = tok.get("output", 0) / 1e6 * 15.0
        cost_cache = tok.get("cache_read", 0) / 1e6 * 0.30
        cost_cw = tok.get("cache_creation", 0) / 1e6 * 3.75
        cost_total = cost_in + cost_out + cost_cache + cost_cw
        cost_jpy = cost_total * 150
        total_cost += cost_jpy

        # Check rule overlap
        actual_rules = set(result.get("referenced_rules_response", []))
        expected_rules = set(case.get("expected_rules", []))
        overlap = actual_rules & expected_rules
        is_correct = len(overlap) >= 1
        if is_correct:
            correct_count += 1

        print(f"⏱️ Latency: {latency/1000:.1f}s")
        print(f"💰 Cost: 約 {cost_jpy:.1f} 円")
        print(f"🎚️ Confidence: {result.get('confidence')}")
        print(f"📖 Expected rules: {sorted(expected_rules)}")
        print(f"📖 Cited rules: {sorted(actual_rules)}")
        print(f"✅ Hit: {sorted(overlap)} ({'CORRECT' if is_correct else 'MISS'})")
        print()
        print(result["response"][:1500])

        md.append(f"## {i}. {case['title']}\n\n")
        md.append(f"**Case ID**: `{case['id']}`\n\n")
        md.append(f"**期待される判断**: {case['expected']}\n\n")
        md.append(f"**期待される引用ルール**: `{', '.join(sorted(expected_rules))}`\n\n")
        md.append(f"### 入力\n\n```\n{case['situation']}\n```\n\n")
        md.append(f"### AI 出力\n\n```\n{result['response']}\n```\n\n")
        md.append(f"### メトリクス\n\n")
        md.append(f"- **応答時間**: {latency/1000:.1f}s\n")
        md.append(f"- **コスト**: 約 {cost_jpy:.2f} 円\n")
        md.append(f"- **確信度**: {result.get('confidence')}\n")
        md.append(f"- **引用ルール（応答）**: `{', '.join(sorted(actual_rules))}`\n")
        md.append(f"- **引用ルール（RAG）**: `{', '.join(result.get('referenced_rules_context', [])[:5])}`\n")
        md.append(f"- **正誤判定**: {'✅ HIT' if is_correct else '❌ MISS'} (overlap={sorted(overlap)})\n")
        md.append(f"- **judgment_id**: `{result.get('judgment_id')}`\n\n")
        md.append("---\n\n")

    md.append("\n## 📊 集計\n\n")
    md.append(f"- 総件数: {len(CASES)}\n")
    md.append(f"- ヒット: {correct_count}/{len(CASES)} ({correct_count/len(CASES)*100:.0f}%)\n")
    md.append(f"- 平均応答時間: {total_latency/len(CASES)/1000:.1f}s\n")
    md.append(f"- 合計コスト: 約 {total_cost:.2f} 円\n")
    md.append(f"- 平均コスト: 約 {total_cost/len(CASES):.2f} 円/件\n")

    output_path.write_text("".join(md), encoding="utf-8")
    print(f"\n\n✅ Report saved: {output_path}")
    print(f"✅ Hit rate: {correct_count}/{len(CASES)}")
    print(f"✅ Avg latency: {total_latency/len(CASES)/1000:.1f}s")
    print(f"✅ Total cost: {total_cost:.2f} 円")


if __name__ == "__main__":
    main()

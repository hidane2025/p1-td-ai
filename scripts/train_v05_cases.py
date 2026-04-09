#!/usr/bin/env python3
"""
Phase 7D: Train v0.5 — 30+ 多様な判例でバッチ訓練

カテゴリ別に判例を設計し、各ケースに期待するルール ID を付ける。
失敗パターンを分析して KEYWORD_MAP / プロンプトを改良する。

使い方:
    ANTHROPIC_API_KEY=sk-ant-... python3 scripts/train_v05_cases.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from judge import judge  # noqa: E402


# =============================================================================
# 30+ 訓練ケース（10 カテゴリ × 3+ 件）
# =============================================================================

TRAIN_CASES = [
    # ============================================================
    # カテゴリ 1: ベッティング（raise/call/bet/undercall）
    # ============================================================
    {
        "id": "T01-verbal-vs-chips-conflict",
        "title": "口頭宣言とチップ額の不一致",
        "category": "ベッティング",
        "situation": "NLHE、Blinds 2,000-4,000。UTG が「15,000 レイズ」と口頭宣言したが、チップを 20,000 分だけ押し出した。どちらが有効か？",
        "expected_rules": ["Rule-40"],
        "expected_keywords": ["whichever is first", "verbal", "口頭が先"],
    },
    {
        "id": "T02-min-raise-violation",
        "title": "ミニマムレイズ違反",
        "category": "ベッティング",
        "situation": "NLHE、Blinds 1,000-2,000。UTG 6,000 オープン、CO が「9,000 レイズ」と宣言（min raise 10,000 未満）。TD としてどう処理する？",
        "expected_rules": ["Rule-43", "Rule-42"],
        "expected_keywords": ["min raise", "ミニマムレイズ", "Rule-43"],
    },
    {
        "id": "T03-allin-reopen-betting",
        "title": "All-in でベッティングラウンドが再開するか",
        "category": "ベッティング",
        "situation": "NLHE、Blinds 3,000-6,000。UTG 18,000 オープン、BTN all-in 25,000（min-raise 未満の 7,000 追加）、SB がアクション中。SB は re-raise できるか？",
        "expected_rules": ["Rule-50", "Rule-43"],
        "expected_keywords": ["reopen", "半分以上", "Rule-50"],
    },
    {
        "id": "T04-check-raise-silent",
        "title": "チェックレイズ無言",
        "category": "ベッティング",
        "situation": "Flop、Player A check、Player B 10,000 bet、Player A がチップを前方に置いて動き（金額不明瞭・宣言なし）、どう処理？",
        "expected_rules": ["Rule-44", "Rule-42"],
        "expected_keywords": ["silent", "forward motion", "Rule-42"],
    },

    # ============================================================
    # カテゴリ 2: ミスディール / 誤配 / カード露出
    # ============================================================
    {
        "id": "T05-first-card-exposed",
        "title": "1 枚目のカード露出",
        "category": "誤配",
        "situation": "Preflop dealing 中、UTG への 1 枚目のカードが表向きに露出した。2 枚目はまだ配られていない。Misdeal か続行か？",
        "expected_rules": ["Rule-35", "Rule-37"],
        "expected_keywords": ["first card", "1 枚目", "continue", "Rule-37"],
    },
    {
        "id": "T06-boxed-card-flop",
        "title": "Flop で boxed card 出現",
        "category": "誤配",
        "situation": "Flop を burn してから 3 枚表にする際、2 枚目のカードが逆向き（boxed card）だった。どう処理する？",
        "expected_rules": ["Rule-37", "Rule-38"],
        "expected_keywords": ["boxed", "逆向き", "Rule-37"],
    },
    {
        "id": "T07-dealer-deals-too-many",
        "title": "ディーラーが多く配りすぎた",
        "category": "誤配",
        "situation": "Hold'em で、ディーラーが誤って 6 人テーブル全員に 3 枚ずつ配ってしまった。アクション前に気づいた。Misdeal か？",
        "expected_rules": ["Rule-35"],
        "expected_keywords": ["misdeal", "too many cards", "Rule-35"],
    },

    # ============================================================
    # カテゴリ 3: ショーダウン / ハンド保護
    # ============================================================
    {
        "id": "T08-mucked-winner",
        "title": "勝ちハンドをディーラーが muck",
        "category": "ショーダウン",
        "situation": "River showdown で Player A が Player B のカードを見ずにハンドを開示、ディーラーが Player B のハンドを勝ちと誤認して A のハンドを muck に混ぜてしまった。後で A の方が強いとわかった。どう処理？",
        "expected_rules": ["Rule-15", "Rule-65"],
        "expected_keywords": ["mucked winner", "誤 muck", "Rule-15"],
    },
    {
        "id": "T09-cards-speak",
        "title": "Cards speak 原則",
        "category": "ショーダウン",
        "situation": "Showdown で Player A が「ツーペア」と口頭で宣言したが、実際のカードはストレートだった。ポットはどう分配？",
        "expected_rules": ["Rule-14", "Rule-1"],
        "expected_keywords": ["cards speak", "Rule-14"],
    },
    {
        "id": "T10-one-card-tabled",
        "title": "1 枚だけ見せた",
        "category": "ショーダウン",
        "situation": "Player が river call 後、ホールカード 1 枚だけ表にして「負け」と言って muck しようとした。対戦相手は見たがっている。どう処理？",
        "expected_rules": ["Rule-13", "Rule-18"],
        "expected_keywords": ["both hole cards", "Rule-13"],
    },

    # ============================================================
    # カテゴリ 4: OOT / アクション順序
    # ============================================================
    {
        "id": "T11-oot-check",
        "title": "OOT check",
        "category": "OOT",
        "situation": "Flop で BB がまだアクションしていないのに、UTG が check を宣言した。どう処理？",
        "expected_rules": ["Rule-53"],
        "expected_keywords": ["OOT", "check", "Rule-53"],
    },
    {
        "id": "T12-oot-raise-binding",
        "title": "OOT raise の binding",
        "category": "OOT",
        "situation": "Preflop、UTG オープンせず、MP が先に「raise 8,000」と宣言。UTG はまだアクションしていなかった。MP の raise は binding か？",
        "expected_rules": ["Rule-53"],
        "expected_keywords": ["binding", "action changes", "Rule-53"],
    },
    {
        "id": "T13-skipped-player-defend",
        "title": "スキップされたプレイヤーの defend right",
        "category": "OOT",
        "situation": "UTG スキップされ、MP→CO→BTN がアクション済み。UTG が気づいた時点で既に SA（Substantial Action）成立後。UTG の option は？",
        "expected_rules": ["Rule-36", "Rule-53"],
        "expected_keywords": ["SA", "Substantial Action", "Rule-36"],
    },

    # ============================================================
    # カテゴリ 5: コリジョン / エチケット / ペナルティ
    # ============================================================
    {
        "id": "T14-whisper-advice",
        "title": "観戦者が耳打ちで助言",
        "category": "エチケット",
        "situation": "Final Table、プレイヤー A のハンド進行中、観戦席にいる A の友人が A に近づき、何かを耳打ちした。ディーラーが気づいた。どう処理？",
        "expected_rules": ["Rule-67", "Rule-69", "Rule-71"],
        "expected_keywords": ["one player", "Rule-67", "助言"],
    },
    {
        "id": "T15-showing-cards-third",
        "title": "ハンド中に第三者にカード見せ",
        "category": "エチケット",
        "situation": "River action 前、Player A が自分のカードを隣の eliminated プレイヤーに見せた。他プレイヤーからクレーム。どう処理？",
        "expected_rules": ["Rule-70", "Rule-71"],
        "expected_keywords": ["exposing", "Rule-70"],
    },
    {
        "id": "T16-verbal-abuse",
        "title": "暴言エスカレーション",
        "category": "エチケット",
        "situation": "プレイヤーが不正解な TD 判定に納得せず、大声で罵声を浴びせ始めた。既に口頭警告 1 回あり。次の処分は？",
        "expected_rules": ["Rule-71", "Rule-70"],
        "expected_keywords": ["penalty", "escalation", "Rule-71"],
    },

    # ============================================================
    # カテゴリ 6: 電子機器 / ID
    # ============================================================
    {
        "id": "T17-airpods",
        "title": "AirPods 装着プレイ",
        "category": "電子機器",
        "situation": "プレイヤーが AirPods を装着したままハンド進行中。音楽を聴いているだけと本人は主張。他プレイヤーは「会話している可能性」とクレーム。",
        "expected_rules": ["Rule-5"],
        "expected_keywords": ["audio", "device", "Rule-5"],
    },
    {
        "id": "T18-apple-watch",
        "title": "Apple Watch 通知",
        "category": "電子機器",
        "situation": "プレイヤーの Apple Watch に通知が入り、ハンド中に画面を確認した。他プレイヤーからクレーム。",
        "expected_rules": ["Rule-5"],
        "expected_keywords": ["smartwatch", "device", "Rule-5"],
    },
    {
        "id": "T19-mask-refuse",
        "title": "マスク外し拒否",
        "category": "ID",
        "situation": "ディーラーが顔確認のためプレイヤーにマスクを外すよう依頼したが拒否。他プレイヤーも「顔が見えない」と不満。",
        "expected_rules": ["Rule-4"],
        "expected_keywords": ["face", "mask", "Rule-4"],
    },

    # ============================================================
    # カテゴリ 7: チップ管理 / ポット計算
    # ============================================================
    {
        "id": "T20-hidden-stack",
        "title": "大きなチップを隠す",
        "category": "チップ管理",
        "situation": "プレイヤーが大きなデノミのチップを他のチップの後ろに隠すように配置。対戦相手が all-in 時にスタック総額を見誤った。クレーム。",
        "expected_rules": ["Rule-25"],
        "expected_keywords": ["visible", "stack", "Rule-25"],
    },
    {
        "id": "T21-short-stack-allin",
        "title": "ショートスタック多重 all-in",
        "category": "ポット計算",
        "situation": "NLHE、4 人 involved、A (40BB)、B (30BB)、C (20BB)、D (5BB) 全員 all-in。サイドポットは何個作る？",
        "expected_rules": ["Rule-55", "Rule-54"],
        "expected_keywords": ["side pot", "main pot", "Rule-55"],
    },
    {
        "id": "T22-chip-race-tie",
        "title": "Chip race 同数",
        "category": "チップ管理",
        "situation": "Chip race で最後の 1 チップを引く権利が 2 人のプレイヤーで同数。どう決める？",
        "expected_rules": ["Rule-24"],
        "expected_keywords": ["chip race", "tie", "Rule-24"],
    },

    # ============================================================
    # カテゴリ 8: トーナメント構造
    # ============================================================
    {
        "id": "T23-late-reg-last-level",
        "title": "Late reg 最終レベル終了間際",
        "category": "構造",
        "situation": "Late reg 最終レベル残り 30 秒、受付待ちのプレイヤーが 10 人並んでいる。どこまで受付する？",
        "expected_rules": ["Rule-8"],
        "expected_keywords": ["late registration", "Rule-8"],
    },
    {
        "id": "T24-absent-player-blinds",
        "title": "不在プレイヤーのブラインド",
        "category": "構造",
        "situation": "プレイヤーが席を外したままで SB/BB/ANTE が支払われ続けている。何ハンドまで許容？",
        "expected_rules": ["Rule-30", "Rule-31"],
        "expected_keywords": ["absent", "blinds", "Rule-30"],
    },
    {
        "id": "T25-missed-blind-return",
        "title": "途中離席からの復帰",
        "category": "構造",
        "situation": "Day 1 中盤、プレイヤーが 2 時間離席してから戻ってきた。BB ポジションをスキップしていた。復帰時の処理は？",
        "expected_rules": ["Rule-30", "Rule-33"],
        "expected_keywords": ["missed blind", "返す", "Rule-30"],
    },

    # ============================================================
    # カテゴリ 9: ハウスルール vs TDA の対立
    # ============================================================
    {
        "id": "T26-house-vs-tda",
        "title": "ハウスルール vs TDA の対立",
        "category": "ハウスルール",
        "situation": "店舗のハウスルールは「OOT fold は常に無効」だが、TDA Rule 53A は「binding」。TDA 準拠を謳う大会でどちらを優先？",
        "expected_rules": ["Rule-1", "Rule-53"],
        "expected_keywords": ["house rule", "Rule-1", "precedence"],
    },
    {
        "id": "T27-straddle-allowed",
        "title": "Straddle の扱い",
        "category": "ハウスルール",
        "situation": "トーナメントで UTG プレイヤーが straddle を宣言。トーナメントでは straddle は通常認められないが、TD はどう対応？",
        "expected_rules": ["Rule-1"],
        "expected_keywords": ["straddle", "Rule-1"],
    },

    # ============================================================
    # カテゴリ 10: 複雑な混合ケース
    # ============================================================
    {
        "id": "T28-dealer-error-all-in",
        "title": "ディーラーミス + All-in 混合",
        "category": "複雑",
        "situation": "Turn で Player A が 50,000 all-in を宣言。ディーラーが誤って 500,000 とアナウンスし、Player B が call を宣言してチップを出した。錯誤発覚後、B は call を取り消せるか？",
        "expected_rules": ["Rule-49", "Rule-1"],
        "expected_reasoning": "Rule 49 Accepted Action の適用、またはディーラー誤認を TD 裁量で是正",
        "expected_keywords": ["accepted action", "Rule-49"],
    },
    {
        "id": "T29-tournament-clock-mistake",
        "title": "クロック誤操作でレベルアップ遅延",
        "category": "複雑",
        "situation": "ディーラーが tournament clock を一時停止し忘れ、実際のブラインドより 5 分遅れて level up した。それまでの 5 分間のアクションは全てやり直すべきか？",
        "expected_rules": ["Rule-1"],
        "expected_keywords": ["Rule-1", "best interest"],
    },
    {
        "id": "T30-binding-but-wrong",
        "title": "Binding だが事実誤認",
        "category": "複雑",
        "situation": "Player A が call を宣言したが、実際は pot が空だと勘違いしていた（相手の all-in 8,000 を見落とし）。宣言は binding か、錯誤による取り消し可能か？",
        "expected_rules": ["Rule-49", "Rule-40"],
        "expected_keywords": ["binding", "Rule-49"],
    },

    # ============================================================
    # カテゴリ 11: 日本特有 / P1 運営想定
    # ============================================================
    {
        "id": "T31-japanese-verbal",
        "title": "日本語特有の曖昧表現",
        "category": "日本特有",
        "situation": "プレイヤーが「うん...」と言いながらカードを前に押し出した。call か fold か曖昧。ディーラーどう判断？",
        "expected_rules": ["Rule-40", "Rule-41"],
        "expected_keywords": ["verbal", "曖昧", "Rule-40"],
    },
    {
        "id": "T32-p1-house-prize-fund",
        "title": "P1 プライズファンドへの影響",
        "category": "P1 運営",
        "situation": "P1 トーナメント final table、1 位賞金 1,000 万円。プレイヤー A が DQ 相当の違反を犯したが、既にチップ 70% 保有。処分と賞金分配は？",
        "expected_rules": ["Rule-71", "Rule-1"],
        "expected_keywords": ["DQ", "chip forfeit", "Rule-71"],
    },
    {
        "id": "T33-p1-rfid-collusion",
        "title": "P1 RFID 配信中の collusion 即検知",
        "category": "P1 運営",
        "situation": "P1 配信中、RFID データから特定の 2 人が soft play している可能性が監視スタッフから報告。現場 TD にエスカレーション。どう対応？",
        "expected_rules": ["Rule-67", "Rule-69", "Rule-71", "Rule-1"],
        "expected_keywords": ["collusion", "RFID", "Rule-67"],
    },
]


def run_batch():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY not set")
        sys.exit(1)

    results = []
    hit_count = 0
    total = len(TRAIN_CASES)
    total_cost_jpy = 0.0
    total_latency_ms = 0

    print(f"\n{'='*72}")
    print(f"🎯 Phase 7D Training Batch — {total} cases")
    print(f"{'='*72}\n")

    for i, case in enumerate(TRAIN_CASES, 1):
        print(f"\n{'='*72}")
        print(f"🃏 [{i}/{total}] {case['id']}: {case['title']}")
        print(f"📂 Category: {case['category']}")
        print(f"{'='*72}")

        t0 = time.time()
        try:
            result = judge(
                situation=case["situation"],
                extra_context=None,
                prompt_version="v0.4",
                save_to_db=False,
            )
        except Exception as e:
            print(f"❌ ERROR: {e}")
            results.append({
                "id": case["id"],
                "error": str(e),
                "hit": False,
            })
            continue

        latency = int((time.time() - t0) * 1000)
        total_latency_ms += latency

        cited = result.get("referenced_rules_response", [])
        expected = case.get("expected_rules", [])
        hit_rules = [r for r in expected if r in cited]
        hit = len(hit_rules) > 0
        if hit:
            hit_count += 1

        confidence = result.get("confidence")
        tok = result.get("token_usage", {})
        cost_in = tok.get("input", 0) / 1e6 * 3.0
        cost_out = tok.get("output", 0) / 1e6 * 15.0
        cost_cache = tok.get("cache_read", 0) / 1e6 * 0.30
        cost_cache_w = tok.get("cache_creation", 0) / 1e6 * 3.75
        cost_jpy = (cost_in + cost_out + cost_cache + cost_cache_w) * 150
        total_cost_jpy += cost_jpy

        # ルール捏造チェック
        validation = result.get("rule_validation", {})
        has_fakes = validation.get("has_fakes", False)
        fakes = validation.get("invalid", [])

        print(f"⏱️  {latency/1000:.1f}s | 💰 {cost_jpy:.1f}円 | 🎚️  {confidence}")
        print(f"📖 Expected: {expected}")
        print(f"📖 Cited:    {cited}")
        print(f"{'✅ HIT' if hit else '❌ MISS'}: {hit_rules}")
        if has_fakes:
            print(f"⚠️  FAKE RULES: {fakes}")
        print(f"\n--- Response (first 400 chars) ---")
        print(result["response"][:400])

        results.append({
            "id": case["id"],
            "title": case["title"],
            "category": case["category"],
            "expected_rules": expected,
            "cited_rules": cited,
            "hit_rules": hit_rules,
            "hit": hit,
            "confidence": confidence,
            "fake_rules": fakes,
            "has_fakes": has_fakes,
            "latency_ms": latency,
            "cost_jpy": round(cost_jpy, 2),
            "response": result["response"],
        })

    # サマリ
    print(f"\n\n{'='*72}")
    print("🎯 TRAINING BATCH RESULTS")
    print(f"{'='*72}")
    print(f"✅ Hit rate: {hit_count}/{total} = {hit_count/total*100:.1f}%")
    print(f"⏱️  Avg latency: {total_latency_ms/total/1000:.1f}s")
    print(f"💰 Total cost: {total_cost_jpy:.1f} 円 ({total_cost_jpy/total:.1f} 円/件)")
    fake_count = sum(1 for r in results if r.get("has_fakes"))
    print(f"⚠️  Fake rule citations: {fake_count}/{total}")

    # カテゴリ別ヒット率
    print(f"\n📊 Category-wise hit rate:")
    cat_stats = {}
    for r in results:
        cat = r.get("category", "?")
        if cat not in cat_stats:
            cat_stats[cat] = {"hit": 0, "total": 0}
        cat_stats[cat]["total"] += 1
        if r.get("hit"):
            cat_stats[cat]["hit"] += 1
    for cat, s in cat_stats.items():
        print(f"  {cat}: {s['hit']}/{s['total']} ({s['hit']/s['total']*100:.0f}%)")

    # 失敗ケースの一覧
    print(f"\n❌ Failed cases:")
    for r in results:
        if not r.get("hit"):
            print(f"  - {r['id']}: Expected {r['expected_rules']}, Got {r['cited_rules']}")

    # ファイル保存
    out_path = BASE_DIR / "reports" / "train_v05_batch.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "batch_size": total,
            "hit_count": hit_count,
            "hit_rate": hit_count / total,
            "total_cost_jpy": round(total_cost_jpy, 2),
            "avg_latency_ms": total_latency_ms / total,
            "fake_rules_count": fake_count,
            "category_stats": cat_stats,
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Saved: {out_path}")


if __name__ == "__main__":
    run_batch()

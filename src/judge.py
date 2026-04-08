"""
TD判断AI — 判断ロジック v0.1

責務:
- TDAルール検索（Phase 0: keyword、Phase 1+: vector）
- プロンプト組み立て
- Claude API 呼び出し
- 応答パース（confidence抽出など）
- db.py への判断保存

分離の理由: cli.py から judgment ロジックを切り離し、
テスト・再利用・将来の UI 差し替えを容易にする。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError as e:
    raise SystemExit(
        "anthropic package not installed. Run: pip3 install anthropic"
    ) from e

from db import save_judgment, get_active_prompt_version

BASE_DIR = Path(__file__).resolve().parent.parent
RULES_PATH = BASE_DIR / "data" / "tda-rules" / "tda_2024_rules_structured.json"
ILLUSTRATIONS_PATH = BASE_DIR / "data" / "tda-rules" / "tda_2024_illustration_examples.json"
PROMPTS_DIR = BASE_DIR / "prompts"

DEFAULT_MODEL = "claude-sonnet-4-5"
FAST_MODEL = "claude-haiku-4-5-20251001"  # Haiku for initial triage
MAX_TOKENS = 1200  # v0.3: 短文化のため削減 (was 2500)


# ===== Rule retrieval (Phase 0: keyword-based) =====

KEYWORD_MAP: dict[str, list[str]] = {
    # English
    "raise": ["Rule-40", "Rule-41", "Rule-42", "Rule-43", "Rule-44", "Rule-45", "Rule-46"],
    "bet": ["Rule-40", "Rule-45", "Rule-46", "Rule-52"],
    "call": ["Rule-41", "Rule-45", "Rule-52"],
    "all-in": ["Rule-45", "Rule-47", "RP-1"],
    "allin": ["Rule-45", "Rule-47"],
    "undercall": ["Rule-52"],
    "underbet": ["Rule-52"],
    "underraise": ["Rule-52", "Rule-43"],
    "out of turn": ["Rule-53"],
    "oot": ["Rule-53"],
    "misdeal": ["Rule-35", "Rule-36", "Rule-37"],
    "exposed": ["Rule-35", "Rule-37", "Rule-38"],
    "showdown": ["Rule-16", "Rule-17", "Rule-18"],
    "phone": ["Rule-5"],
    "smartphone": ["Rule-5"],
    "device": ["Rule-5"],
    "electronic": ["Rule-5"],
    "solver": ["Rule-5"],
    "sunglasses": ["Rule-4"],
    "hood": ["Rule-4"],
    "face": ["Rule-4"],
    "identity": ["Rule-4"],
    "angle": ["Rule-65", "Rule-70", "Rule-71"],
    "etiquette": ["Rule-70", "Rule-71"],
    "penalty": ["Rule-71"],
    "disqualif": ["Rule-71"],
    "collusion": ["Rule-67", "Rule-71"],
    "advise": ["Rule-67"],
    "one player": ["Rule-67"],
    "seat": ["Rule-7", "Rule-8"],
    "late reg": ["Rule-8"],
    "re-entry": ["Rule-8"],
    "clock": ["Rule-30", "Rule-31"],
    "string bet": ["Rule-44"],
    "chip bet": ["Rule-45"],
    "overchip": ["Rule-44"],
    "multi-chip": ["Rule-45"],
    "side pot": ["Rule-33"],
    "dead button": ["Rule-20"],
    "big blind ante": ["RP-11"],
    "bba": ["RP-11"],
    "final table": ["RP-9", "Rule-26"],
    "hand for hand": ["RP-8"],
    "balancing": ["Rule-11"],
    "soft play": ["Rule-71"],
    "dodging blinds": ["Rule-71"],

    # Japanese - betting
    "レイズ": ["Rule-40", "Rule-41", "Rule-42", "Rule-43", "Rule-44", "Rule-45"],
    "ベット": ["Rule-40", "Rule-45", "Rule-52"],
    "コール": ["Rule-41", "Rule-45", "Rule-52"],
    "オールイン": ["Rule-47"],
    "アンダーコール": ["Rule-52"],
    "アンダーベット": ["Rule-52"],
    "アンダーレイズ": ["Rule-52", "Rule-43"],
    "オーバーチップ": ["Rule-44"],
    "ストリングベット": ["Rule-44"],
    "チップ": ["Rule-40", "Rule-44", "Rule-45"],
    "押し出し": ["Rule-40", "Rule-44", "Rule-45"],
    "無言": ["Rule-40", "Rule-44", "Rule-45"],
    "発言なし": ["Rule-40", "Rule-44", "Rule-45"],
    "無発言": ["Rule-40", "Rule-44", "Rule-45"],
    "宣言": ["Rule-40", "Rule-42", "Rule-44"],
    "サイドポット": ["Rule-33"],

    # Japanese - action order
    "順番外": ["Rule-53"],
    "順番": ["Rule-53"],
    "アクション": ["Rule-53"],
    "スキップ": ["Rule-53"],
    "飛ばし": ["Rule-53"],
    "OOT": ["Rule-53"],

    # Japanese - dealing/misdeal (重要：case-003で発見された抜け)
    "誤配": ["Rule-35", "Rule-37"],
    "誤り": ["Rule-35"],
    "ミスディール": ["Rule-35"],
    "配り直し": ["Rule-35"],
    "配り間違い": ["Rule-35"],
    "配牌": ["Rule-35", "Rule-36"],
    "配牌ミス": ["Rule-35"],
    "表向き": ["Rule-35", "Rule-37"],
    "表面": ["Rule-35", "Rule-37"],
    "裏向き": ["Rule-35"],
    "裏面": ["Rule-35"],
    "露出": ["Rule-35", "Rule-37"],
    "ディーラーのミス": ["Rule-35"],
    "ディーラーミス": ["Rule-35"],
    "ディーラーエラー": ["Rule-35"],
    "見えた": ["Rule-35", "Rule-37"],
    "見てしまった": ["Rule-35", "Rule-37"],
    "シャッフル": ["Rule-35"],
    "再シャッフル": ["Rule-35"],
    "再配": ["Rule-35"],

    # Japanese - showdown (case-006で発見された抜け)
    "ショーダウン": ["Rule-16", "Rule-17", "Rule-18"],
    "公開": ["Rule-16", "Rule-17"],
    "オープン": ["Rule-16", "Rule-17"],
    "muck": ["Rule-16", "Rule-17", "Rule-65"],
    "マック": ["Rule-16", "Rule-17", "Rule-65"],
    "下向き": ["Rule-16", "Rule-65"],
    "伏せ": ["Rule-16", "Rule-65"],
    "カードを渡": ["Rule-16", "Rule-17"],
    "カードを投げ": ["Rule-65", "Rule-71"],
    "倒す": ["Rule-16", "Rule-17"],
    "見せる": ["Rule-16", "Rule-17"],
    "捨てる": ["Rule-16", "Rule-65"],
    "ファウル": ["Rule-65"],
    "全員": ["Rule-16"],
    "tabled": ["Rule-16", "Rule-17"],
    "table cards": ["Rule-16", "Rule-17"],
    "live cards": ["Rule-14", "Rule-16"],

    # Japanese - devices (Rule 4/5)
    "スマホ": ["Rule-5"],
    "スマートフォン": ["Rule-5"],
    "電話": ["Rule-5"],
    "携帯": ["Rule-5"],
    "デバイス": ["Rule-5"],
    "端末": ["Rule-5"],
    "ソルバー": ["Rule-5"],
    "GTO": ["Rule-5"],
    "チャート": ["Rule-5"],
    "サングラス": ["Rule-4"],
    "フード": ["Rule-4"],
    "顔": ["Rule-4"],
    "フェイス": ["Rule-4"],
    "マスク": ["Rule-4"],

    # Japanese - player conduct
    "助言": ["Rule-67"],
    "アドバイス": ["Rule-67"],
    "観戦": ["Rule-67"],
    "観戦者": ["Rule-67"],
    "ささや": ["Rule-67"],
    "耳打ち": ["Rule-67"],
    "耳元": ["Rule-67"],
    "第三者": ["Rule-67"],
    "友人": ["Rule-67"],
    "エチケット": ["Rule-70", "Rule-71"],
    "ペナルティ": ["Rule-71"],
    "失格": ["Rule-71"],
    "警告": ["Rule-71"],
    "ソフトプレイ": ["Rule-71"],
    "共謀": ["Rule-67", "Rule-71"],
    "不正": ["Rule-71"],
    "暴言": ["Rule-70", "Rule-71"],

    # Japanese - tournament structure
    "席": ["Rule-7", "Rule-8"],
    "シート": ["Rule-7"],
    "遅刻": ["Rule-8"],
    "再エントリー": ["Rule-8"],
    "リエントリー": ["Rule-8"],
    "レイトレジ": ["Rule-8"],
    "時計": ["Rule-29", "Rule-30"],
    "クロック": ["Rule-29", "Rule-30"],
    "clock": ["Rule-29", "Rule-30"],
    "コール時計": ["Rule-29"],
    "25秒": ["Rule-29"],
    "30秒": ["Rule-29"],
    "時間切れ": ["Rule-29"],
    "時間制限": ["Rule-29"],
    "ショットクロック": ["Rule-29", "Rule-30"],
    "席を立": ["Rule-30", "Rule-31"],
    "離席": ["Rule-30", "Rule-31"],
    "不在": ["Rule-30", "Rule-31"],
    "トイレ": ["Rule-30", "Rule-31"],
    "at seat": ["Rule-30"],
    "at your seat": ["Rule-30"],
    "remain at": ["Rule-31"],
    # Dead button / button progression
    "ボタン": ["Rule-32", "Rule-20"],
    "dead button": ["Rule-32"],
    "デッドボタン": ["Rule-32"],
    "button": ["Rule-32"],
    "bust out": ["Rule-32"],
    "bust": ["Rule-32"],
    "敗退": ["Rule-32"],
    "脱落": ["Rule-32"],
    "次ハンド": ["Rule-32"],
    "ボタン進行": ["Rule-32"],
    "ブラインド進行": ["Rule-32", "Rule-20"],
    "blinds": ["Rule-32"],
    "SB": ["Rule-32"],
    "BB": ["Rule-32"],

    # Dodging blinds (Rule 33)
    "dodging": ["Rule-33", "Rule-71"],
    "dodge": ["Rule-33", "Rule-71"],
    "BB回避": ["Rule-33", "Rule-71"],
    "ブラインド回避": ["Rule-33", "Rule-71"],
    "BB直前": ["Rule-33"],
    "意図的に席": ["Rule-33"],
    "連続で回避": ["Rule-33"],
    "連続": ["Rule-33"],  # Weaker signal
    "体調不良": ["Rule-33", "Rule-1"],

    # Showdown proper tabling (Rule 13, 14, 15)
    "両方のカード": ["Rule-13"],
    "両方のホール": ["Rule-13"],
    "1枚だけ": ["Rule-13", "Rule-15"],
    "1枚のみ": ["Rule-13", "Rule-15"],
    "不完全公開": ["Rule-13", "Rule-15"],
    "カードを倒": ["Rule-13", "Rule-16"],
    "テーブル": ["Rule-13"],  # Weak
    "winning hand": ["Rule-13", "Rule-15"],
    "tabling": ["Rule-13"],

    # Asking to see a hand (Rule 18)
    "見せろ": ["Rule-18"],
    "見せ要求": ["Rule-18"],
    "見せるべき": ["Rule-18"],
    "last aggressor": ["Rule-18"],
    "最後のアグレッサー": ["Rule-18"],
    "hand they paid": ["Rule-18"],
    "inalienable": ["Rule-18"],

    # Chip race (Rule 24)
    "chip race": ["Rule-24"],
    "チップレース": ["Rule-24"],
    "color up": ["Rule-24"],
    "color-up": ["Rule-24"],
    "カラーアップ": ["Rule-24"],
    "最後のチップ": ["Rule-24"],
    "raced out": ["Rule-24"],
    "denomination": ["Rule-24"],
    "デノミ": ["Rule-24"],
    "廃止": ["Rule-24"],

    # Conditional declarations (Rule 59)
    "if-then": ["Rule-59"],
    "if then": ["Rule-59"],
    "条件付き": ["Rule-59"],
    "もしお前が": ["Rule-59"],
    "もし〜なら": ["Rule-59"],
    "レイズしてきたら": ["Rule-59"],
    "conditional": ["Rule-59"],

    # Improper hand exposure / tabling nuances
    "ホールカード": ["Rule-13", "Rule-65"],
    "hole card": ["Rule-13", "Rule-65"],

    # Chip management / out of view (Rule 63)
    "ポケット": ["Rule-63"],
    "pocket": ["Rule-63"],
    "持ち出し": ["Rule-63"],
    "持ち出": ["Rule-63"],
    "out of view": ["Rule-63"],
    "視界外": ["Rule-63"],
    "隠す": ["Rule-63"],
    "ズボン": ["Rule-63"],
    "チップ没収": ["Rule-63"],
    "forfeit": ["Rule-63"],

    # Chips found behind (Rule 62)
    "chip found": ["Rule-62"],
    "hidden chip": ["Rule-62"],
    "後ろに隠れ": ["Rule-62"],
    "隠れていた": ["Rule-62"],
    "隠れた": ["Rule-62"],
    "後から発見": ["Rule-62"],
    "後発見": ["Rule-62"],
    "accepted action": ["Rule-49", "Rule-62"],

    # Button placement errors (Rule 34)
    "button placement": ["Rule-34"],
    "ボタン位置": ["Rule-34"],
    "ボタン配置": ["Rule-34"],
    "ボタンを進め": ["Rule-34"],
    "ボタンを戻": ["Rule-34"],
    "ボタン誤": ["Rule-34"],
    "2席進め": ["Rule-34"],
    "誤配置": ["Rule-34"],

    # Chip count (Rule 60)
    "count": ["Rule-60", "Rule-25"],
    "カウント": ["Rule-60", "Rule-25"],
    "正確な数": ["Rule-60"],
    "数えて": ["Rule-60"],
    "正確に数": ["Rule-60"],
    "チップを数": ["Rule-60"],
    "スタック数": ["Rule-60", "Rule-25"],
    "乱雑": ["Rule-60"],

    # Deck change (Rule 26)
    "deck change": ["Rule-26"],
    "デッキ変更": ["Rule-26"],
    "新しいデッキ": ["Rule-26"],
    "デッキを変え": ["Rule-26"],
    "運が悪い": ["Rule-26"],
    "デッキ交換": ["Rule-26"],

    # Over-betting for change (Rule 61)
    "お釣り": ["Rule-61"],
    "change": ["Rule-61"],
    "つり銭": ["Rule-61"],
    "余剰": ["Rule-61", "Rule-45"],

    # Rebuy (Rule 27)
    "rebuy": ["Rule-27"],
    "リバイ": ["Rule-27"],
    "リバイ宣言": ["Rule-27"],
    "re-buy": ["Rule-27"],
    "chips behind": ["Rule-27"],

    # Playing the board (Rule 19)
    "play the board": ["Rule-19"],
    "ボードで勝負": ["Rule-19"],
    "ボードで play": ["Rule-19"],
    "ボード play": ["Rule-19"],
    "ボード遊び": ["Rule-19"],

    # Helicopter fold (Rule 68)
    "helicopter": ["Rule-68"],
    "ヘリコプター": ["Rule-68"],
    "投げ": ["Rule-68"],
    "放り投げ": ["Rule-68"],
    "放り": ["Rule-68"],
    "高く放": ["Rule-68"],

    # Table balancing (Rule 11)
    "balance": ["Rule-11"],
    "バランス": ["Rule-11"],
    "table balance": ["Rule-11"],
    "卓バランス": ["Rule-11"],
    "テーブル移動": ["Rule-11"],
    "transfer": ["Rule-11"],
    "worst position": ["Rule-11"],
    "ファイナル": ["RP-9", "Rule-26"],
    "ファイナルテーブル": ["RP-9", "Rule-26"],
    "ハンドフォーハンド": ["RP-8"],
    "バブル": ["RP-8"],
    "ブラインドアンティ": ["RP-11"],
    "BBA": ["RP-11"],
    "アンティ": ["RP-11"],
    "バランス": ["Rule-11"],
    "テーブルバランス": ["Rule-11"],

    # Rule-65A: Unprotected hand / Raiser mucks own hand (最重要: Negreanuケース)
    # レイザーが自分で muck → raise 返却、ベースポットのみ他プレイヤーに
    "unprotected hand": ["Rule-65"],
    "unprotected": ["Rule-65"],
    "protect": ["Rule-65"],
    "protection": ["Rule-65"],
    "uncalled": ["Rule-65"],
    "uncalled bet": ["Rule-65"],
    "uncalled raise": ["Rule-65"],
    "no redress": ["Rule-65"],
    "redress": ["Rule-65"],
    "自分から muck": ["Rule-65"],
    "自分で muck": ["Rule-65"],
    "自分からマック": ["Rule-65"],
    "自分でマック": ["Rule-65"],
    "raiser muck": ["Rule-65"],
    "raiser mucks": ["Rule-65"],
    "レイザー muck": ["Rule-65"],
    "レイザーがマック": ["Rule-65"],
    "raise 後 muck": ["Rule-65"],
    "レイズ後 muck": ["Rule-65"],
    "レイズ後マック": ["Rule-65"],
    "誤って muck": ["Rule-65"],
    "誤ってマック": ["Rule-65"],
    "間違って muck": ["Rule-65"],
    "間違ってマック": ["Rule-65"],
    "勘違いで muck": ["Rule-65"],
    "勘違いでマック": ["Rule-65"],
    "勘違い": ["Rule-65"],
    "思い込み": ["Rule-65"],
    "勝ったと思": ["Rule-65"],
    "勝ったと勘違い": ["Rule-65"],
    "fold してしまった": ["Rule-65"],
    "フォールドしてしまった": ["Rule-65"],
    "誤fold": ["Rule-65"],
    "誤フォールド": ["Rule-65"],
    "誤ってフォールド": ["Rule-65"],
    "返却": ["Rule-65"],
    "返金": ["Rule-65"],
    "raise 返却": ["Rule-65"],
    "レイズ返却": ["Rule-65"],
    "レイズ分返却": ["Rule-65"],
    "レイズ分返金": ["Rule-65"],
    "kill hand": ["Rule-65"],
    "killed by dealer": ["Rule-65"],
    "ディーラーがkill": ["Rule-65"],
    "ディーラーが kill": ["Rule-65"],
    "前提ハンド": ["Rule-65"],
    "誤認": ["Rule-65"],
    "誤解": ["Rule-65"],
    "showdown なしで muck": ["Rule-65"],
    "ショーダウン前 muck": ["Rule-65"],
    "ショーダウン前にマック": ["Rule-65"],
    "all-in call 後": ["Rule-65"],
    "call 後 muck": ["Rule-65"],
    "コール後 muck": ["Rule-65"],
    "コール後マック": ["Rule-65"],
}


def load_rules() -> list[dict]:
    if not RULES_PATH.exists():
        raise FileNotFoundError(f"Rules file not found: {RULES_PATH}")
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_illustrations() -> list[dict]:
    """TDA Illustration Addendum の example エントリを読み込む"""
    if not ILLUSTRATIONS_PATH.exists():
        return []
    with open(ILLUSTRATIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def find_illustrations_for_rules(rule_ids: list[str]) -> list[dict]:
    """指定された rule_id 群に対応する Illustration Addendum のエントリを返す"""
    illustrations = load_illustrations()
    rule_id_set = set(rule_ids)
    return [e for e in illustrations if e["rule_id"] in rule_id_set]


def _keyword_search(situation: str) -> list[dict]:
    """Phase 0/1: keyword-based rule retrieval with keyword-hit-count ranking.

    Phase 2 改良: ルールごとにヒットしたキーワード数をカウントし、
    より specific なルール（多くのキーワードが該当するルール）を上位にランク付ける。
    """
    rules = load_rules()
    sit_lower = situation.lower()

    # Count keyword hits per rule
    hit_counts: dict[str, int] = {}
    for keyword, rule_ids in KEYWORD_MAP.items():
        if keyword.lower() in sit_lower:
            for rid in rule_ids:
                hit_counts[rid] = hit_counts.get(rid, 0) + 1

    # Sort rules by hit count (descending), preserving rule order as tiebreaker
    scored = [
        (r, hit_counts.get(r["id"], 0))
        for r in rules
        if r["id"] in hit_counts
    ]
    scored.sort(key=lambda x: -x[1])  # Higher count = more relevant
    return [r for r, _ in scored]


def search_rules(situation: str, top_k: int = 10) -> list[dict]:
    """
    Phase 2: hybrid retrieval (keyword + TF-IDF).

    Strategy:
      1. Keyword map をプライマリとして実行
      2. TF-IDF で補完（keyword ゼロヒットや漏れに対応）
      3. Rule-1 / Rule-71 を必ず含める
      4. fallback: 不足分を先頭ルールで埋める
    """
    keyword_hits = _keyword_search(situation)

    # Use hybrid retriever if sklearn available
    try:
        from retriever import hybrid_search
        result = hybrid_search(situation, keyword_hits, top_k=top_k)
        if len(result) >= top_k:
            return result
        # Fallback padding
        rules = load_rules()
        seen_ids = {r["id"] for r in result}
        for r in rules:
            if r["id"] not in seen_ids:
                result.append(r)
                seen_ids.add(r["id"])
            if len(result) >= top_k:
                break
        return result[:top_k]
    except Exception:
        # Fallback to pure keyword + padding (Phase 0/1 behavior)
        rules = load_rules()
        hit_ids = {r["id"] for r in keyword_hits}
        hit_ids.update(["Rule-1", "Rule-71"])
        hit_rules = [r for r in rules if r["id"] in hit_ids]
        if len(hit_rules) < top_k:
            for r in rules:
                if r not in hit_rules:
                    hit_rules.append(r)
                if len(hit_rules) >= top_k:
                    break
        return hit_rules[:top_k]


# ===== Prompt loading =====

def load_system_prompt(version: str | None = None) -> tuple[str, str]:
    """
    Load a specific prompt version or the active one from DB.
    Returns (version_id, prompt_text).
    """
    if version is None:
        active = get_active_prompt_version()
        if active is None:
            # Fallback to system.md and label it v0.1
            path = PROMPTS_DIR / "system.md"
            if not path.exists():
                raise FileNotFoundError(f"No prompt found at {path}")
            return "v0.1", path.read_text(encoding="utf-8")
        version = active["version"]
        path = BASE_DIR / active["path"]
    else:
        path = PROMPTS_DIR / "versions" / f"system_{version}.md"

    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")

    return version, path.read_text(encoding="utf-8")


# ===== Response parsing =====

def extract_confidence(response_text: str) -> str | None:
    """Extract confidence level from response text. Matches various formats."""
    # Try structured tags first: 【確信度】 high, 確信度: high, confidence: high
    patterns = [
        r"【?確信度】?[:：\s]*\*?\*?(high|medium|low)",
        r"confidence[:：\s]*\*?\*?(high|medium|low)",
    ]
    for p in patterns:
        match = re.search(p, response_text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return None


def extract_referenced_rules(response_text: str) -> list[str]:
    """Extract Rule-XX / RP-XX references from response text. Handles multiple formats."""
    # Match "Rule-45", "Rule 45", "RP-11", "RP 11"
    pattern = r"(Rule|RP)[-\s]?(\d+)"
    matches = re.findall(pattern, response_text)
    rule_ids = set()
    for prefix, num in matches:
        rule_ids.add(f"{prefix}-{num}")
    return sorted(rule_ids, key=lambda x: (x.split("-")[0], int(x.split("-")[1])))


# ===== Main judgment function =====

def judge(
    situation: str,
    extra_context: dict | None = None,
    prompt_version: str | None = None,
    model: str = DEFAULT_MODEL,
    save_to_db: bool = True,
    use_cache: bool = True,
) -> dict:
    """
    Run a TD judgment on the given situation.

    Phase 3 追加:
      - prompt caching: system prompt + rules context をキャッシュ化（5 分 TTL）
      - use_cache=False で無効化可能

    Returns: {
        'judgment_id': str | None,
        'response': str,
        'prompt_version': str,
        'model': str,
        'referenced_rules_context': [list of rule dicts fed as RAG],
        'referenced_rules_response': [list of rule IDs mentioned in response],
        'confidence': str | None,
        'latency_ms': int,
        'token_usage': dict,
        'cache_hit': bool,
    }
    """
    t0 = time.time()

    version_id, system_prompt = load_system_prompt(prompt_version)
    relevant_rules = search_rules(situation)
    rules_context = "\n\n".join(
        f"### {r['id']}: {r['title']}\n{r['body']}" for r in relevant_rules
    )

    # Attach illustration examples for retrieved rules (Phase 1 Task G)
    illustrations = find_illustrations_for_rules([r["id"] for r in relevant_rules])
    illustration_context = ""
    if illustrations:
        illustration_context = "\n\n## 参照例示（Illustration Addendum 2024）\n\n" + "\n\n".join(
            f"### {e['rule_id']}{e['subpart']}: {e['title_snippet']}\n{e['body'][:1500]}"
            for e in illustrations
        )

    user_message = f"""以下の状況について、TD判断AIとして判断してください。

## 状況
{situation}
"""
    if extra_context:
        user_message += (
            "\n## 追加情報\n```json\n"
            + json.dumps(extra_context, ensure_ascii=False, indent=2)
            + "\n```\n"
        )

    user_message += f"""
上記の参照ルールと例示（Illustration Addendum）を元に、システムプロンプトで指定されたフォーマットで判断を返してください。
該当ルールが参照候補にない場合は、Rule 1（Floor Decisions）の一般原則で判断してください。
"""

    # Build system prompt with cacheable rules context
    # Phase 3: Use prompt caching with cache_control
    if use_cache:
        # Split into 2 blocks: system prompt (always cached) + rules context (cached per retrieval set)
        system_blocks = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": f"## 参照ルール候補（TDA 2024年版）\n\n{rules_context}{illustration_context}",
                "cache_control": {"type": "ephemeral"},
            },
        ]
    else:
        system_blocks = [
            {"type": "text", "text": system_prompt},
            {
                "type": "text",
                "text": f"## 参照ルール候補（TDA 2024年版）\n\n{rules_context}{illustration_context}",
            },
        ]

    client = Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
    )

    response_text = response.content[0].text
    latency_ms = int((time.time() - t0) * 1000)

    # Capture cache metrics if available
    cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
    cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0

    token_usage = {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
        "cache_read": cache_read,
        "cache_creation": cache_creation,
    }
    cache_hit = cache_read > 0

    confidence = extract_confidence(response_text)
    referenced_rules_response = extract_referenced_rules(response_text)

    judgment_id = None
    if save_to_db:
        judgment_id = save_judgment(
            situation=situation,
            extra_context=extra_context,
            prompt_version=version_id,
            model=model,
            referenced_rules=[r["id"] for r in relevant_rules],
            response_text=response_text,
            confidence=confidence,
            latency_ms=latency_ms,
            token_usage=token_usage,
        )

    return {
        "judgment_id": judgment_id,
        "response": response_text,
        "prompt_version": version_id,
        "model": model,
        "referenced_rules_context": [r["id"] for r in relevant_rules],
        "referenced_rules_response": referenced_rules_response,
        "confidence": confidence,
        "latency_ms": latency_ms,
        "token_usage": token_usage,
        "cache_hit": cache_hit,
    }


def judge_with_routing(
    situation: str,
    extra_context: dict | None = None,
    prompt_version: str | None = None,
) -> dict:
    """
    Phase 3: Haiku + Sonnet routing.

    Strategy:
      1. First attempt with Haiku (fast, cheap)
      2. If confidence != 'high' OR required rules not cited, escalate to Sonnet
      3. Return final result with routing metadata

    Cost savings:
      - If Haiku succeeds (~60% of cases): save 80% vs Sonnet
      - If escalation needed: 1 extra Haiku call cost (~$0.002)
      - Net: ~50% cost reduction across large case loads
    """
    t0 = time.time()

    # Attempt 1: Haiku
    haiku_result = judge(
        situation=situation,
        extra_context=extra_context,
        prompt_version=prompt_version,
        model=FAST_MODEL,
        save_to_db=True,
    )

    haiku_confidence = haiku_result.get("confidence")
    haiku_rules = haiku_result.get("referenced_rules_response") or []
    escalate = (
        haiku_confidence != "high"
        or len(haiku_rules) < 2
    )

    if not escalate:
        haiku_result["routing"] = "haiku_only"
        haiku_result["total_latency_ms"] = int((time.time() - t0) * 1000)
        return haiku_result

    # Attempt 2: Sonnet escalation
    sonnet_result = judge(
        situation=situation,
        extra_context=extra_context,
        prompt_version=prompt_version,
        model=DEFAULT_MODEL,
        save_to_db=True,
    )
    sonnet_result["routing"] = "escalated_to_sonnet"
    sonnet_result["haiku_judgment_id"] = haiku_result.get("judgment_id")
    sonnet_result["total_latency_ms"] = int((time.time() - t0) * 1000)
    return sonnet_result

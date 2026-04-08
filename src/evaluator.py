"""
TD判断AI — 評価エンジン v0.2

Phase 1 で導入する「必須/推奨」分離式の evaluator。

### 設計
- required_rules: 判断の核心となるルール。1 つでも欠けたら wrong
- recommended_rules: 定義・補助・関連ルール。あれば品質 UP、なくても correct
- 3 tier 判定:
    correct  = required 全ヒット（recommended は別途記録）
    partial  = required 部分ヒット（半分以上）
    wrong    = required ゼロヒット or 半分未満

### 後方互換
expected_rules（旧フィールド）しかないケースは、全てを required とみなす。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class EvalResult:
    rating: str                      # "correct" | "partial" | "wrong"
    required_hits: int
    required_total: int
    required_missing: list[str]
    recommended_hits: int
    recommended_total: int
    recommended_missing: list[str]
    quality_score: float             # 0.0 - 1.0（required + recommended を加重平均）

    def to_dict(self) -> dict:
        return {
            "rating": self.rating,
            "required_hits": self.required_hits,
            "required_total": self.required_total,
            "required_missing": self.required_missing,
            "recommended_hits": self.recommended_hits,
            "recommended_total": self.recommended_total,
            "recommended_missing": self.recommended_missing,
            "quality_score": round(self.quality_score, 3),
        }

    def summary(self) -> str:
        icon = {"correct": "✅", "partial": "🟡", "wrong": "❌"}[self.rating]
        req = f"{self.required_hits}/{self.required_total}"
        rec = f"{self.recommended_hits}/{self.recommended_total}"
        return (
            f"{icon} {self.rating.upper()}  "
            f"required={req}  recommended={rec}  "
            f"quality={self.quality_score:.2f}"
        )


def _rule_matches(rule_id: str, text: str) -> bool:
    """Rule-45 を 'Rule-45', 'Rule 45', 'Rule45' の全形式で照合。

    さらに Rule-5 は Rule-5C/Rule-5D のような subpart 付きにもマッチさせる。
    """
    prefix = "RP" if rule_id.startswith("RP-") else "Rule"
    num = rule_id.replace("Rule-", "").replace("RP-", "")
    patterns = [
        f"{prefix}-{num}",
        f"{prefix} {num}",
        f"{prefix}{num}",
    ]
    if any(p in text for p in patterns):
        return True
    # 末尾に subpart (A/B/C 等) が付いた表記も OK
    subpart_pattern = rf"{prefix}[- ]?{num}[A-Za-z\-]"
    if re.search(subpart_pattern, text):
        return True
    return False


def evaluate(
    response_text: str,
    required_rules: list[str],
    recommended_rules: list[str] | None = None,
) -> EvalResult:
    """
    response_text に対して required_rules/recommended_rules がどれだけ引用されているか評価する。

    rating は required_rules に基づく 3 tier:
      - required 全ヒット           → correct
      - required 半分以上ヒット     → partial
      - required 半分未満ヒット     → wrong

    quality_score は required 70% + recommended 30% の加重平均（recommended なしなら required のみ）。
    """
    recommended_rules = recommended_rules or []

    required_hits = sum(1 for r in required_rules if _rule_matches(r, response_text))
    required_missing = [r for r in required_rules if not _rule_matches(r, response_text)]

    recommended_hits = sum(1 for r in recommended_rules if _rule_matches(r, response_text))
    recommended_missing = [r for r in recommended_rules if not _rule_matches(r, response_text)]

    # Rating based on required_rules only
    if not required_rules:
        rating = "correct"
    else:
        req_ratio = required_hits / len(required_rules)
        if req_ratio >= 1.0:
            rating = "correct"
        elif req_ratio >= 0.5:
            rating = "partial"
        else:
            rating = "wrong"

    # Quality score: required weighted 70%, recommended 30%
    req_score = (required_hits / len(required_rules)) if required_rules else 1.0
    if recommended_rules:
        rec_score = recommended_hits / len(recommended_rules)
        quality = 0.7 * req_score + 0.3 * rec_score
    else:
        quality = req_score

    return EvalResult(
        rating=rating,
        required_hits=required_hits,
        required_total=len(required_rules),
        required_missing=required_missing,
        recommended_hits=recommended_hits,
        recommended_total=len(recommended_rules),
        recommended_missing=recommended_missing,
        quality_score=quality,
    )


def evaluate_legacy(
    response_text: str,
    expected_rules: list[str],
) -> EvalResult:
    """後方互換: 旧 expected_rules しかない場合は全て required として扱う。"""
    return evaluate(response_text, required_rules=expected_rules, recommended_rules=[])

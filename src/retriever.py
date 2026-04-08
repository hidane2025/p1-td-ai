"""
TD判断AI — RAG リトリーバー v0.2 (Phase 2)

Phase 0/1 では keyword map による retrieval を使っていたが、これは以下の問題があった：
- 日本語自然言語の語彙ゆれに弱い（「配る」「配布」「配布する」が別物扱い）
- キーワードが漏れるとルールが候補に入らない
- メンテナンスコスト増（新ルール追加のたびにキーワード登録）

Phase 2 ではこれを TF-IDF + keyword のハイブリッドで改善する：
- **TF-IDF**: 文字 n-gram で日本語自然言語をカバー（3-gram + 2-gram のアナライザ）
- **Keyword boost**: 既存のキーワードマップは「強い優先度」として保持
- **Fallback**: 両方に完全にヒットしない場合も Rule 1/71 を必ず含める

### 設計
1. Index 構築時にルール本文を TF-IDF ベクトル化（モジュール起動時一度だけ）
2. クエリ時: (1) keyword hit を最優先（既存）、(2) TF-IDF top-K を補完、(3) Rule 1/71 を必ず含める
3. Phase 3 で vector embedding（Voyage/OpenAI）に置き換え可能な抽象化
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

BASE_DIR = Path(__file__).resolve().parent.parent
RULES_PATH = BASE_DIR / "data" / "tda-rules" / "tda_2024_rules_structured.json"


@lru_cache(maxsize=1)
def _load_rules_cached() -> list[dict]:
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_jp_keywords_for_rules() -> dict[str, list[str]]:
    """judge.py の KEYWORD_MAP から逆マッピングを作り、
    各ルールにどの日本語/英語キーワードが関連付けられているかを返す。
    """
    # Delay import to avoid circular dependency
    import sys
    from pathlib import Path
    src_dir = Path(__file__).resolve().parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from judge import KEYWORD_MAP  # noqa: E402

    rule_to_keywords: dict[str, list[str]] = {}
    for keyword, rule_ids in KEYWORD_MAP.items():
        for rid in rule_ids:
            rule_to_keywords.setdefault(rid, []).append(keyword)
    return rule_to_keywords


@lru_cache(maxsize=1)
def _build_tfidf_index():
    """TF-IDF インデックスを一度だけ構築してキャッシュ"""
    if not HAS_SKLEARN:
        return None, None

    rules = _load_rules_cached()
    jp_keywords = _build_jp_keywords_for_rules()

    corpus = []
    for r in rules:
        # Title + body + 日本語キーワード（逆マッピング）を連結
        # title を重視するため 3 回繰り返す
        jp_words = " ".join(jp_keywords.get(r["id"], []))
        # 日本語キーワードも重要なので 2 回繰り返す
        doc = f"{r['title']} {r['title']} {r['title']} {jp_words} {jp_words} {r['body']}"
        corpus.append(doc)

    # 日本語+英語対応: character n-gram (2-4)
    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        max_features=30000,
        lowercase=True,
    )
    matrix = vectorizer.fit_transform(corpus)
    return vectorizer, matrix


def tfidf_search(query: str, top_k: int = 10) -> list[tuple[dict, float]]:
    """
    TF-IDF ベースで query に類似するルールを返す。
    Returns: [(rule_dict, score), ...] score 降順
    """
    if not HAS_SKLEARN:
        return []

    vectorizer, matrix = _build_tfidf_index()
    if vectorizer is None:
        return []

    rules = _load_rules_cached()
    query_vec = vectorizer.transform([query])
    similarities = cosine_similarity(query_vec, matrix).flatten()

    # Top-k indices
    top_indices = similarities.argsort()[::-1][:top_k]
    return [(rules[i], float(similarities[i])) for i in top_indices if similarities[i] > 0.0]


def hybrid_search(
    query: str,
    keyword_hits: list[dict],
    top_k: int = 10,
    min_combined_score: float = 0.03,
    alpha: float = 0.4,  # Weight for keyword hit ratio
    beta: float = 0.6,   # Weight for TF-IDF score
) -> list[dict]:
    """
    Keyword + TF-IDF の重み付きハイブリッド検索。

    Phase 2 改良: キーワードとTF-IDFのスコアを正規化して重み付き合算する。
    これにより TF-IDF がキーワード検索の偏りを補正する。

    Score formula:
      combined_score = α * (keyword_hit_count / max_keyword_count) + β * tfidf_score

    Args:
      query: 状況の自然言語
      keyword_hits: keyword map で既にヒットしたルール（順序は keyword_hit_count 降順）
      top_k: 最終的に返すルール数
      min_combined_score: 合算スコアの下限
      alpha: keyword の重み（0〜1）
      beta: TF-IDF の重み（0〜1）

    Returns:
      最終的な retrieval 結果（rule dict のリスト、combined_score 降順）
    """
    rules = _load_rules_cached()

    # 1. Build keyword score map (normalized 0-1)
    # keyword_hits is already ordered by hit count (judge._keyword_search)
    kw_scores: dict[str, float] = {}
    if keyword_hits:
        # Use rank-based score: position 0 = 1.0, position N-1 = 0.0
        for i, r in enumerate(keyword_hits):
            # Linear decay
            kw_scores[r["id"]] = max(0.0, 1.0 - i / max(len(keyword_hits), 1))

    # 2. Build TF-IDF score map
    tfidf_results = tfidf_search(query, top_k=30)
    tfidf_scores: dict[str, float] = {r["id"]: score for r, score in tfidf_results}
    # Normalize tfidf scores (max to 1.0)
    if tfidf_scores:
        max_tfidf = max(tfidf_scores.values())
        if max_tfidf > 0:
            tfidf_scores = {k: v / max_tfidf for k, v in tfidf_scores.items()}

    # 3. Combined score for all rules that have at least one signal
    all_candidate_ids = set(kw_scores.keys()) | set(tfidf_scores.keys())
    combined: list[tuple[dict, float]] = []
    rule_by_id = {r["id"]: r for r in rules}
    for rid in all_candidate_ids:
        r = rule_by_id.get(rid)
        if not r:
            continue
        score = alpha * kw_scores.get(rid, 0.0) + beta * tfidf_scores.get(rid, 0.0)
        if score >= min_combined_score:
            combined.append((r, score))

    combined.sort(key=lambda x: -x[1])

    # 4. Take top_k
    result = [r for r, _ in combined[:top_k]]
    seen_ids = {r["id"] for r in result}

    # 5. 必須: Rule-1, Rule-71
    for required_id in ["Rule-1", "Rule-71"]:
        if required_id not in seen_ids and len(result) < top_k:
            r = rule_by_id.get(required_id)
            if r:
                result.append(r)
                seen_ids.add(required_id)
        elif required_id not in seen_ids:
            # Replace lowest-scored rule with required one
            r = rule_by_id.get(required_id)
            if r:
                result[-1] = r
                seen_ids.add(required_id)

    return result[:top_k]


def diagnostic_report(query: str, keyword_hits: list[dict]) -> dict:
    """デバッグ用: keyword/tfidf それぞれの結果を並べて返す"""
    rules = _load_rules_cached()
    tfidf = tfidf_search(query, top_k=10)
    hybrid = hybrid_search(query, keyword_hits, top_k=10)
    return {
        "keyword_hits": [r["id"] for r in keyword_hits],
        "tfidf_top_10": [(r["id"], round(s, 3)) for r, s in tfidf],
        "hybrid_final": [r["id"] for r in hybrid],
    }

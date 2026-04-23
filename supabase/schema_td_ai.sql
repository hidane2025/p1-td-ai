-- TD判断AI — Supabase Vector スキーマ v0.1
--
-- Phase 3 で稼働予定。pgvector 拡張を使い、TDA ルールと判例を vector 化する。
-- 現在のローカル SQLite スキーマ (src/db.py) と互換性を保つ設計。
--
-- 実行前準備:
--   1. Supabase ダッシュボード → Database → Extensions → "vector" を enable
--   2. プロジェクト ID は環境変数 SUPABASE_URL で指定
--
-- 実行方法:
--   Supabase SQL Editor で本ファイルをペーストして実行、または
--   psql "postgres://postgres:[pw]@db.[project].supabase.co:5432/postgres" -f schema_td_ai.sql

-- ===== pgvector 拡張（一度だけ） =====
CREATE EXTENSION IF NOT EXISTS vector;

-- ===== tda_rules: TDA 2024 年版ルール本体 =====
-- 93 エントリ: Rule-1〜Rule-71 + RP-1〜RP-22
CREATE TABLE IF NOT EXISTS td_ai_rules (
    id TEXT PRIMARY KEY,                     -- "Rule-45" | "RP-11"
    rule_number INT NOT NULL,                -- 45 | 11
    kind TEXT NOT NULL,                      -- "rule" | "rp"
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    jp_keywords TEXT[] DEFAULT '{}',         -- 日本語キーワード（keyword map 由来）
    embedding vector(1024),                  -- Voyage voyage-3 or equivalent (1024-dim)
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_td_ai_rules_embedding
    ON td_ai_rules USING hnsw (embedding vector_cosine_ops);

-- ===== tda_illustrations: Illustration Addendum の例示 =====
CREATE TABLE IF NOT EXISTS td_ai_illustrations (
    id SERIAL PRIMARY KEY,
    rule_id TEXT NOT NULL REFERENCES td_ai_rules(id),
    subpart TEXT,                            -- "-A" | "-B" | ""
    title_snippet TEXT,
    body TEXT NOT NULL,
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_td_ai_illustrations_embedding
    ON td_ai_illustrations USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_td_ai_illustrations_rule_id
    ON td_ai_illustrations(rule_id);

-- ===== td_ai_cases: 判例DB =====
-- SQLite の cases テーブルと同じ shape + embedding
CREATE TABLE IF NOT EXISTS td_ai_cases (
    id TEXT PRIMARY KEY,                     -- "case-001-multi-chip-bet"
    created_at TIMESTAMPTZ DEFAULT NOW(),
    source TEXT,                             -- "mina" | "real" | "imported"
    category TEXT,
    situation TEXT NOT NULL,
    tournament_phase TEXT,
    blinds TEXT,
    game_type TEXT,
    expected_judgment TEXT,
    expected_rules TEXT[],
    required_rules TEXT[],                   -- Phase 1 で追加
    recommended_rules TEXT[],
    expected_reasoning TEXT,
    notes TEXT,
    derived_from_judgment_id TEXT,
    embedding vector(1024)                   -- situation の埋め込み（類似ケース検索用）
);

CREATE INDEX IF NOT EXISTS idx_td_ai_cases_embedding
    ON td_ai_cases USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_td_ai_cases_category ON td_ai_cases(category);

-- ===== td_ai_judgments: AI判断ログ =====
CREATE TABLE IF NOT EXISTS td_ai_judgments (
    id TEXT PRIMARY KEY,                     -- "j_<uuid12>"
    created_at TIMESTAMPTZ DEFAULT NOW(),
    situation TEXT NOT NULL,
    extra_context JSONB,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    referenced_rules TEXT[],                 -- RAG で渡したルール ID
    response_text TEXT NOT NULL,
    response_json JSONB,
    confidence TEXT,                         -- "high" | "medium" | "low"
    latency_ms INT,
    token_usage JSONB,
    embedding vector(1024)                   -- situation の埋め込み（類似判断検索用）
);

CREATE INDEX IF NOT EXISTS idx_td_ai_judgments_created
    ON td_ai_judgments(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_td_ai_judgments_version
    ON td_ai_judgments(prompt_version);

CREATE INDEX IF NOT EXISTS idx_td_ai_judgments_embedding
    ON td_ai_judgments USING hnsw (embedding vector_cosine_ops);

-- ===== td_ai_feedback: フィードバック =====
CREATE TABLE IF NOT EXISTS td_ai_feedback (
    id TEXT PRIMARY KEY,                     -- "fb_<uuid12>"
    judgment_id TEXT NOT NULL REFERENCES td_ai_judgments(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    rating TEXT NOT NULL CHECK (rating IN ('correct', 'partial', 'wrong')),
    correct_judgment TEXT,
    comment TEXT,
    reviewer TEXT
);

CREATE INDEX IF NOT EXISTS idx_td_ai_feedback_judgment
    ON td_ai_feedback(judgment_id);

CREATE INDEX IF NOT EXISTS idx_td_ai_feedback_rating
    ON td_ai_feedback(rating);

-- ===== td_ai_prompt_versions: プロンプト履歴 =====
CREATE TABLE IF NOT EXISTS td_ai_prompt_versions (
    version TEXT PRIMARY KEY,                -- "v0.1", "v0.2", ...
    created_at TIMESTAMPTZ DEFAULT NOW(),
    path TEXT NOT NULL,
    parent_version TEXT REFERENCES td_ai_prompt_versions(version),
    change_notes TEXT,
    active BOOLEAN NOT NULL DEFAULT false
);

-- ===== Vector search 関数 =====

-- 状況から類似ルールを検索
CREATE OR REPLACE FUNCTION td_ai_search_rules(
    query_embedding vector(1024),
    match_count INT DEFAULT 10
)
RETURNS TABLE (
    id TEXT,
    title TEXT,
    body TEXT,
    jp_keywords TEXT[],
    similarity REAL
)
LANGUAGE sql STABLE
AS $$
    SELECT
        r.id,
        r.title,
        r.body,
        r.jp_keywords,
        (1 - (r.embedding <=> query_embedding))::REAL AS similarity
    FROM td_ai_rules r
    WHERE r.embedding IS NOT NULL
    ORDER BY r.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- 状況から類似判例を検索（few-shot 用）
CREATE OR REPLACE FUNCTION td_ai_search_cases(
    query_embedding vector(1024),
    match_count INT DEFAULT 3
)
RETURNS TABLE (
    id TEXT,
    situation TEXT,
    expected_judgment TEXT,
    required_rules TEXT[],
    similarity REAL
)
LANGUAGE sql STABLE
AS $$
    SELECT
        c.id,
        c.situation,
        c.expected_judgment,
        c.required_rules,
        (1 - (c.embedding <=> query_embedding))::REAL AS similarity
    FROM td_ai_cases c
    WHERE c.embedding IS NOT NULL
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- 類似過去判断を検索（学習ループ用）
CREATE OR REPLACE FUNCTION td_ai_search_judgments(
    query_embedding vector(1024),
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id TEXT,
    situation TEXT,
    response_text TEXT,
    latest_rating TEXT,
    similarity REAL
)
LANGUAGE sql STABLE
AS $$
    SELECT
        j.id,
        j.situation,
        j.response_text,
        (
            SELECT rating FROM td_ai_feedback f
            WHERE f.judgment_id = j.id
            ORDER BY created_at DESC LIMIT 1
        )::TEXT AS latest_rating,
        (1 - (j.embedding <=> query_embedding))::REAL AS similarity
    FROM td_ai_judgments j
    WHERE j.embedding IS NOT NULL
    ORDER BY j.embedding <=> query_embedding
    LIMIT match_count;
$$;

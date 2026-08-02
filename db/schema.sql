-- Garden Companion schema
-- One Postgres instance, two logical concerns: the knowledge base
-- (documents/sections/chunks/embeddings) and monitoring (conversations/feedback).
-- See docs/decisions.md for why everything lives in one database.

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- Knowledge base
-- ============================================================

-- One row per source (a Gutenberg book or a Clemson HGIC fact sheet).
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,        -- e.g. 'gutenberg-9550', 'hgic-tomato-diseases'
    source_type   TEXT NOT NULL CHECK (source_type IN ('book', 'factsheet')),
    source_ref    TEXT NOT NULL,           -- gutenberg ID or HGIC page URL
    title         TEXT NOT NULL,
    author        TEXT,
    license_note  TEXT,
    raw_text      TEXT,                     -- cleaned full text, landed here before section/chunk splitting
    fetched_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- The pre-chunk unit ground truth questions are generated from: a chapter/
-- section of a book, or a fact sheet (which may be its own single section).
-- This is the granularity search evaluation checks against, since a "document"
-- here can be a whole book -- see docs/decisions.md.
CREATE TABLE IF NOT EXISTS sections (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_title   TEXT,
    section_order   INTEGER NOT NULL,
    raw_text        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sections_document ON sections(document_id);

-- Chunks are generated per strategy, so the same section produces multiple
-- rows (one set per strategy). The `strategy` column is what lets eval/
-- evaluate_search.py run the same ground truth against all three and compare.
CREATE TABLE IF NOT EXISTS chunks (
    id              BIGSERIAL PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id      TEXT REFERENCES sections(id) ON DELETE SET NULL,
    strategy        TEXT NOT NULL CHECK (strategy IN ('fixed', 'structure', 'recursive')),
    chunk_index     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    token_count     INTEGER,
    embedding       vector(1536),           -- OpenAI text-embedding-3-small
    search_vector   tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_strategy ON chunks(strategy);
CREATE INDEX IF NOT EXISTS idx_chunks_search_vector ON chunks USING GIN(search_vector);

-- HNSW index for vector search. Created per-strategy-scale is fine at our
-- volume (low thousands of rows); revisit if the corpus grows a lot.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

-- LLM-generated questions, one section can produce several. This is the
-- ground truth search evaluation (Aug 3) runs against -- a "hit" means a
-- retrieved chunk's section_id matches this row's section_id, not an exact
-- document-ID match (see docs/decisions.md for why: a "document" here can
-- be a whole book, so section is the real granularity).
CREATE TABLE IF NOT EXISTS ground_truth (
    id                 BIGSERIAL PRIMARY KEY,
    section_id         TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    document_id        TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    question           TEXT NOT NULL,
    -- Embedded once (eval/embed_questions.py) and cached here so vector/
    -- hybrid search evaluation doesn't re-embed all ~7,500 questions on
    -- every eval re-run. Same text-embedding-3-small / vector(1536) as the
    -- chunks table, so query and chunk vectors live in the same space.
    question_embedding vector(1536),
    generated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Idempotent add for databases created before question_embedding existed:
-- CREATE TABLE IF NOT EXISTS above is a no-op on an existing table, so it
-- would never add this column on its own. This ALTER lets `init_db` evolve
-- an existing ground_truth table without a destructive wipe (unlike the
-- raw_text-column change earlier in the project, which did need a reset).
ALTER TABLE ground_truth ADD COLUMN IF NOT EXISTS question_embedding vector(1536);

CREATE INDEX IF NOT EXISTS idx_ground_truth_section ON ground_truth(section_id);

-- ============================================================
-- Monitoring (module 5 pattern, same shape as the course)
-- ============================================================

CREATE TABLE IF NOT EXISTS conversations (
    id                  SERIAL PRIMARY KEY,
    question            TEXT NOT NULL,
    answer              TEXT NOT NULL,
    model               TEXT NOT NULL,
    instructions        TEXT NOT NULL,
    prompt              TEXT NOT NULL,
    search_strategy     TEXT,               -- which chunking strategy served this answer
    search_method       TEXT,               -- 'keyword' | 'vector' | 'hybrid'
    prompt_tokens       INTEGER NOT NULL,
    completion_tokens   INTEGER NOT NULL,
    total_tokens        INTEGER NOT NULL,
    response_time       FLOAT NOT NULL,
    cost                FLOAT NOT NULL,
    timestamp           TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id                SERIAL PRIMARY KEY,
    conversation_id   INTEGER REFERENCES conversations(id),
    source            TEXT NOT NULL CHECK (source IN ('user', 'judge')),
    relevance         TEXT,
    explanation       TEXT,
    score             INTEGER,
    timestamp         TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_conversation ON feedback(conversation_id);

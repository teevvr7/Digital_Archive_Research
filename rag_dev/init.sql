-- init.sql: Database schema for InvoiceInsight RAG Sandbox

-- Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Drop table if exists to allow fresh initialization during experiments
DROP TABLE IF EXISTS invoice_chunks CASCADE;
DROP TABLE IF EXISTS feedback CASCADE;

-- Core chunk table storing serialised markdown and raw JSON alongside embeddings
CREATE TABLE invoice_chunks (
    id SERIAL PRIMARY KEY,
    invoice_id TEXT NOT NULL UNIQUE,
    content_text TEXT NOT NULL,        -- Serialised human-readable Markdown
    content_json JSONB NOT NULL,       -- Full raw extracted JSON structure
    embedding vector(384) NOT NULL     -- 384-dimensional SentenceTransformer embeddings
);

-- HNSW index for sub-millisecond similarity queries
CREATE INDEX ON invoice_chunks USING hnsw (embedding vector_cosine_ops);

-- TSVector column for PostgreSQL Full-Text Search (for hybrid FTS + vector search)
ALTER TABLE invoice_chunks ADD COLUMN search_tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', content_text)) STORED;

-- GIN index for fast FTS matches
CREATE INDEX ON invoice_chunks USING gin (search_tsv);

-- Persistent logging and user feedback table for the monitoring dashboard
CREATE TABLE feedback (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    retrieved_ids TEXT[],               -- Array of invoice_ids retrieved as context
    relevance_score REAL,               -- Similarity score of the top result
    response_time_ms INT,               -- Total response latency in milliseconds
    user_rating INT,                    -- User feedback: +1 (thumbs up), -1 (thumbs down)
    created_at TIMESTAMP DEFAULT NOW()
);

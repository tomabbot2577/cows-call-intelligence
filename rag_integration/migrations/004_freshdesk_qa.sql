-- Freshdesk Q&A Integration
-- Store resolved ticket Q&A pairs for RAG search

CREATE TABLE IF NOT EXISTS kb_freshdesk_qa (
    id SERIAL PRIMARY KEY,
    qa_id VARCHAR(50) UNIQUE NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category VARCHAR(100),
    tags TEXT[],
    ticket_id INTEGER NOT NULL,
    requester_email VARCHAR(255),
    agent_name VARCHAR(100),
    priority INTEGER,
    created_at TIMESTAMP,
    resolved_at TIMESTAMP,
    synced_at TIMESTAMP DEFAULT NOW(),

    -- For RAG search
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', COALESCE(question, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(answer, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(category, '')), 'C')
    ) STORED
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_fd_qa_category ON kb_freshdesk_qa(category);
CREATE INDEX IF NOT EXISTS idx_fd_qa_synced ON kb_freshdesk_qa(synced_at);
CREATE INDEX IF NOT EXISTS idx_fd_qa_ticket ON kb_freshdesk_qa(ticket_id);
CREATE INDEX IF NOT EXISTS idx_fd_qa_search ON kb_freshdesk_qa USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_fd_qa_tags ON kb_freshdesk_qa USING GIN(tags);

-- Sync tracking table
CREATE TABLE IF NOT EXISTS kb_freshdesk_sync_log (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    tickets_processed INTEGER DEFAULT 0,
    qa_pairs_created INTEGER DEFAULT 0,
    qa_pairs_updated INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    error_details JSONB,
    status VARCHAR(20) DEFAULT 'running'
);

-- Comment
COMMENT ON TABLE kb_freshdesk_qa IS 'Q&A pairs extracted from resolved Freshdesk tickets for RAG search';

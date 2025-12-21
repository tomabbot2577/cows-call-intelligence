-- Simple Knowledge Base Tables
-- Lightweight KB that uses existing RAG for search, just logs queries and feedback

-- Drop complex tables if they exist (we're simplifying)
DROP TABLE IF EXISTS knowledge_base_analytics CASCADE;
DROP TABLE IF EXISTS knowledge_base_history CASCADE;
DROP TABLE IF EXISTS knowledge_base_feedback CASCADE;
DROP TABLE IF EXISTS knowledge_base_contributions CASCADE;
DROP TABLE IF EXISTS knowledge_base_gaps CASCADE;
DROP TABLE IF EXISTS knowledge_base_queries CASCADE;
DROP TABLE IF EXISTS knowledge_base_articles CASCADE;
DROP TABLE IF EXISTS knowledge_base_categories CASCADE;

-- Simple search log table
CREATE TABLE IF NOT EXISTS kb_searches (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    agent_id VARCHAR(100),
    results_json JSONB,
    result_count INT DEFAULT 0,
    rag_summary TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Simple feedback table
CREATE TABLE IF NOT EXISTS kb_feedback (
    id SERIAL PRIMARY KEY,
    search_id INT REFERENCES kb_searches(id) ON DELETE CASCADE,
    helpful BOOLEAN NOT NULL,
    result_index INT,  -- Which result was helpful/not helpful (0-based)
    comment TEXT,
    agent_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_kb_searches_created ON kb_searches(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kb_searches_agent ON kb_searches(agent_id);
CREATE INDEX IF NOT EXISTS idx_kb_searches_query ON kb_searches USING gin(to_tsvector('english', query));
CREATE INDEX IF NOT EXISTS idx_kb_feedback_search ON kb_feedback(search_id);
CREATE INDEX IF NOT EXISTS idx_kb_feedback_helpful ON kb_feedback(helpful);

-- View for quick stats
CREATE OR REPLACE VIEW kb_stats AS
SELECT
    COUNT(*) as total_searches,
    COUNT(DISTINCT agent_id) as unique_agents,
    AVG(result_count) as avg_results,
    COUNT(*) FILTER (WHERE result_count = 0) as no_result_searches,
    (SELECT COUNT(*) FROM kb_feedback WHERE helpful = TRUE) as helpful_count,
    (SELECT COUNT(*) FROM kb_feedback WHERE helpful = FALSE) as not_helpful_count,
    (SELECT COUNT(*) FROM kb_feedback) as total_feedback
FROM kb_searches
WHERE created_at >= NOW() - INTERVAL '30 days';

COMMENT ON TABLE kb_searches IS 'Logs all KB searches for analytics and improvement';
COMMENT ON TABLE kb_feedback IS 'User feedback on search results for quality tracking';

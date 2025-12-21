-- Knowledge Base Schema
-- Comprehensive system for tracking Q&A, searches, feedback, and knowledge gaps

-- ============================================
-- 1. MAIN KNOWLEDGE BASE ARTICLES
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_base_articles (
    id SERIAL PRIMARY KEY,

    -- Content
    title TEXT NOT NULL,
    problem TEXT NOT NULL,                    -- The question/problem
    solution TEXT NOT NULL,                   -- The answer/solution

    -- Categorization
    category TEXT,                            -- e.g., 'PCR', 'Billing', 'Technical', 'Integration'
    subcategory TEXT,
    tags TEXT[],                              -- searchable tags
    keywords TEXT[],                          -- extracted keywords for search

    -- Source information
    source_type TEXT NOT NULL DEFAULT 'call', -- 'call', 'ticket', 'manual', 'imported'
    source_id TEXT,                           -- recording_id, ticket_id, etc.

    -- People involved
    resolved_by TEXT,                         -- Employee who solved it
    asked_by TEXT,                            -- Customer who asked
    customer_company TEXT,

    -- Dates
    resolved_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Quality & Verification
    status TEXT DEFAULT 'active',             -- 'active', 'draft', 'archived', 'needs_review'
    verified BOOLEAN DEFAULT FALSE,
    verified_by TEXT,
    verified_at TIMESTAMP,
    confidence_score REAL,                    -- AI confidence in the answer

    -- Usage metrics
    view_count INTEGER DEFAULT 0,
    helpful_count INTEGER DEFAULT 0,
    not_helpful_count INTEGER DEFAULT 0,
    times_cited INTEGER DEFAULT 0,            -- How often this was the answer to a query

    -- Related content
    related_articles INTEGER[],               -- IDs of related articles

    -- Full-text search
    search_vector TSVECTOR,

    -- Vector embedding for semantic search
    embedding VECTOR(1536)
);

-- Indexes for knowledge_base_articles
CREATE INDEX IF NOT EXISTS idx_kb_articles_category ON knowledge_base_articles(category);
CREATE INDEX IF NOT EXISTS idx_kb_articles_source ON knowledge_base_articles(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_kb_articles_status ON knowledge_base_articles(status);
CREATE INDEX IF NOT EXISTS idx_kb_articles_tags ON knowledge_base_articles USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_kb_articles_keywords ON knowledge_base_articles USING GIN(keywords);
CREATE INDEX IF NOT EXISTS idx_kb_articles_search ON knowledge_base_articles USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_kb_articles_resolved_by ON knowledge_base_articles(resolved_by);
CREATE INDEX IF NOT EXISTS idx_kb_articles_resolved_date ON knowledge_base_articles(resolved_date);

-- Trigger to update search vector
CREATE OR REPLACE FUNCTION update_kb_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.problem, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.solution, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.tags, ' '), '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.category, '')), 'C');
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS kb_articles_search_trigger ON knowledge_base_articles;
CREATE TRIGGER kb_articles_search_trigger
    BEFORE INSERT OR UPDATE ON knowledge_base_articles
    FOR EACH ROW EXECUTE FUNCTION update_kb_search_vector();


-- ============================================
-- 2. QUERY TRACKING - All searches made
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_base_queries (
    id SERIAL PRIMARY KEY,

    -- Query details
    query_text TEXT NOT NULL,
    query_type TEXT DEFAULT 'search',         -- 'search', 'question', 'browse'

    -- User info
    user_identifier TEXT,                     -- Username or session ID
    user_department TEXT,

    -- Search parameters
    filters_used JSONB,                       -- Any filters applied
    date_range TEXT,

    -- Results
    results_count INTEGER DEFAULT 0,
    article_ids_returned INTEGER[],           -- Which articles were shown
    top_result_id INTEGER,                    -- Best match article ID

    -- Outcome tracking
    was_answered BOOLEAN,                     -- Did they find an answer?
    clicked_article_id INTEGER,               -- Which article did they click?
    time_to_click_ms INTEGER,                 -- How long before they clicked

    -- Feedback
    feedback_given BOOLEAN DEFAULT FALSE,
    feedback_helpful BOOLEAN,
    feedback_text TEXT,

    -- Session info
    session_id TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_queries_created ON knowledge_base_queries(created_at);
CREATE INDEX IF NOT EXISTS idx_kb_queries_answered ON knowledge_base_queries(was_answered);
CREATE INDEX IF NOT EXISTS idx_kb_queries_user ON knowledge_base_queries(user_identifier);
CREATE INDEX IF NOT EXISTS idx_kb_queries_text ON knowledge_base_queries USING GIN(to_tsvector('english', query_text));


-- ============================================
-- 3. KNOWLEDGE GAPS - Unanswered questions
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_base_gaps (
    id SERIAL PRIMARY KEY,

    -- The unanswered question
    question TEXT NOT NULL,
    normalized_question TEXT,                 -- Cleaned/normalized version for deduplication

    -- Context
    category_guess TEXT,                      -- AI-guessed category
    tags_guess TEXT[],

    -- Tracking
    times_asked INTEGER DEFAULT 1,            -- How many times this was asked
    first_asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    asked_by TEXT[],                          -- Users who asked

    -- Resolution
    status TEXT DEFAULT 'open',               -- 'open', 'in_progress', 'resolved', 'wont_fix'
    priority TEXT DEFAULT 'normal',           -- 'low', 'normal', 'high', 'critical'
    assigned_to TEXT,
    resolved_article_id INTEGER,              -- Link to article when resolved
    resolution_notes TEXT,
    resolved_at TIMESTAMP,
    resolved_by TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_gaps_status ON knowledge_base_gaps(status);
CREATE INDEX IF NOT EXISTS idx_kb_gaps_priority ON knowledge_base_gaps(priority);
CREATE INDEX IF NOT EXISTS idx_kb_gaps_times_asked ON knowledge_base_gaps(times_asked DESC);
CREATE INDEX IF NOT EXISTS idx_kb_gaps_question ON knowledge_base_gaps USING GIN(to_tsvector('english', question));


-- ============================================
-- 4. USER CONTRIBUTIONS - Improvements/additions
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_base_contributions (
    id SERIAL PRIMARY KEY,

    -- Contribution type
    contribution_type TEXT NOT NULL,          -- 'new_article', 'edit', 'correction', 'addition', 'comment'

    -- Content
    article_id INTEGER,                       -- NULL for new articles
    original_content TEXT,                    -- What it was before (for edits)
    new_content TEXT,                         -- The contribution
    field_modified TEXT,                      -- Which field was changed

    -- For new articles
    suggested_title TEXT,
    suggested_problem TEXT,
    suggested_solution TEXT,
    suggested_category TEXT,
    suggested_tags TEXT[],

    -- Contributor info
    contributed_by TEXT NOT NULL,
    contributor_department TEXT,
    contribution_reason TEXT,                 -- Why they're suggesting this

    -- Review status
    status TEXT DEFAULT 'pending',            -- 'pending', 'approved', 'rejected', 'merged'
    reviewed_by TEXT,
    reviewed_at TIMESTAMP,
    review_notes TEXT,

    -- If approved, what was created/modified
    resulting_article_id INTEGER,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_contributions_status ON knowledge_base_contributions(status);
CREATE INDEX IF NOT EXISTS idx_kb_contributions_type ON knowledge_base_contributions(contribution_type);
CREATE INDEX IF NOT EXISTS idx_kb_contributions_article ON knowledge_base_contributions(article_id);
CREATE INDEX IF NOT EXISTS idx_kb_contributions_contributor ON knowledge_base_contributions(contributed_by);


-- ============================================
-- 5. ARTICLE FEEDBACK - Detailed feedback per article
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_base_feedback (
    id SERIAL PRIMARY KEY,

    article_id INTEGER NOT NULL REFERENCES knowledge_base_articles(id),
    query_id INTEGER REFERENCES knowledge_base_queries(id),

    -- Feedback
    helpful BOOLEAN,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    feedback_text TEXT,

    -- What was missing or wrong?
    issue_type TEXT,                          -- 'incomplete', 'outdated', 'incorrect', 'confusing', 'other'

    -- User info
    user_identifier TEXT,
    user_department TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_feedback_article ON knowledge_base_feedback(article_id);
CREATE INDEX IF NOT EXISTS idx_kb_feedback_helpful ON knowledge_base_feedback(helpful);


-- ============================================
-- 6. ARTICLE HISTORY - Track all changes
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_base_history (
    id SERIAL PRIMARY KEY,

    article_id INTEGER NOT NULL REFERENCES knowledge_base_articles(id),

    -- Change details
    action TEXT NOT NULL,                     -- 'created', 'updated', 'verified', 'archived', 'restored'
    field_changed TEXT,
    old_value TEXT,
    new_value TEXT,

    -- Who made the change
    changed_by TEXT,
    change_reason TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_history_article ON knowledge_base_history(article_id);
CREATE INDEX IF NOT EXISTS idx_kb_history_action ON knowledge_base_history(action);


-- ============================================
-- 7. ANALYTICS SUMMARY - Daily/weekly stats
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_base_analytics (
    id SERIAL PRIMARY KEY,

    date DATE NOT NULL,
    period_type TEXT NOT NULL,                -- 'daily', 'weekly', 'monthly'

    -- Query metrics
    total_queries INTEGER DEFAULT 0,
    unique_users INTEGER DEFAULT 0,
    queries_answered INTEGER DEFAULT 0,
    queries_unanswered INTEGER DEFAULT 0,
    answer_rate REAL,                         -- percentage

    -- Article metrics
    total_articles INTEGER DEFAULT 0,
    articles_created INTEGER DEFAULT 0,
    articles_updated INTEGER DEFAULT 0,
    articles_viewed INTEGER DEFAULT 0,

    -- Feedback metrics
    feedback_positive INTEGER DEFAULT 0,
    feedback_negative INTEGER DEFAULT 0,
    avg_rating REAL,

    -- Gap metrics
    new_gaps_identified INTEGER DEFAULT 0,
    gaps_resolved INTEGER DEFAULT 0,

    -- Top items
    top_queries JSONB,                        -- Most common queries
    top_articles JSONB,                       -- Most viewed articles
    top_gaps JSONB,                           -- Most asked unanswered questions

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(date, period_type)
);

CREATE INDEX IF NOT EXISTS idx_kb_analytics_date ON knowledge_base_analytics(date);
CREATE INDEX IF NOT EXISTS idx_kb_analytics_period ON knowledge_base_analytics(period_type);


-- ============================================
-- 8. CATEGORIES - Organize knowledge
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_base_categories (
    id SERIAL PRIMARY KEY,

    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT,
    parent_id INTEGER REFERENCES knowledge_base_categories(id),

    icon TEXT,                                -- Bootstrap icon class
    color TEXT,                               -- Hex color for UI

    article_count INTEGER DEFAULT 0,

    sort_order INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default categories
INSERT INTO knowledge_base_categories (name, display_name, description, icon, color) VALUES
    ('pcr', 'PC Recruiter', 'PC Recruiter software issues and features', 'bi-laptop', '#0d6efd'),
    ('technical', 'Technical Support', 'Technical issues, errors, and troubleshooting', 'bi-gear', '#6c757d'),
    ('billing', 'Billing & Accounts', 'Billing, payments, and account management', 'bi-credit-card', '#198754'),
    ('integration', 'Integrations', 'Third-party integrations and API issues', 'bi-plug', '#6f42c1'),
    ('training', 'Training & How-To', 'Training materials and how-to guides', 'bi-book', '#fd7e14'),
    ('general', 'General', 'General inquiries and miscellaneous', 'bi-question-circle', '#0dcaf0')
ON CONFLICT (name) DO NOTHING;


-- ============================================
-- HELPER VIEWS
-- ============================================

-- View: Article search results with all metadata
CREATE OR REPLACE VIEW kb_article_search AS
SELECT
    a.id,
    a.title,
    a.problem,
    a.solution,
    a.category,
    a.subcategory,
    a.tags,
    a.source_type,
    a.source_id,
    a.resolved_by,
    a.asked_by,
    a.customer_company,
    a.resolved_date,
    a.status,
    a.verified,
    a.view_count,
    a.helpful_count,
    a.not_helpful_count,
    a.times_cited,
    CASE
        WHEN (a.helpful_count + a.not_helpful_count) > 0
        THEN ROUND((a.helpful_count::NUMERIC / (a.helpful_count + a.not_helpful_count) * 100), 1)
        ELSE NULL
    END as helpfulness_score,
    c.display_name as category_name,
    c.icon as category_icon,
    c.color as category_color
FROM knowledge_base_articles a
LEFT JOIN knowledge_base_categories c ON a.category = c.name
WHERE a.status = 'active';


-- View: Knowledge gaps needing attention
CREATE OR REPLACE VIEW kb_gaps_priority AS
SELECT
    g.*,
    CASE
        WHEN g.times_asked >= 10 THEN 'critical'
        WHEN g.times_asked >= 5 THEN 'high'
        WHEN g.times_asked >= 3 THEN 'normal'
        ELSE 'low'
    END as calculated_priority,
    EXTRACT(DAY FROM NOW() - g.first_asked_at) as days_open
FROM knowledge_base_gaps g
WHERE g.status IN ('open', 'in_progress')
ORDER BY g.times_asked DESC, g.first_asked_at ASC;


-- View: Query answer rate by category
CREATE OR REPLACE VIEW kb_answer_rates AS
SELECT
    DATE_TRUNC('day', created_at)::DATE as query_date,
    COUNT(*) as total_queries,
    COUNT(CASE WHEN was_answered = TRUE THEN 1 END) as answered,
    COUNT(CASE WHEN was_answered = FALSE THEN 1 END) as unanswered,
    ROUND(
        COUNT(CASE WHEN was_answered = TRUE THEN 1 END)::NUMERIC /
        NULLIF(COUNT(*), 0) * 100, 1
    ) as answer_rate
FROM knowledge_base_queries
GROUP BY DATE_TRUNC('day', created_at)::DATE
ORDER BY query_date DESC;


-- Grant permissions
GRANT ALL ON ALL TABLES IN SCHEMA public TO call_insights_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO call_insights_user;

COMMIT;

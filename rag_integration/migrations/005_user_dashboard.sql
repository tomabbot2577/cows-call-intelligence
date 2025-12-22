-- =====================================================
-- USER ACTIVITY DASHBOARD - DATABASE MIGRATION
-- Migration: 005_user_dashboard.sql
-- Date: 2025-12-22
-- Description: Creates tables for user dashboard metrics,
--              email triggers, and Freshdesk agent mapping
-- =====================================================

-- 1. Daily aggregated metrics per employee
CREATE TABLE IF NOT EXISTS user_daily_metrics (
    id SERIAL PRIMARY KEY,
    employee_name VARCHAR(100) NOT NULL,
    metric_date DATE NOT NULL,

    -- Call Metrics
    total_calls INTEGER DEFAULT 0,
    answered_calls INTEGER DEFAULT 0,
    missed_calls INTEGER DEFAULT 0,
    voicemail_calls INTEGER DEFAULT 0,
    inbound_calls INTEGER DEFAULT 0,
    outbound_calls INTEGER DEFAULT 0,
    avg_duration_seconds REAL DEFAULT 0,
    total_duration_seconds INTEGER DEFAULT 0,
    avg_talk_time_seconds REAL,  -- NULL if not available
    avg_hold_time_seconds REAL,  -- NULL if not available
    avg_ring_time_seconds REAL,  -- NULL if not available
    employee_talk_pct REAL,      -- From diarization, NULL if not available

    -- Call Quality Metrics (from insights table)
    avg_quality_score REAL,
    avg_satisfaction_score REAL,
    positive_sentiment_count INTEGER DEFAULT 0,
    negative_sentiment_count INTEGER DEFAULT 0,
    neutral_sentiment_count INTEGER DEFAULT 0,
    escalation_count INTEGER DEFAULT 0,
    first_contact_resolution_count INTEGER DEFAULT 0,
    high_churn_risk_count INTEGER DEFAULT 0,

    -- Ticket Metrics (from kb_freshdesk_qa)
    tickets_opened INTEGER DEFAULT 0,
    tickets_closed INTEGER DEFAULT 0,
    tickets_open_total INTEGER DEFAULT 0,  -- Snapshot at end of day
    tickets_over_1_day INTEGER DEFAULT 0,
    tickets_over_3_days INTEGER DEFAULT 0,
    tickets_over_5_days INTEGER DEFAULT 0,
    tickets_over_7_days INTEGER DEFAULT 0,
    avg_first_response_minutes REAL,
    first_contact_ticket_resolution INTEGER DEFAULT 0,

    -- Productivity Score (calculated)
    productivity_score REAL,
    productivity_grade VARCHAR(2),  -- A+, A, A-, B+, B, B-, C+, C, C-, D, F
    productivity_breakdown JSONB,   -- Component scores

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_user_daily_metrics UNIQUE (employee_name, metric_date)
);

-- Indexes for user_daily_metrics
CREATE INDEX IF NOT EXISTS idx_udm_employee ON user_daily_metrics(employee_name);
CREATE INDEX IF NOT EXISTS idx_udm_date ON user_daily_metrics(metric_date);
CREATE INDEX IF NOT EXISTS idx_udm_employee_date ON user_daily_metrics(employee_name, metric_date);
CREATE INDEX IF NOT EXISTS idx_udm_score ON user_daily_metrics(productivity_score);

-- 2. Hourly call volume breakdown (for charts)
CREATE TABLE IF NOT EXISTS user_hourly_call_volume (
    id SERIAL PRIMARY KEY,
    employee_name VARCHAR(100) NOT NULL,
    metric_date DATE NOT NULL,
    hour_of_day INTEGER NOT NULL CHECK (hour_of_day >= 0 AND hour_of_day < 24),

    total_calls INTEGER DEFAULT 0,
    inbound_calls INTEGER DEFAULT 0,
    outbound_calls INTEGER DEFAULT 0,
    answered_calls INTEGER DEFAULT 0,
    missed_calls INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_user_hourly UNIQUE (employee_name, metric_date, hour_of_day)
);

CREATE INDEX IF NOT EXISTS idx_uhcv_employee_date ON user_hourly_call_volume(employee_name, metric_date);

-- 3. Ticket aging snapshot (daily snapshot of open ticket distribution)
CREATE TABLE IF NOT EXISTS ticket_aging_snapshot (
    id SERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    agent_name VARCHAR(100) NOT NULL,

    tickets_0_1_days INTEGER DEFAULT 0,
    tickets_1_3_days INTEGER DEFAULT 0,
    tickets_3_5_days INTEGER DEFAULT 0,
    tickets_5_7_days INTEGER DEFAULT 0,
    tickets_7_plus_days INTEGER DEFAULT 0,
    total_open INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_ticket_aging UNIQUE (snapshot_date, agent_name)
);

CREATE INDEX IF NOT EXISTS idx_tas_date ON ticket_aging_snapshot(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_tas_agent ON ticket_aging_snapshot(agent_name);

-- 4. Email trigger configuration
CREATE TABLE IF NOT EXISTS dashboard_email_triggers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,

    -- Trigger Type
    trigger_type VARCHAR(50) NOT NULL,
    -- 'below_expectations' - Alert when metrics fall below threshold
    -- 'meets_expectations' - Notify when metrics are on track
    -- 'exceeds_expectations' - Celebrate when metrics exceed targets
    -- 'daily_summary' - Scheduled daily report
    -- 'weekly_summary' - Scheduled weekly report
    -- 'threshold_alert' - Immediate alert on specific condition

    -- Scope
    applies_to VARCHAR(50) NOT NULL DEFAULT 'all_users',
    -- 'all_users', 'specific_users'
    target_employees TEXT[],  -- NULL for all users, or list of employee names

    -- Conditions (JSONB for flexibility)
    conditions JSONB NOT NULL DEFAULT '{}',
    -- Example: {"metric": "answer_rate", "operator": "less_than", "value": 80, "period": "today"}

    -- Multiple conditions support
    condition_logic VARCHAR(10) DEFAULT 'AND',  -- AND, OR

    -- Recipients
    notify_admin BOOLEAN DEFAULT TRUE,
    notify_user BOOLEAN DEFAULT FALSE,
    notify_all_admins BOOLEAN DEFAULT FALSE,
    custom_emails TEXT[],  -- Additional email addresses

    -- Schedule
    frequency VARCHAR(20) NOT NULL DEFAULT 'daily',
    -- 'realtime' (every 15 min), 'hourly', 'daily', 'weekly'
    schedule_time TIME,  -- For daily/weekly triggers
    schedule_day INTEGER,  -- 0-6 for weekly (0=Monday)

    -- Cooldown (prevent duplicate alerts)
    cooldown_minutes INTEGER DEFAULT 60,
    last_triggered_at TIMESTAMP,
    trigger_count INTEGER DEFAULT 0,

    -- Email template customization
    email_subject_template TEXT,
    email_body_template TEXT,

    -- Audit
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT valid_trigger_type CHECK (
        trigger_type IN ('below_expectations', 'meets_expectations',
                         'exceeds_expectations', 'daily_summary',
                         'weekly_summary', 'threshold_alert')
    ),
    CONSTRAINT valid_frequency CHECK (
        frequency IN ('realtime', 'hourly', 'daily', 'weekly')
    ),
    CONSTRAINT valid_applies_to CHECK (
        applies_to IN ('all_users', 'specific_users')
    )
);

CREATE INDEX IF NOT EXISTS idx_det_active ON dashboard_email_triggers(is_active);
CREATE INDEX IF NOT EXISTS idx_det_type ON dashboard_email_triggers(trigger_type);
CREATE INDEX IF NOT EXISTS idx_det_frequency ON dashboard_email_triggers(frequency);

-- 5. Trigger execution log
CREATE TABLE IF NOT EXISTS dashboard_trigger_log (
    id SERIAL PRIMARY KEY,
    trigger_id INTEGER REFERENCES dashboard_email_triggers(id) ON DELETE SET NULL,
    trigger_name VARCHAR(100),  -- Denormalized for history
    triggered_at TIMESTAMP DEFAULT NOW(),

    -- Context
    employee_name VARCHAR(100),
    period VARCHAR(20),

    -- Metrics at trigger time
    metric_name VARCHAR(100),
    metric_value REAL,
    threshold_value REAL,

    -- Full metrics snapshot
    metrics_snapshot JSONB,

    -- Evaluation result
    evaluation_result VARCHAR(50),  -- 'below', 'meets', 'exceeds', 'triggered'
    trigger_reason TEXT,  -- Human-readable reason

    -- Notification details
    recipients TEXT[],
    email_sent BOOLEAN DEFAULT FALSE,
    email_subject TEXT,
    email_error TEXT,

    -- Result
    action_taken VARCHAR(50)  -- 'email_sent', 'email_failed', 'skipped_cooldown'
);

CREATE INDEX IF NOT EXISTS idx_dtl_trigger ON dashboard_trigger_log(trigger_id);
CREATE INDEX IF NOT EXISTS idx_dtl_employee ON dashboard_trigger_log(employee_name);
CREATE INDEX IF NOT EXISTS idx_dtl_triggered_at ON dashboard_trigger_log(triggered_at);
CREATE INDEX IF NOT EXISTS idx_dtl_date ON dashboard_trigger_log(DATE(triggered_at));

-- 6. Freshdesk agent to PCR employee mapping
CREATE TABLE IF NOT EXISTS freshdesk_agent_map (
    id SERIAL PRIMARY KEY,
    freshdesk_agent_name VARCHAR(100) UNIQUE NOT NULL,
    pcr_employee_name VARCHAR(100),  -- NULL if not mapped

    -- Metadata
    ticket_count INTEGER DEFAULT 0,  -- How many tickets this agent has
    first_seen_at TIMESTAMP,
    last_seen_at TIMESTAMP,

    -- Mapping info
    mapped_by VARCHAR(100),
    mapped_at TIMESTAMP,
    auto_matched BOOLEAN DEFAULT FALSE,  -- True if auto-matched by name similarity
    match_confidence REAL,  -- 0-1 confidence score for auto-match

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fam_pcr_employee ON freshdesk_agent_map(pcr_employee_name);
CREATE INDEX IF NOT EXISTS idx_fam_unmapped ON freshdesk_agent_map(pcr_employee_name) WHERE pcr_employee_name IS NULL;

-- 7. User dashboard preferences
CREATE TABLE IF NOT EXISTS user_dashboard_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,

    -- Display preferences
    default_period VARCHAR(20) DEFAULT 'today',
    show_call_metrics BOOLEAN DEFAULT TRUE,
    show_ticket_metrics BOOLEAN DEFAULT TRUE,
    show_quality_metrics BOOLEAN DEFAULT TRUE,
    show_productivity_score BOOLEAN DEFAULT TRUE,

    -- Chart preferences
    chart_type VARCHAR(20) DEFAULT 'bar',  -- 'bar', 'line'
    show_hourly_chart BOOLEAN DEFAULT TRUE,
    show_aging_chart BOOLEAN DEFAULT TRUE,

    -- Notification preferences
    email_daily_summary BOOLEAN DEFAULT FALSE,
    email_weekly_summary BOOLEAN DEFAULT FALSE,
    email_threshold_alerts BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_user_prefs UNIQUE (user_id)
);

-- Add email column to users table if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'email'
    ) THEN
        ALTER TABLE users ADD COLUMN email VARCHAR(255);
    END IF;
END $$;

-- =====================================================
-- VIEWS FOR COMMON QUERIES
-- =====================================================

-- View: Active employees (with calls or tickets in last 30 days)
CREATE OR REPLACE VIEW active_employees_30d AS
SELECT DISTINCT employee_name
FROM user_daily_metrics
WHERE metric_date >= CURRENT_DATE - INTERVAL '30 days'
  AND (total_calls > 0 OR tickets_opened > 0 OR tickets_closed > 0);

-- View: Latest metrics for each employee
CREATE OR REPLACE VIEW latest_employee_metrics AS
SELECT DISTINCT ON (employee_name)
    employee_name,
    metric_date,
    total_calls,
    answered_calls,
    CASE WHEN total_calls > 0
         THEN ROUND((answered_calls::NUMERIC / total_calls) * 100, 1)
         ELSE 0 END AS answer_rate,
    avg_quality_score,
    tickets_open_total,
    tickets_over_5_days,
    productivity_score,
    productivity_grade
FROM user_daily_metrics
ORDER BY employee_name, metric_date DESC;

-- View: Unmapped Freshdesk agents
CREATE OR REPLACE VIEW unmapped_freshdesk_agents AS
SELECT
    f.freshdesk_agent_name,
    f.ticket_count,
    f.first_seen_at,
    f.last_seen_at
FROM freshdesk_agent_map f
WHERE f.pcr_employee_name IS NULL
ORDER BY f.ticket_count DESC;

-- =====================================================
-- COMMENTS
-- =====================================================

COMMENT ON TABLE user_daily_metrics IS 'Daily aggregated metrics per employee for dashboard display';
COMMENT ON TABLE user_hourly_call_volume IS 'Hourly call volume breakdown for charts';
COMMENT ON TABLE ticket_aging_snapshot IS 'Daily snapshot of ticket aging distribution by agent';
COMMENT ON TABLE dashboard_email_triggers IS 'Configuration for automated email notifications';
COMMENT ON TABLE dashboard_trigger_log IS 'Log of all trigger evaluations and email sends';
COMMENT ON TABLE freshdesk_agent_map IS 'Maps Freshdesk agent names to canonical PCR employee names';
COMMENT ON TABLE user_dashboard_preferences IS 'Per-user dashboard display and notification preferences';

COMMENT ON COLUMN user_daily_metrics.productivity_score IS 'Weighted score 0-100 based on call, ticket, and quality metrics';
COMMENT ON COLUMN user_daily_metrics.employee_talk_pct IS 'Percentage of call talk time by employee (from diarization)';
COMMENT ON COLUMN dashboard_email_triggers.conditions IS 'JSONB with metric, operator, value, and period fields';
COMMENT ON COLUMN freshdesk_agent_map.match_confidence IS 'Confidence score 0-1 for auto-matched names';

-- =====================================================
-- INITIAL DATA: Populate freshdesk_agent_map from existing data
-- =====================================================

INSERT INTO freshdesk_agent_map (freshdesk_agent_name, ticket_count, first_seen_at, last_seen_at)
SELECT
    agent_name,
    COUNT(*) as ticket_count,
    MIN(created_at) as first_seen_at,
    MAX(created_at) as last_seen_at
FROM kb_freshdesk_qa
WHERE agent_name IS NOT NULL AND agent_name != ''
GROUP BY agent_name
ON CONFLICT (freshdesk_agent_name) DO UPDATE SET
    ticket_count = EXCLUDED.ticket_count,
    last_seen_at = EXCLUDED.last_seen_at,
    updated_at = NOW();

-- Auto-match obvious names (exact matches to canonical list)
UPDATE freshdesk_agent_map
SET
    pcr_employee_name = CASE
        WHEN LOWER(freshdesk_agent_name) = 'jim lombardo' THEN 'James Lombardo'
        WHEN LOWER(freshdesk_agent_name) = 'robin montoni' THEN 'Robin Montoni'
        WHEN LOWER(freshdesk_agent_name) = 'dylan bello' THEN 'Dylan Bello'
        WHEN LOWER(freshdesk_agent_name) = 'andrew rothman' THEN 'Andrew Rothman'
        WHEN LOWER(freshdesk_agent_name) = 'james blair' THEN 'James Blair'
        WHEN LOWER(freshdesk_agent_name) = 'nick bradach' THEN 'Nicholas Bradach'
        WHEN LOWER(freshdesk_agent_name) = 'nicholas bradach' THEN 'Nicholas Bradach'
        WHEN LOWER(freshdesk_agent_name) = 'garrett komyati' THEN 'Garrett Komyati'
        WHEN LOWER(freshdesk_agent_name) = 'samuel barnes' THEN 'Samuel Barnes'
        WHEN LOWER(freshdesk_agent_name) = 'sam barnes' THEN 'Samuel Barnes'
        WHEN LOWER(freshdesk_agent_name) = 'bill kubicek' THEN 'Bill Kubicek'
        WHEN LOWER(freshdesk_agent_name) = 'lisa rogers' THEN 'Lisa Rogers'
        WHEN LOWER(freshdesk_agent_name) = 'sean mclaughlin' THEN 'Sean McLaughlin'
        WHEN LOWER(freshdesk_agent_name) = 'mackenzie scalise' THEN 'Mackenzie Scalise'
        WHEN LOWER(freshdesk_agent_name) = 'matthew mueller' THEN 'Matthew Mueller'
        WHEN LOWER(freshdesk_agent_name) = 'matt mueller' THEN 'Matthew Mueller'
        WHEN LOWER(freshdesk_agent_name) = 'jason salamon' THEN 'Jason Salamon'
        WHEN LOWER(freshdesk_agent_name) = 'christian salem' THEN 'Christian Salem'
        ELSE pcr_employee_name
    END,
    auto_matched = TRUE,
    match_confidence = 1.0,
    mapped_at = NOW()
WHERE pcr_employee_name IS NULL
  AND LOWER(freshdesk_agent_name) IN (
      'jim lombardo', 'robin montoni', 'dylan bello', 'andrew rothman',
      'james blair', 'nick bradach', 'nicholas bradach', 'garrett komyati',
      'samuel barnes', 'sam barnes', 'bill kubicek', 'lisa rogers',
      'sean mclaughlin', 'mackenzie scalise', 'matthew mueller', 'matt mueller',
      'jason salamon', 'christian salem'
  );

-- =====================================================
-- GRANT PERMISSIONS
-- =====================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON user_daily_metrics TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_hourly_call_volume TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ticket_aging_snapshot TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON dashboard_email_triggers TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON dashboard_trigger_log TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON freshdesk_agent_map TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_dashboard_preferences TO call_insights_user;

GRANT USAGE, SELECT ON SEQUENCE user_daily_metrics_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE user_hourly_call_volume_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE ticket_aging_snapshot_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE dashboard_email_triggers_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE dashboard_trigger_log_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE freshdesk_agent_map_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE user_dashboard_preferences_id_seq TO call_insights_user;

-- Done
SELECT 'Migration 005_user_dashboard.sql completed successfully' AS status;

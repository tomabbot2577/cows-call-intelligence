-- =====================================================
-- VIDEO MEETING INTELLIGENCE - DATABASE MIGRATION
-- Migration: 007_video_meetings.sql
-- Date: 2025-12-22
-- Description: Creates tables for unified video meeting intelligence
--              supporting Fathom AI and RingCentral Video sources
--              with 6-layer AI processing pipeline
-- =====================================================

-- Enable pgcrypto for encryption functions if not already enabled
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =====================================================
-- 1. FATHOM API KEYS - Employee API credentials (encrypted)
-- =====================================================

CREATE TABLE IF NOT EXISTS fathom_api_keys (
    id SERIAL PRIMARY KEY,
    employee_name VARCHAR(255) NOT NULL,
    employee_email VARCHAR(255) UNIQUE NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    team VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,

    -- Sync tracking
    last_sync_at TIMESTAMPTZ,
    last_recording_id BIGINT,
    sync_error_count INTEGER DEFAULT 0,
    last_error_message TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fathom_api_keys_active ON fathom_api_keys(is_active);
CREATE INDEX IF NOT EXISTS idx_fathom_api_keys_email ON fathom_api_keys(employee_email);
CREATE INDEX IF NOT EXISTS idx_fathom_api_keys_admin ON fathom_api_keys(is_admin) WHERE is_admin = TRUE;

COMMENT ON TABLE fathom_api_keys IS 'Stores encrypted Fathom API keys for each employee (12 employees max)';
COMMENT ON COLUMN fathom_api_keys.api_key_encrypted IS 'Fernet-encrypted API key';

-- =====================================================
-- 2. VIDEO MEETINGS - Unified meeting storage (Fathom + RingCentral)
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meetings (
    id SERIAL PRIMARY KEY,

    -- Source identification
    recording_id BIGINT NOT NULL,
    source VARCHAR(20) NOT NULL CHECK (source IN ('fathom', 'ringcentral')),
    source_unique_id VARCHAR(500),

    -- Source-specific URLs
    fathom_url VARCHAR(500),
    share_url VARCHAR(500),
    ringcentral_bridge_id VARCHAR(255),
    ringcentral_short_id VARCHAR(50),

    -- Meeting metadata
    title VARCHAR(500),
    meeting_title VARCHAR(500),
    meeting_type VARCHAR(50),
    platform VARCHAR(50),
    transcript_language VARCHAR(10) DEFAULT 'en',
    calendar_invitees_domains_type VARCHAR(50),

    -- Timing
    scheduled_start_time TIMESTAMPTZ,
    scheduled_end_time TIMESTAMPTZ,
    recording_start_time TIMESTAMPTZ,
    recording_end_time TIMESTAMPTZ,
    duration_seconds INTEGER,

    -- Host/Recorder
    host_name VARCHAR(255),
    host_email VARCHAR(255),
    host_email_domain VARCHAR(255),
    host_team VARCHAR(100),
    host_extension_id VARCHAR(50),
    host_account_id VARCHAR(50),
    host_phone VARCHAR(50),

    -- Participant counts
    participant_count INTEGER,
    internal_participant_count INTEGER,
    external_participant_count INTEGER,

    -- Raw JSON storage
    participants_json JSONB,
    action_items_json JSONB,
    crm_matches_json JSONB,
    transcript_segments_json JSONB,

    -- Content
    transcript_text TEXT,
    word_count INTEGER,
    fathom_summary TEXT,
    fathom_summary_template VARCHAR(50),
    ringcentral_keywords JSONB,
    chat_transcript_url VARCHAR(500),

    -- Recording info
    recording_url VARCHAR(500),
    recording_media_url VARCHAR(500),
    recording_file_size BIGINT,
    recording_status VARCHAR(50),

    -- Processing status
    download_status VARCHAR(50) DEFAULT 'pending',
    transcription_status VARCHAR(50) DEFAULT 'pending',
    downloaded_at TIMESTAMPTZ,
    downloaded_by_employee_id INTEGER REFERENCES fathom_api_keys(id),
    downloaded_by_employee_email VARCHAR(255),

    -- Layer processing flags (6 layers)
    layer1_complete BOOLEAN DEFAULT FALSE,
    layer2_complete BOOLEAN DEFAULT FALSE,
    layer3_complete BOOLEAN DEFAULT FALSE,
    layer4_complete BOOLEAN DEFAULT FALSE,
    layer5_complete BOOLEAN DEFAULT FALSE,
    layer6_complete BOOLEAN DEFAULT FALSE,

    -- Duplicate prevention
    content_hash VARCHAR(64),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint per source
    CONSTRAINT unique_source_recording UNIQUE (source, recording_id)
);

CREATE INDEX IF NOT EXISTS idx_video_meetings_source ON video_meetings(source);
CREATE INDEX IF NOT EXISTS idx_video_meetings_host ON video_meetings(host_email);
CREATE INDEX IF NOT EXISTS idx_video_meetings_date ON video_meetings(recording_start_time);
CREATE INDEX IF NOT EXISTS idx_video_meetings_type ON video_meetings(meeting_type);
CREATE INDEX IF NOT EXISTS idx_video_meetings_platform ON video_meetings(platform);
CREATE INDEX IF NOT EXISTS idx_video_meetings_status ON video_meetings(download_status);
CREATE INDEX IF NOT EXISTS idx_video_meetings_layers ON video_meetings(layer1_complete, layer2_complete, layer3_complete, layer4_complete, layer5_complete, layer6_complete);
CREATE INDEX IF NOT EXISTS idx_video_meetings_hash ON video_meetings(content_hash);
CREATE INDEX IF NOT EXISTS idx_video_meetings_downloaded_by ON video_meetings(downloaded_by_employee_id);
CREATE INDEX IF NOT EXISTS idx_video_meetings_external ON video_meetings(calendar_invitees_domains_type);
CREATE INDEX IF NOT EXISTS idx_video_meetings_rc_bridge ON video_meetings(ringcentral_bridge_id);
CREATE INDEX IF NOT EXISTS idx_video_meetings_all_layers ON video_meetings(id)
    WHERE layer1_complete AND layer2_complete AND layer3_complete AND layer4_complete AND layer5_complete AND layer6_complete;

COMMENT ON TABLE video_meetings IS 'Unified storage for video meetings from Fathom AI and RingCentral Video';
COMMENT ON COLUMN video_meetings.source IS 'fathom or ringcentral';
COMMENT ON COLUMN video_meetings.meeting_type IS 'training, sales, internal, external, customer_success, screen_share';

-- =====================================================
-- 3. VIDEO MEETING PARTICIPANTS - Individual participant records
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meeting_participants (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES video_meetings(id) ON DELETE CASCADE,

    -- Source tracking
    source VARCHAR(20),

    -- Participant identity
    participant_name VARCHAR(255),
    participant_email VARCHAR(255),
    participant_email_domain VARCHAR(255),
    is_external BOOLEAN,
    matched_speaker_display_name VARCHAR(255),

    -- RingCentral-specific fields
    ringcentral_account_id VARCHAR(50),
    ringcentral_extension_id VARCHAR(50),
    ringcentral_session_id VARCHAR(100),
    participant_type VARCHAR(50),

    -- Contact information (enriched from RingCentral)
    phone_business VARCHAR(50),
    phone_mobile VARCHAR(50),
    phone_extension VARCHAR(20),

    -- Team info
    team VARCHAR(100),
    department VARCHAR(100),

    -- Speaking metrics
    speaking_time_seconds INTEGER,
    speaking_percentage DECIMAL(5,2),
    word_count INTEGER,
    segment_count INTEGER,

    -- Engagement indicators
    questions_asked INTEGER,
    was_dominant_speaker BOOLEAN DEFAULT FALSE,
    sentiment_score DECIMAL(3,2),
    engagement_level VARCHAR(20),

    -- CRM match data
    crm_contact_name VARCHAR(255),
    crm_contact_email VARCHAR(255),
    crm_contact_url VARCHAR(500),
    crm_company_name VARCHAR(255),
    crm_company_url VARCHAR(500),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_participants_meeting ON video_meeting_participants(meeting_id);
CREATE INDEX IF NOT EXISTS idx_participants_source ON video_meeting_participants(source);
CREATE INDEX IF NOT EXISTS idx_participants_email ON video_meeting_participants(participant_email);
CREATE INDEX IF NOT EXISTS idx_participants_domain ON video_meeting_participants(participant_email_domain);
CREATE INDEX IF NOT EXISTS idx_participants_external ON video_meeting_participants(is_external);
CREATE INDEX IF NOT EXISTS idx_participants_company ON video_meeting_participants(crm_company_name);
CREATE INDEX IF NOT EXISTS idx_participants_phone ON video_meeting_participants(phone_business);
CREATE INDEX IF NOT EXISTS idx_participants_extension ON video_meeting_participants(ringcentral_extension_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_participants_unique ON video_meeting_participants(meeting_id, participant_email);

COMMENT ON TABLE video_meeting_participants IS 'Individual participant records with contact info and speaking metrics';
COMMENT ON COLUMN video_meeting_participants.is_external IS 'TRUE = customer/prospect, FALSE = internal employee';

-- =====================================================
-- 4. VIDEO MEETING ACTION ITEMS - From Fathom
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meeting_action_items (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES video_meetings(id) ON DELETE CASCADE,

    -- Action item details
    description TEXT NOT NULL,
    user_generated BOOLEAN DEFAULT FALSE,
    completed BOOLEAN DEFAULT FALSE,

    -- Timestamp in recording
    recording_timestamp VARCHAR(20),
    recording_playback_url VARCHAR(500),

    -- Assignee details
    assignee_name VARCHAR(255),
    assignee_email VARCHAR(255),
    assignee_team VARCHAR(100),

    -- Due date
    due_date DATE,
    priority VARCHAR(20),

    -- Follow-up tracking
    follow_up_sent BOOLEAN DEFAULT FALSE,
    follow_up_sent_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_action_items_meeting ON video_meeting_action_items(meeting_id);
CREATE INDEX IF NOT EXISTS idx_action_items_assignee ON video_meeting_action_items(assignee_email);
CREATE INDEX IF NOT EXISTS idx_action_items_completed ON video_meeting_action_items(completed);
CREATE INDEX IF NOT EXISTS idx_action_items_due ON video_meeting_action_items(due_date);

COMMENT ON TABLE video_meeting_action_items IS 'Action items extracted from video meetings with assignee tracking';

-- =====================================================
-- 5. VIDEO MEETING CRM DEALS - Deal associations
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meeting_crm_deals (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES video_meetings(id) ON DELETE CASCADE,

    -- Deal details from CRM matches
    deal_name VARCHAR(255),
    deal_amount DECIMAL(15,2),
    deal_record_url VARCHAR(500),

    -- Additional deal tracking
    deal_stage VARCHAR(100),
    deal_probability DECIMAL(5,2),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_deals_meeting ON video_meeting_crm_deals(meeting_id);
CREATE INDEX IF NOT EXISTS idx_crm_deals_amount ON video_meeting_crm_deals(deal_amount);

COMMENT ON TABLE video_meeting_crm_deals IS 'CRM deal associations from video meetings';

-- =====================================================
-- 6. VIDEO MEETING INSIGHTS - Layer 2 Sentiment Analysis
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meeting_insights (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES video_meetings(id) ON DELETE CASCADE UNIQUE,

    -- Sentiment
    overall_sentiment VARCHAR(20),
    sentiment_score DECIMAL(3,2),
    sentiment_reasoning TEXT,
    customer_sentiment VARCHAR(20),

    -- Meeting quality
    meeting_quality_score DECIMAL(3,1),
    quality_reasoning TEXT,
    engagement_level VARCHAR(20),

    -- SaaS-Specific Metrics
    nps_indicator INTEGER,
    customer_satisfaction_signals JSONB,
    churn_risk_level VARCHAR(20),
    churn_risk_signals JSONB,
    upsell_opportunity_detected BOOLEAN DEFAULT FALSE,
    expansion_signals JSONB,

    -- Classification
    meeting_category VARCHAR(50),
    call_type VARCHAR(50),
    key_topics JSONB,

    -- Outcomes
    decisions_made JSONB,
    follow_up_required BOOLEAN DEFAULT FALSE,
    escalation_needed BOOLEAN DEFAULT FALSE,

    -- Summary
    ai_summary TEXT,
    one_liner TEXT,

    -- Competitor Intel
    competitors_mentioned JSONB,
    competitive_positioning_notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vm_insights_sentiment ON video_meeting_insights(overall_sentiment);
CREATE INDEX IF NOT EXISTS idx_vm_insights_churn ON video_meeting_insights(churn_risk_level);
CREATE INDEX IF NOT EXISTS idx_vm_insights_nps ON video_meeting_insights(nps_indicator);
CREATE INDEX IF NOT EXISTS idx_vm_insights_meeting ON video_meeting_insights(meeting_id);

COMMENT ON TABLE video_meeting_insights IS 'Layer 2: Sentiment and customer health analysis';

-- =====================================================
-- 7. VIDEO MEETING RESOLUTIONS - Layer 3 Outcomes
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meeting_resolutions (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES video_meetings(id) ON DELETE CASCADE UNIQUE,

    -- Meeting objectives
    objectives_identified JSONB,
    objectives_met BOOLEAN,
    objectives_met_score DECIMAL(3,1),
    objectives_met_reasoning TEXT,

    -- Action items analysis
    action_items_count INTEGER,
    action_items_assigned INTEGER,
    action_items_with_deadlines INTEGER,
    action_items_with_owners INTEGER,
    action_items_analysis JSONB,
    action_item_quality_score DECIMAL(3,1),

    -- Decision tracking
    decisions_count INTEGER,
    decisions_documented BOOLEAN,
    decision_clarity_score DECIMAL(3,1),
    key_decisions JSONB,

    -- SaaS Customer Success Metrics
    first_contact_resolution BOOLEAN,
    time_to_resolution_minutes INTEGER,
    escalation_avoided BOOLEAN,
    customer_effort_score DECIMAL(3,1),

    -- Follow-up quality
    next_steps_defined BOOLEAN,
    timeline_established BOOLEAN,
    owners_assigned BOOLEAN,
    follow_up_date_set BOOLEAN,
    follow_up_date DATE,

    -- Meeting effectiveness
    time_efficiency_score DECIMAL(3,1),
    participation_balance_score DECIMAL(3,1),
    conclusion_quality_score DECIMAL(3,1),

    -- Loop closure
    solution_summarized BOOLEAN,
    understanding_confirmed BOOLEAN,
    asked_if_anything_else BOOLEAN,
    next_steps_provided BOOLEAN,
    timeline_given BOOLEAN,
    contact_info_provided BOOLEAN,
    thanked_customer BOOLEAN,
    confirmed_satisfaction BOOLEAN,
    loop_closure_score DECIMAL(3,1),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vm_resolutions_met ON video_meeting_resolutions(objectives_met);
CREATE INDEX IF NOT EXISTS idx_vm_resolutions_fcr ON video_meeting_resolutions(first_contact_resolution);
CREATE INDEX IF NOT EXISTS idx_vm_resolutions_meeting ON video_meeting_resolutions(meeting_id);

COMMENT ON TABLE video_meeting_resolutions IS 'Layer 3: Resolution and outcomes tracking';

-- =====================================================
-- 8. VIDEO MEETING RECOMMENDATIONS - Layer 4 Coaching
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meeting_recommendations (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES video_meetings(id) ON DELETE CASCADE UNIQUE,

    -- Process improvements
    process_improvements JSONB,
    meeting_structure_suggestions JSONB,

    -- Participant feedback
    host_strengths JSONB,
    host_improvements JSONB,
    participant_engagement_notes JSONB,
    coaching_priorities JSONB,

    -- Communication improvements
    suggested_follow_up_template TEXT,
    key_talking_points JSONB,
    objection_handling_suggestions JSONB,

    -- Training needs
    training_opportunities JSONB,
    knowledge_gaps JSONB,
    skill_development_areas JSONB,
    recommended_training_modules JSONB,

    -- SaaS Sales Recommendations
    deal_progression_suggestions JSONB,
    pricing_discussion_notes TEXT,
    value_proposition_improvements JSONB,
    competitive_response_suggestions JSONB,

    -- SaaS Customer Success Recommendations
    retention_actions JSONB,
    expansion_opportunities JSONB,
    customer_health_actions JSONB,

    -- Risk assessment
    risk_level VARCHAR(20),
    risk_factors JSONB,
    risk_mitigation_suggestions JSONB,

    -- Efficiency
    efficiency_score DECIMAL(3,1),
    time_savings_potential INTEGER,
    meeting_frequency_recommendation TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vm_recommendations_risk ON video_meeting_recommendations(risk_level);
CREATE INDEX IF NOT EXISTS idx_vm_recommendations_meeting ON video_meeting_recommendations(meeting_id);

COMMENT ON TABLE video_meeting_recommendations IS 'Layer 4: Recommendations and coaching suggestions';

-- =====================================================
-- 9. VIDEO MEETING ADVANCED METRICS - Layer 5 AI Insights
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meeting_advanced_metrics (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES video_meetings(id) ON DELETE CASCADE UNIQUE,

    -- Speaking analysis
    speaking_time_distribution JSONB,
    interruption_count INTEGER,
    question_count INTEGER,
    dominant_speaker VARCHAR(255),
    talk_listen_ratio JSONB,

    -- Engagement metrics
    engagement_score DECIMAL(3,1),
    participation_rate DECIMAL(3,2),
    average_response_time_seconds INTEGER,
    silence_percentage DECIMAL(5,2),

    -- Content analysis
    topics_depth_analysis JSONB,
    key_phrases JSONB,
    sentiment_by_speaker JSONB,
    sentiment_timeline JSONB,

    -- SaaS Business Intelligence
    competitor_mentions JSONB,
    product_mentions JSONB,
    feature_requests JSONB,
    pain_points JSONB,
    customer_concerns JSONB,
    opportunities_identified JSONB,
    objections_raised JSONB,

    -- SaaS Sales Metrics (Hormozi)
    hormozi_score DECIMAL(3,1),
    value_proposition_clarity DECIMAL(3,1),
    objection_handling_score DECIMAL(3,1),
    closing_technique_score DECIMAL(3,1),
    discovery_quality_score DECIMAL(3,1),
    rapport_building_score DECIMAL(3,1),
    needs_assessment_score DECIMAL(3,1),

    -- SaaS Customer Success Metrics
    customer_health_score DECIMAL(3,1),
    adoption_indicators JSONB,
    renewal_likelihood DECIMAL(3,2),
    expansion_likelihood DECIMAL(3,2),
    advocacy_potential DECIMAL(3,1),

    -- SaaS Financial Indicators
    deal_value_mentioned DECIMAL(15,2),
    contract_length_mentioned INTEGER,
    discount_discussed BOOLEAN,
    budget_concerns_raised BOOLEAN,
    roi_discussed BOOLEAN,

    -- Performance benchmarks
    meeting_effectiveness_percentile INTEGER,
    host_performance_trend VARCHAR(20),
    team_performance_comparison JSONB,

    -- RAG-ready fields
    searchable_content TEXT,
    embedding_generated BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vm_metrics_engagement ON video_meeting_advanced_metrics(engagement_score);
CREATE INDEX IF NOT EXISTS idx_vm_metrics_health ON video_meeting_advanced_metrics(customer_health_score);
CREATE INDEX IF NOT EXISTS idx_vm_metrics_renewal ON video_meeting_advanced_metrics(renewal_likelihood);
CREATE INDEX IF NOT EXISTS idx_vm_metrics_hormozi ON video_meeting_advanced_metrics(hormozi_score);
CREATE INDEX IF NOT EXISTS idx_vm_metrics_meeting ON video_meeting_advanced_metrics(meeting_id);

COMMENT ON TABLE video_meeting_advanced_metrics IS 'Layer 5: Advanced metrics and AI insights';

-- =====================================================
-- 10. VIDEO MEETING LEARNING ANALYSIS - Layer 6 UTL-based
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meeting_learning_analysis (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES video_meetings(id) ON DELETE CASCADE UNIQUE,

    -- Core Learning Metrics (Unified Theory of Learning)
    learning_score DECIMAL(4,3),
    entropy_delta DECIMAL(4,3),
    coherence_delta DECIMAL(4,3),
    emotional_coefficient DECIMAL(4,3),
    phase_alignment DECIMAL(4,3),

    -- Learning State Classification
    learning_state VARCHAR(50),
    learning_trajectory VARCHAR(50),

    -- Attendee Learning Profiles
    attendee_knowledge_level VARCHAR(20),
    attendee_learning_style VARCHAR(50),
    attendee_comprehension_signals JSONB,
    attendee_confusion_signals JSONB,

    -- Host/Presenter Teaching Effectiveness
    host_teaching_clarity DECIMAL(4,3),
    host_pacing_score DECIMAL(4,3),
    host_scaffolding_quality DECIMAL(4,3),
    host_analogy_usage INTEGER,
    host_check_in_frequency INTEGER,
    host_engagement_techniques JSONB,

    -- Knowledge Transfer Metrics
    concepts_introduced JSONB,
    concepts_understood JSONB,
    concepts_confused JSONB,
    concepts_requiring_followup JSONB,
    knowledge_transfer_rate DECIMAL(4,3),

    -- Meeting Type-Specific Learning Metrics
    training_effectiveness_score DECIMAL(4,3),
    demo_clarity_score DECIMAL(4,3),
    onboarding_progress_score DECIMAL(4,3),

    -- Temporal Learning Analysis
    learning_moments JSONB,
    peak_learning_moments JSONB,
    learning_stall_moments JSONB,
    learning_curve_data JSONB,

    -- Coaching Recommendations (for host/presenter)
    lambda_recommendations JSONB,
    teaching_adjustments_needed JSONB,
    coaching_recommendations JSONB,
    skill_development_priorities JSONB,

    -- Multi-Participant Learning
    participant_learning_scores JSONB,
    group_learning_dynamics JSONB,
    participation_learning_correlation JSONB,

    -- Learning Outcome Correlation
    learning_vs_satisfaction_correlation DECIMAL(4,3),
    learning_vs_action_items_correlation DECIMAL(4,3),

    -- Analysis Metadata
    analysis_model VARCHAR(100),
    analysis_confidence DECIMAL(4,3),
    analysis_notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT valid_learning_score CHECK (learning_score >= 0 AND learning_score <= 1),
    CONSTRAINT valid_entropy CHECK (entropy_delta >= 0 AND entropy_delta <= 1),
    CONSTRAINT valid_coherence CHECK (coherence_delta >= 0 AND coherence_delta <= 1),
    CONSTRAINT valid_emotional CHECK (emotional_coefficient >= 0 AND emotional_coefficient <= 1),
    CONSTRAINT valid_phase CHECK (phase_alignment >= -1 AND phase_alignment <= 1)
);

CREATE INDEX IF NOT EXISTS idx_vm_learning_state ON video_meeting_learning_analysis(learning_state);
CREATE INDEX IF NOT EXISTS idx_vm_learning_score ON video_meeting_learning_analysis(learning_score);
CREATE INDEX IF NOT EXISTS idx_vm_knowledge_transfer ON video_meeting_learning_analysis(knowledge_transfer_rate);
CREATE INDEX IF NOT EXISTS idx_vm_training_effectiveness ON video_meeting_learning_analysis(training_effectiveness_score);
CREATE INDEX IF NOT EXISTS idx_vm_learning_meeting ON video_meeting_learning_analysis(meeting_id);

COMMENT ON TABLE video_meeting_learning_analysis IS 'Layer 6: Learning Intelligence using Unified Theory of Learning (UTL)';
COMMENT ON COLUMN video_meeting_learning_analysis.learning_score IS 'L = f(ΔS × ΔC × wₑ × cos(φ)) - Overall learning effectiveness';
COMMENT ON COLUMN video_meeting_learning_analysis.entropy_delta IS 'ΔS - Amount of novelty/challenge introduced (0-1)';
COMMENT ON COLUMN video_meeting_learning_analysis.coherence_delta IS 'ΔC - Amount of understanding achieved (0-1)';
COMMENT ON COLUMN video_meeting_learning_analysis.emotional_coefficient IS 'wₑ - Emotional engagement level (0-1)';
COMMENT ON COLUMN video_meeting_learning_analysis.phase_alignment IS 'cos(φ) - Challenge-support synchronization (-1 to 1)';
COMMENT ON COLUMN video_meeting_learning_analysis.learning_state IS 'aha_zone, overwhelmed, bored, disengaged, building, struggling, none';

-- =====================================================
-- 11. VIDEO MEETING EMBEDDINGS - Vector search
-- =====================================================

CREATE TABLE IF NOT EXISTS video_meeting_embeddings (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER REFERENCES video_meetings(id) ON DELETE CASCADE UNIQUE,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_meeting_embeddings_vector
ON video_meeting_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

COMMENT ON TABLE video_meeting_embeddings IS 'Vector embeddings for semantic search (OpenAI text-embedding-ada-002)';

-- =====================================================
-- VIEWS FOR COMMON QUERIES
-- =====================================================

-- View: Video meetings ready for RAG export (all 6 layers complete)
CREATE OR REPLACE VIEW video_meetings_ready_for_rag AS
SELECT
    vm.id,
    vm.recording_id,
    vm.source,
    vm.title,
    vm.meeting_type,
    vm.host_name,
    vm.recording_start_time,
    vm.duration_seconds,
    vm.participant_count,
    vmi.overall_sentiment,
    vmi.churn_risk_level,
    vmr.objectives_met,
    vma.hormozi_score,
    vmla.learning_score,
    vmla.learning_state
FROM video_meetings vm
LEFT JOIN video_meeting_insights vmi ON vm.id = vmi.meeting_id
LEFT JOIN video_meeting_resolutions vmr ON vm.id = vmr.meeting_id
LEFT JOIN video_meeting_advanced_metrics vma ON vm.id = vma.meeting_id
LEFT JOIN video_meeting_learning_analysis vmla ON vm.id = vmla.meeting_id
WHERE vm.layer1_complete AND vm.layer2_complete AND vm.layer3_complete
  AND vm.layer4_complete AND vm.layer5_complete AND vm.layer6_complete;

-- View: Host teaching effectiveness ranking
CREATE OR REPLACE VIEW host_teaching_effectiveness AS
SELECT
    vm.host_name,
    vm.host_email,
    COUNT(*) as meeting_count,
    ROUND(AVG(vmla.learning_score)::NUMERIC, 3) as avg_learning_score,
    ROUND(AVG(vmla.knowledge_transfer_rate)::NUMERIC, 3) as avg_transfer_rate,
    ROUND(AVG(vmla.host_teaching_clarity)::NUMERIC, 3) as avg_clarity,
    ROUND(AVG(vmla.host_pacing_score)::NUMERIC, 3) as avg_pacing,
    ROUND(AVG(vmla.host_scaffolding_quality)::NUMERIC, 3) as avg_scaffolding,
    SUM(vmla.host_analogy_usage) as total_analogies,
    SUM(vmla.host_check_in_frequency) as total_check_ins
FROM video_meeting_learning_analysis vmla
JOIN video_meetings vm ON vmla.meeting_id = vm.id
WHERE vmla.learning_state != 'none'
GROUP BY vm.host_name, vm.host_email
ORDER BY avg_learning_score DESC;

-- View: Learning state distribution by meeting type
CREATE OR REPLACE VIEW learning_state_distribution AS
SELECT
    vm.meeting_type,
    vmla.learning_state,
    COUNT(*) as count,
    ROUND(AVG(vmla.learning_score)::NUMERIC, 3) as avg_score
FROM video_meeting_learning_analysis vmla
JOIN video_meetings vm ON vmla.meeting_id = vm.id
GROUP BY vm.meeting_type, vmla.learning_state
ORDER BY vm.meeting_type, count DESC;

-- =====================================================
-- GRANT PERMISSIONS
-- =====================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON fathom_api_keys TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meetings TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meeting_participants TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meeting_action_items TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meeting_crm_deals TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meeting_insights TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meeting_resolutions TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meeting_recommendations TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meeting_advanced_metrics TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meeting_learning_analysis TO call_insights_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON video_meeting_embeddings TO call_insights_user;

GRANT USAGE, SELECT ON SEQUENCE fathom_api_keys_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meetings_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meeting_participants_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meeting_action_items_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meeting_crm_deals_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meeting_insights_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meeting_resolutions_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meeting_recommendations_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meeting_advanced_metrics_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meeting_learning_analysis_id_seq TO call_insights_user;
GRANT USAGE, SELECT ON SEQUENCE video_meeting_embeddings_id_seq TO call_insights_user;

-- =====================================================
-- SUMMARY
-- =====================================================

SELECT 'Migration 007_video_meetings.sql completed successfully' AS status;
SELECT 'Tables created: 11 (fathom_api_keys, video_meetings, video_meeting_participants, video_meeting_action_items, video_meeting_crm_deals, video_meeting_insights, video_meeting_resolutions, video_meeting_recommendations, video_meeting_advanced_metrics, video_meeting_learning_analysis, video_meeting_embeddings)' AS tables;
SELECT 'Views created: 3 (video_meetings_ready_for_rag, host_teaching_effectiveness, learning_state_distribution)' AS views;

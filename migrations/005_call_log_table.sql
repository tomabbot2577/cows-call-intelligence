-- Migration: Create call_log table for ALL RingCentral calls
-- Date: 2025-12-21
-- Purpose: Track all calls (with or without recordings) for complete workflow visibility

CREATE TABLE IF NOT EXISTS call_log (
    -- Primary Key
    id SERIAL PRIMARY KEY,

    -- RingCentral Identifiers
    ringcentral_id TEXT UNIQUE NOT NULL,
    session_id TEXT,
    telephony_session_id TEXT,

    -- Timing
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_seconds INTEGER DEFAULT 0,

    -- Call Classification
    direction TEXT,                    -- Inbound, Outbound
    call_type TEXT,                    -- Voice, Fax
    call_action TEXT,                  -- Phone Call, Transfer, FindMe, VoIP Call, etc.
    call_result TEXT,                  -- Accepted, Missed, Voicemail, No Answer, Busy, etc.
    call_reason TEXT,
    call_reason_description TEXT,

    -- Caller (Customer) Information
    from_phone_number TEXT,
    from_name TEXT,
    from_location TEXT,
    from_extension_number TEXT,
    from_extension_id TEXT,

    -- Called Party (Employee) Information
    to_phone_number TEXT,
    to_name TEXT,
    to_location TEXT,
    to_extension_number TEXT,
    to_extension_id TEXT,

    -- Recording Information (NULL if no recording)
    has_recording BOOLEAN DEFAULT FALSE,
    recording_id TEXT,
    recording_uri TEXT,
    recording_type TEXT,               -- Automatic, OnDemand
    recording_content_uri TEXT,

    -- Call Routing
    call_legs JSONB,                   -- Complete routing path for transfers
    internal_type TEXT,                -- Local, LongDistance, International, etc.
    transport TEXT,                    -- PSTN, VoIP

    -- Link to transcripts table (if transcribed)
    transcript_id TEXT REFERENCES transcripts(recording_id),

    -- Processing Status
    audio_downloaded BOOLEAN DEFAULT FALSE,
    audio_download_time TIMESTAMP WITH TIME ZONE,
    is_transcribed BOOLEAN DEFAULT FALSE,
    transcription_time TIMESTAMP WITH TIME ZONE,

    -- Full metadata backup
    raw_metadata JSONB,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_call_log_start_time ON call_log(start_time);
CREATE INDEX IF NOT EXISTS idx_call_log_result ON call_log(call_result);
CREATE INDEX IF NOT EXISTS idx_call_log_direction ON call_log(direction);
CREATE INDEX IF NOT EXISTS idx_call_log_from_phone ON call_log(from_phone_number);
CREATE INDEX IF NOT EXISTS idx_call_log_to_extension ON call_log(to_extension_number);
CREATE INDEX IF NOT EXISTS idx_call_log_has_recording ON call_log(has_recording);
CREATE INDEX IF NOT EXISTS idx_call_log_session ON call_log(session_id);

-- Comments
COMMENT ON TABLE call_log IS 'All calls from RingCentral including missed, voicemail, abandoned - complete call workflow visibility';
COMMENT ON COLUMN call_log.call_result IS 'Accepted, Missed, Voicemail, No Answer, Busy, Rejected, Abandoned, etc.';
COMMENT ON COLUMN call_log.call_action IS 'Phone Call, Transfer, FindMe, FollowMe, VoIP Call, Conference Call, etc.';
COMMENT ON COLUMN call_log.call_legs IS 'JSON array of call routing steps for transfers and hunt groups';

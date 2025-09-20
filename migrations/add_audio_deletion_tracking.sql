-- Migration: Add audio deletion tracking columns
-- Purpose: Track when audio files are deleted for security compliance
-- Date: 2025-01-19

-- Add audio deletion tracking columns to call_recordings table
ALTER TABLE call_recordings
ADD COLUMN IF NOT EXISTS audio_deleted BOOLEAN DEFAULT FALSE NOT NULL,
ADD COLUMN IF NOT EXISTS audio_deletion_time TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS audio_deletion_verified BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS audio_file_hash VARCHAR(64);

-- Add index for finding undeleted audio
CREATE INDEX IF NOT EXISTS idx_audio_not_deleted
ON call_recordings (audio_deleted)
WHERE audio_deleted = FALSE;

-- Add index for deletion time tracking
CREATE INDEX IF NOT EXISTS idx_audio_deletion_time
ON call_recordings (audio_deletion_time)
WHERE audio_deletion_time IS NOT NULL;

-- Add comment explaining the columns
COMMENT ON COLUMN call_recordings.audio_deleted IS 'Whether the audio file has been deleted after transcription (security compliance)';
COMMENT ON COLUMN call_recordings.audio_deletion_time IS 'Timestamp when the audio file was deleted';
COMMENT ON COLUMN call_recordings.audio_deletion_verified IS 'Whether the deletion was verified (file confirmed not to exist)';
COMMENT ON COLUMN call_recordings.audio_file_hash IS 'SHA-256 hash of the audio file before deletion (for audit trail)';

-- Create audit table for deletion history
CREATE TABLE IF NOT EXISTS audio_deletion_audit (
    id SERIAL PRIMARY KEY,
    recording_id VARCHAR(100) NOT NULL,
    deletion_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    file_path TEXT,
    file_size_bytes BIGINT,
    file_hash VARCHAR(64),
    deletion_method VARCHAR(50),
    deletion_verified BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    metadata JSONB
);

-- Add index on recording_id for audit lookups
CREATE INDEX IF NOT EXISTS idx_deletion_audit_recording
ON audio_deletion_audit (recording_id);

-- Add index on deletion timestamp for time-based queries
CREATE INDEX IF NOT EXISTS idx_deletion_audit_timestamp
ON audio_deletion_audit (deletion_timestamp);

-- Add comment explaining the audit table
COMMENT ON TABLE audio_deletion_audit IS 'Audit trail for audio file deletions - critical for security compliance';

-- Create a view to easily check deletion status
CREATE OR REPLACE VIEW v_audio_deletion_status AS
SELECT
    COUNT(*) AS total_recordings,
    SUM(CASE WHEN audio_deleted = TRUE THEN 1 ELSE 0 END) AS deleted_count,
    SUM(CASE WHEN audio_deleted = FALSE THEN 1 ELSE 0 END) AS not_deleted_count,
    SUM(CASE WHEN audio_deletion_verified = TRUE THEN 1 ELSE 0 END) AS verified_count,
    ROUND(
        100.0 * SUM(CASE WHEN audio_deleted = TRUE THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        2
    ) AS deletion_percentage,
    MIN(audio_deletion_time) AS first_deletion,
    MAX(audio_deletion_time) AS last_deletion
FROM call_recordings;

-- Create a function to check if all audio is deleted
CREATE OR REPLACE FUNCTION check_audio_deletion_compliance()
RETURNS TABLE (
    compliant BOOLEAN,
    total_recordings INTEGER,
    undeleted_count INTEGER,
    oldest_undeleted TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        (COUNT(*) FILTER (WHERE audio_deleted = FALSE) = 0) AS compliant,
        COUNT(*)::INTEGER AS total_recordings,
        COUNT(*) FILTER (WHERE audio_deleted = FALSE)::INTEGER AS undeleted_count,
        MIN(created_at) FILTER (WHERE audio_deleted = FALSE) AS oldest_undeleted
    FROM call_recordings
    WHERE transcription_status = 'completed';
END;
$$ LANGUAGE plpgsql;

-- Grant necessary permissions (adjust user as needed)
GRANT SELECT ON v_audio_deletion_status TO PUBLIC;
GRANT EXECUTE ON FUNCTION check_audio_deletion_compliance() TO PUBLIC;

-- Output migration status
SELECT 'Audio deletion tracking migration completed' AS status,
       NOW() AS completed_at;

-- Show current deletion status
SELECT * FROM v_audio_deletion_status;
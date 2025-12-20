-- RAG Export Tracking Table
-- Tracks which calls have been exported to the RAG system to prevent duplicates

CREATE TABLE IF NOT EXISTS rag_exports (
    id SERIAL PRIMARY KEY,
    recording_id VARCHAR(255) NOT NULL UNIQUE,

    -- Export status
    export_status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, exported, failed, skipped

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    exported_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Export details
    jsonl_file VARCHAR(500),          -- Path to JSONL file
    gcs_uri VARCHAR(500),             -- GCS URI after upload
    vertex_imported BOOLEAN DEFAULT FALSE,
    gemini_imported BOOLEAN DEFAULT FALSE,

    -- Batch tracking
    batch_id VARCHAR(100),            -- Links exports from same batch
    batch_sequence INT,               -- Order within batch

    -- Layer verification (snapshot at export time)
    layer1_complete BOOLEAN DEFAULT FALSE,
    layer2_complete BOOLEAN DEFAULT FALSE,
    layer3_complete BOOLEAN DEFAULT FALSE,
    layer4_complete BOOLEAN DEFAULT FALSE,
    layer5_complete BOOLEAN DEFAULT FALSE,

    -- Error tracking
    error_message TEXT,
    retry_count INT DEFAULT 0,
    last_retry_at TIMESTAMP,

    -- Metadata
    call_date DATE,
    employee_name VARCHAR(255),
    customer_name VARCHAR(255),

    -- Constraints
    CONSTRAINT valid_status CHECK (export_status IN ('pending', 'exported', 'failed', 'skipped'))
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_rag_exports_status ON rag_exports(export_status);
CREATE INDEX IF NOT EXISTS idx_rag_exports_recording_id ON rag_exports(recording_id);
CREATE INDEX IF NOT EXISTS idx_rag_exports_batch_id ON rag_exports(batch_id);
CREATE INDEX IF NOT EXISTS idx_rag_exports_exported_at ON rag_exports(exported_at);
CREATE INDEX IF NOT EXISTS idx_rag_exports_call_date ON rag_exports(call_date);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_rag_exports_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_rag_exports_updated_at ON rag_exports;
CREATE TRIGGER trigger_rag_exports_updated_at
    BEFORE UPDATE ON rag_exports
    FOR EACH ROW
    EXECUTE FUNCTION update_rag_exports_updated_at();

-- View to show export statistics
CREATE OR REPLACE VIEW rag_export_stats AS
SELECT
    export_status,
    COUNT(*) as count,
    MIN(exported_at) as earliest_export,
    MAX(exported_at) as latest_export,
    SUM(CASE WHEN vertex_imported THEN 1 ELSE 0 END) as vertex_imported_count,
    SUM(CASE WHEN gemini_imported THEN 1 ELSE 0 END) as gemini_imported_count
FROM rag_exports
GROUP BY export_status;

-- View to find calls ready for export (all 5 layers complete, not yet exported)
CREATE OR REPLACE VIEW calls_ready_for_rag_export AS
SELECT
    t.recording_id,
    t.call_date,
    t.employee_name,
    t.customer_name,
    t.customer_company
FROM transcripts t
INNER JOIN insights i ON t.recording_id = i.recording_id
INNER JOIN call_resolutions cr ON t.recording_id = cr.recording_id
INNER JOIN call_recommendations rec ON t.recording_id = rec.recording_id
INNER JOIN call_advanced_metrics cam ON t.recording_id = cam.recording_id
LEFT JOIN rag_exports re ON t.recording_id = re.recording_id
WHERE t.transcript_text IS NOT NULL
  AND LENGTH(t.transcript_text) > 100
  AND (t.employee_name IS NOT NULL OR t.customer_name IS NOT NULL)
  AND (re.recording_id IS NULL OR re.export_status = 'failed')
ORDER BY t.call_date DESC;

COMMENT ON TABLE rag_exports IS 'Tracks which call recordings have been exported to the RAG system (Vertex AI and Gemini)';
COMMENT ON VIEW calls_ready_for_rag_export IS 'Shows calls with all 5 layers complete that have not yet been exported to RAG';

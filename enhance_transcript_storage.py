#!/usr/bin/env python3
"""
Enhance database to properly store transcripts with all metadata
Ensures we capture everything from RingCentral and our processing pipeline
"""

import sqlite3
import json
from pathlib import Path
import sys
sys.path.insert(0, '/var/www/call-recording-system')

print("=" * 80)
print("ENHANCING TRANSCRIPT & METADATA STORAGE")
print("=" * 80)

# Connect to database
db_path = '/var/www/call-recording-system/data/insights/insights.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. ALTER existing insights table to add transcript columns
print("\n1. UPDATING INSIGHTS TABLE:")
print("-" * 40)

alter_statements = [
    ("transcript_text", "ALTER TABLE insights ADD COLUMN transcript_text TEXT"),
    ("transcript_file_path", "ALTER TABLE insights ADD COLUMN transcript_file_path TEXT"),
    ("raw_metadata", "ALTER TABLE insights ADD COLUMN raw_metadata JSON"),
    ("ringcentral_id", "ALTER TABLE insights ADD COLUMN ringcentral_id TEXT"),
    ("audio_url", "ALTER TABLE insights ADD COLUMN audio_url TEXT"),
    ("google_drive_url", "ALTER TABLE insights ADD COLUMN google_drive_url TEXT"),
    ("salad_transcription_id", "ALTER TABLE insights ADD COLUMN salad_transcription_id TEXT"),
    ("openrouter_model_used", "ALTER TABLE insights ADD COLUMN openrouter_model_used TEXT"),
    ("processing_pipeline_version", "ALTER TABLE insights ADD COLUMN processing_pipeline_version TEXT")
]

for column_name, sql in alter_statements:
    try:
        cursor.execute(sql)
        print(f"  ✅ Added column: {column_name}")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print(f"  ℹ️  Column already exists: {column_name}")
        else:
            print(f"  ❌ Error adding {column_name}: {e}")

# 2. CREATE comprehensive transcripts table with ALL metadata
print("\n2. CREATING COMPREHENSIVE TRANSCRIPTS TABLE:")
print("-" * 40)

create_transcripts_sql = """
CREATE TABLE IF NOT EXISTS transcripts_complete (
    -- Primary identification
    recording_id TEXT PRIMARY KEY,
    ringcentral_id TEXT UNIQUE,

    -- Transcript data
    transcript_text TEXT NOT NULL,
    transcript_segments JSON,  -- Store speaker segments
    word_count INTEGER,
    confidence_score REAL,
    language TEXT DEFAULT 'en',

    -- Call metadata
    call_date DATE,
    call_time TIME,
    duration_seconds REAL,
    from_number TEXT,
    to_number TEXT,
    from_extension TEXT,
    to_extension TEXT,
    direction TEXT,  -- inbound/outbound

    -- Participants
    customer_name TEXT,
    customer_phone TEXT,
    customer_email TEXT,
    customer_company TEXT,
    employee_name TEXT,
    employee_id TEXT,
    employee_extension TEXT,
    employee_department TEXT,

    -- RingCentral metadata
    ringcentral_recording_url TEXT,
    ringcentral_account_id TEXT,
    ringcentral_session_id TEXT,
    ringcentral_recording_type TEXT,
    ringcentral_status TEXT,

    -- Processing metadata
    salad_job_id TEXT,
    salad_transcription_url TEXT,
    salad_processing_time REAL,
    openrouter_models_used JSON,  -- List of models used for different tasks
    processing_pipeline_version TEXT,

    -- Storage locations
    transcript_json_path TEXT,
    transcript_md_path TEXT,
    insights_json_path TEXT,
    google_drive_id TEXT,
    google_drive_url TEXT,

    -- AI insights reference
    has_ai_insights BOOLEAN DEFAULT 0,
    insights_generated_at TIMESTAMP,

    -- Complete metadata dump
    full_metadata JSON,  -- Complete JSON dump of all metadata

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes for searching
    CHECK (transcript_text IS NOT NULL AND transcript_text != '')
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_trans_date ON transcripts_complete(call_date);
CREATE INDEX IF NOT EXISTS idx_trans_customer ON transcripts_complete(customer_name);
CREATE INDEX IF NOT EXISTS idx_trans_employee ON transcripts_complete(employee_name);
CREATE INDEX IF NOT EXISTS idx_trans_phone ON transcripts_complete(customer_phone);
CREATE INDEX IF NOT EXISTS idx_trans_ringcentral ON transcripts_complete(ringcentral_id);
CREATE INDEX IF NOT EXISTS idx_trans_duration ON transcripts_complete(duration_seconds);

-- Full-text search preparation (SQLite doesn't have native FTS like PostgreSQL)
-- We'll create a virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    recording_id,
    transcript_text,
    customer_name,
    employee_name,
    content=transcripts_complete,
    content_rowid=rowid
);

-- Trigger to keep FTS updated
CREATE TRIGGER IF NOT EXISTS transcripts_fts_insert
AFTER INSERT ON transcripts_complete
BEGIN
    INSERT INTO transcripts_fts(recording_id, transcript_text, customer_name, employee_name)
    VALUES (new.recording_id, new.transcript_text, new.customer_name, new.employee_name);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_fts_update
AFTER UPDATE ON transcripts_complete
BEGIN
    UPDATE transcripts_fts
    SET transcript_text = new.transcript_text,
        customer_name = new.customer_name,
        employee_name = new.employee_name
    WHERE recording_id = old.recording_id;
END;
"""

try:
    cursor.executescript(create_transcripts_sql)
    conn.commit()
    print("  ✅ Comprehensive transcripts table created with full metadata support")
    print("  ✅ Full-text search enabled via FTS5")
except Exception as e:
    print(f"  ❌ Error creating transcripts table: {e}")

# 3. MIGRATE existing transcript data
print("\n3. MIGRATING EXISTING TRANSCRIPT DATA:")
print("-" * 40)

# Load existing transcripts from JSON files
transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
migrated_count = 0
error_count = 0

for year_dir in transcript_dir.glob('*'):
    if not year_dir.is_dir():
        continue
    for month_dir in year_dir.glob('*'):
        if not month_dir.is_dir():
            continue
        for day_dir in month_dir.glob('*'):
            if not day_dir.is_dir():
                continue
            for json_file in day_dir.glob('*.json'):
                try:
                    with open(json_file, 'r') as f:
                        data = json.load(f)

                    # Extract all metadata
                    recording_id = json_file.stem

                    # Check if already exists
                    cursor.execute("SELECT 1 FROM transcripts_complete WHERE recording_id = ?", (recording_id,))
                    if cursor.fetchone():
                        continue

                    # Insert with all available metadata
                    cursor.execute("""
                        INSERT INTO transcripts_complete (
                            recording_id,
                            transcript_text,
                            transcript_segments,
                            word_count,
                            confidence_score,
                            call_date,
                            duration_seconds,
                            customer_name,
                            employee_name,
                            transcript_json_path,
                            full_metadata,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        recording_id,
                        data.get('transcript', data.get('text', '')),
                        json.dumps(data.get('segments', [])),
                        data.get('word_count', 0),
                        data.get('confidence', 0),
                        data.get('metadata', {}).get('date'),
                        data.get('metadata', {}).get('duration'),
                        data.get('participants', {}).get('customer', {}).get('name'),
                        data.get('participants', {}).get('employee', {}).get('name'),
                        str(json_file),
                        json.dumps(data),
                    ))

                    migrated_count += 1

                except Exception as e:
                    print(f"  ⚠️  Error migrating {json_file.name}: {e}")
                    error_count += 1

conn.commit()
print(f"  ✅ Migrated {migrated_count} transcripts")
if error_count > 0:
    print(f"  ⚠️  {error_count} errors during migration")

# 4. CREATE metadata tracking table
print("\n4. CREATING METADATA TRACKING TABLE:")
print("-" * 40)

metadata_tracking_sql = """
CREATE TABLE IF NOT EXISTS metadata_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id TEXT NOT NULL,
    metadata_type TEXT NOT NULL,  -- 'ringcentral', 'salad', 'openrouter', 'google_drive'
    metadata_key TEXT NOT NULL,
    metadata_value TEXT,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (recording_id) REFERENCES transcripts_complete(recording_id)
);

CREATE INDEX IF NOT EXISTS idx_meta_recording ON metadata_tracking(recording_id);
CREATE INDEX IF NOT EXISTS idx_meta_type ON metadata_tracking(metadata_type);
"""

try:
    cursor.executescript(metadata_tracking_sql)
    conn.commit()
    print("  ✅ Metadata tracking table created")
except Exception as e:
    print(f"  ❌ Error creating metadata tracking: {e}")

# 5. VERIFY data integrity
print("\n5. DATA INTEGRITY CHECK:")
print("-" * 40)

# Count records in each table
cursor.execute("SELECT COUNT(*) FROM transcripts_complete")
transcript_count = cursor.fetchone()[0]
print(f"  📊 Total transcripts with metadata: {transcript_count}")

cursor.execute("SELECT COUNT(*) FROM transcripts_complete WHERE transcript_text IS NOT NULL AND transcript_text != ''")
with_text_count = cursor.fetchone()[0]
print(f"  📊 Transcripts with text content: {with_text_count}")

cursor.execute("SELECT COUNT(*) FROM transcripts_complete WHERE full_metadata IS NOT NULL")
with_metadata_count = cursor.fetchone()[0]
print(f"  📊 Transcripts with full metadata: {with_metadata_count}")

# 6. Sample queries to demonstrate capabilities
print("\n6. SAMPLE SEARCH CAPABILITIES:")
print("-" * 40)

print("""
Now you can run powerful queries like:

1. Full-text search across all transcripts:
   SELECT * FROM transcripts_fts WHERE transcript_text MATCH 'billing issue';

2. Find all calls for a customer with metadata:
   SELECT recording_id, call_date, duration_seconds, full_metadata
   FROM transcripts_complete
   WHERE customer_name LIKE '%John Smith%';

3. Aggregate analysis by employee:
   SELECT employee_name, COUNT(*) as calls, AVG(duration_seconds) as avg_duration
   FROM transcripts_complete
   WHERE call_date BETWEEN '2025-01-01' AND '2025-09-30'
   GROUP BY employee_name;

4. Find calls with specific metadata:
   SELECT * FROM metadata_tracking
   WHERE metadata_type = 'ringcentral' AND metadata_key = 'session_id';
""")

conn.close()

print("\n" + "=" * 80)
print("ENHANCEMENT COMPLETE!")
print("=" * 80)
print("""
✅ Database now stores:
   - Full transcript text
   - Complete call metadata
   - RingCentral metadata
   - Salad Cloud processing info
   - OpenRouter model tracking
   - Google Drive references
   - Participant information
   - Full-text search capability

Next steps:
1. Update processing pipeline to populate all metadata fields
2. Implement search API endpoints
3. Create dashboard views for metadata analytics
""")
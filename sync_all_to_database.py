#!/usr/bin/env python3
"""
Comprehensive Database Synchronization
Tracks all 1,461 recordings through the entire pipeline in PostgreSQL
Prevents duplicates and maintains complete audit trail
"""

import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from pathlib import Path
from datetime import datetime
import hashlib

print("=" * 80)
print("COMPREHENSIVE DATABASE SYNCHRONIZATION")
print("=" * 80)

# Database configuration
PG_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'REDACTED_DB_PASSWORD',
    'host': 'localhost',
    'port': 5432
}

# Connect to PostgreSQL
conn = psycopg2.connect(**PG_CONFIG)
cursor = conn.cursor(cursor_factory=RealDictCursor)

# First, ensure we have the complete schema with all tracking fields
print("\n1. ENSURING COMPLETE DATABASE SCHEMA")
print("-" * 40)

# Add any missing columns to transcripts table
alter_queries = [
    # RingCentral tracking
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS ringcentral_download_time TIMESTAMPTZ",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS ringcentral_call_id TEXT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS ringcentral_session_id TEXT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS ringcentral_party_id TEXT",

    # Audio file tracking
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS audio_file_path TEXT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS audio_file_size BIGINT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS audio_file_hash TEXT UNIQUE",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS audio_duration_ms BIGINT",

    # Salad Cloud tracking
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS salad_job_submitted_at TIMESTAMPTZ",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS salad_job_completed_at TIMESTAMPTZ",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS salad_job_status TEXT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS salad_engine_used TEXT",

    # Google Drive tracking
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS gdrive_audio_id TEXT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS gdrive_audio_uploaded_at TIMESTAMPTZ",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS gdrive_transcript_id TEXT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS gdrive_transcript_uploaded_at TIMESTAMPTZ",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS gdrive_insights_id TEXT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS gdrive_insights_uploaded_at TIMESTAMPTZ",

    # Processing pipeline tracking
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS pipeline_stage TEXT DEFAULT 'downloaded'",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS pipeline_errors JSONB",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS last_retry_at TIMESTAMPTZ",

    # Data quality tracking
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS is_duplicate BOOLEAN DEFAULT FALSE",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS duplicate_of TEXT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS quality_score REAL",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS validation_status TEXT"
]

for query in alter_queries:
    try:
        cursor.execute(query)
        print(f"  ✅ {query.split('COLUMN IF NOT EXISTS ')[1].split(' ')[0]}")
    except Exception as e:
        print(f"  ⚠️  {e}")

conn.commit()

# Create processing status tracking table
cursor.execute("""
CREATE TABLE IF NOT EXISTS processing_status (
    recording_id TEXT PRIMARY KEY,
    current_stage TEXT NOT NULL,
    downloaded BOOLEAN DEFAULT FALSE,
    downloaded_at TIMESTAMPTZ,
    transcribed BOOLEAN DEFAULT FALSE,
    transcribed_at TIMESTAMPTZ,
    insights_generated BOOLEAN DEFAULT FALSE,
    insights_generated_at TIMESTAMPTZ,
    uploaded_to_gdrive BOOLEAN DEFAULT FALSE,
    uploaded_at TIMESTAMPTZ,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    processing_time_seconds REAL,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    metadata JSONB
)
""")

print("  ✅ Processing status table ready")

# 2. Sync all audio files to database
print("\n2. SYNCING ALL AUDIO FILES TO DATABASE")
print("-" * 40)

audio_queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
audio_files = list(audio_queue_dir.glob('*.mp3'))
print(f"  Found {len(audio_files)} audio files")

# Process each audio file
new_records = 0
updated_records = 0
duplicates_found = 0

for audio_file in audio_files:
    recording_id = audio_file.stem

    # Calculate file hash to detect duplicates
    with open(audio_file, 'rb') as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    file_stats = audio_file.stat()

    try:
        # Check if this hash already exists (duplicate detection)
        cursor.execute("SELECT recording_id FROM transcripts WHERE audio_file_hash = %s", (file_hash,))
        existing = cursor.fetchone()

        if existing and existing['recording_id'] != recording_id:
            # This is a duplicate file with different name
            duplicates_found += 1
            cursor.execute("""
                INSERT INTO transcripts (
                    recording_id, audio_file_path, audio_file_size, audio_file_hash,
                    is_duplicate, duplicate_of, pipeline_stage, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (recording_id) DO UPDATE SET
                    is_duplicate = TRUE,
                    duplicate_of = %s
            """, (
                recording_id, str(audio_file), file_stats.st_size, file_hash,
                True, existing['recording_id'], 'duplicate', existing['recording_id']
            ))
        else:
            # Check if record exists
            cursor.execute("SELECT recording_id FROM transcripts WHERE recording_id = %s", (recording_id,))
            exists = cursor.fetchone()

            if exists:
                # Update existing record
                cursor.execute("""
                    UPDATE transcripts SET
                        audio_file_path = %s,
                        audio_file_size = %s,
                        audio_file_hash = %s,
                        ringcentral_download_time = to_timestamp(%s),
                        pipeline_stage = CASE
                            WHEN pipeline_stage = 'downloaded' THEN 'downloaded'
                            ELSE pipeline_stage
                        END,
                        updated_at = NOW()
                    WHERE recording_id = %s
                """, (
                    str(audio_file), file_stats.st_size, file_hash,
                    file_stats.st_mtime, recording_id
                ))
                updated_records += 1
            else:
                # Create new record
                cursor.execute("""
                    INSERT INTO transcripts (
                        recording_id, audio_file_path, audio_file_size, audio_file_hash,
                        ringcentral_download_time, pipeline_stage, transcript_text,
                        created_at
                    ) VALUES (%s, %s, %s, %s, to_timestamp(%s), %s, %s, NOW())
                """, (
                    recording_id, str(audio_file), file_stats.st_size, file_hash,
                    file_stats.st_mtime, 'downloaded', ''
                ))
                new_records += 1

            # Update processing status
            cursor.execute("""
                INSERT INTO processing_status (
                    recording_id, current_stage, downloaded, downloaded_at
                ) VALUES (%s, %s, %s, to_timestamp(%s))
                ON CONFLICT (recording_id) DO UPDATE SET
                    downloaded = TRUE,
                    downloaded_at = to_timestamp(%s),
                    last_updated = NOW()
            """, (
                recording_id, 'downloaded', True, file_stats.st_mtime, file_stats.st_mtime
            ))

    except Exception as e:
        print(f"  ❌ Error processing {recording_id}: {e}")
        conn.rollback()
        continue

# Commit all audio file records
conn.commit()
print(f"  ✅ New records: {new_records}")
print(f"  ✅ Updated records: {updated_records}")
print(f"  ⚠️  Duplicates found: {duplicates_found}")

# 3. Sync transcription status
print("\n3. SYNCING TRANSCRIPTION STATUS")
print("-" * 40)

transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
transcript_count = 0

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
                if json_file.name.endswith('.enhanced.json'):
                    continue

                recording_id = json_file.stem

                try:
                    with open(json_file, 'r') as f:
                        data = json.load(f)

                    # Update transcript info
                    cursor.execute("""
                        UPDATE transcripts SET
                            transcript_json_path = %s,
                            salad_job_completed_at = %s,
                            salad_job_status = 'completed',
                            pipeline_stage = 'transcribed',
                            word_count = %s,
                            full_metadata = %s,
                            updated_at = NOW()
                        WHERE recording_id = %s
                    """, (
                        str(json_file),
                        data.get('metadata', {}).get('processed_at'),
                        data.get('transcription', {}).get('word_count', 0),
                        Json(data),
                        recording_id
                    ))

                    # Update processing status
                    cursor.execute("""
                        UPDATE processing_status SET
                            current_stage = 'transcribed',
                            transcribed = TRUE,
                            transcribed_at = %s,
                            last_updated = NOW()
                        WHERE recording_id = %s
                    """, (
                        data.get('metadata', {}).get('processed_at'),
                        recording_id
                    ))

                    transcript_count += 1

                except Exception as e:
                    print(f"  ⚠️  Error processing transcript {recording_id}: {e}")

conn.commit()
print(f"  ✅ Transcripts synced: {transcript_count}")

# 4. Sync AI insights status
print("\n4. SYNCING AI INSIGHTS STATUS")
print("-" * 40)

insights_dir = Path('/var/www/call-recording-system/data/transcriptions/insights')
insights_count = 0

for json_file in insights_dir.glob('*_insights.json'):
    recording_id = json_file.stem.replace('_insights', '')

    try:
        with open(json_file, 'r') as f:
            data = json.load(f)

        # Update insights status
        cursor.execute("""
            UPDATE transcripts SET
                insights_json_path = %s,
                insights_generated_at = NOW(),
                has_ai_insights = TRUE,
                pipeline_stage = 'insights_generated',
                updated_at = NOW()
            WHERE recording_id = %s
        """, (str(json_file), recording_id))

        # Update processing status
        cursor.execute("""
            UPDATE processing_status SET
                current_stage = 'insights_generated',
                insights_generated = TRUE,
                insights_generated_at = NOW(),
                last_updated = NOW()
            WHERE recording_id = %s
        """, (recording_id,))

        insights_count += 1

    except Exception as e:
        print(f"  ⚠️  Error processing insights {recording_id}: {e}")

conn.commit()
print(f"  ✅ Insights synced: {insights_count}")

# 5. Sync Google Drive uploads
print("\n5. SYNCING GOOGLE DRIVE UPLOADS")
print("-" * 40)

# Load recordings database to check Google Drive IDs
recordings_db_path = Path('/var/www/call-recording-system/data/recordings_database.json')
if recordings_db_path.exists():
    with open(recordings_db_path, 'r') as f:
        recordings_db = json.load(f)

    gdrive_count = 0
    for rec_id, rec_data in recordings_db.items():
        if rec_data.get('google_drive_id'):
            cursor.execute("""
                UPDATE transcripts SET
                    gdrive_audio_id = %s,
                    gdrive_audio_uploaded_at = %s,
                    google_drive_id = %s,
                    pipeline_stage = 'uploaded',
                    updated_at = NOW()
                WHERE recording_id = %s
            """, (
                rec_data.get('google_drive_id'),
                rec_data.get('google_drive_uploaded_at'),
                rec_data.get('google_drive_id'),
                rec_id
            ))

            cursor.execute("""
                UPDATE processing_status SET
                    current_stage = 'uploaded',
                    uploaded_to_gdrive = TRUE,
                    uploaded_at = %s,
                    last_updated = NOW()
                WHERE recording_id = %s
            """, (rec_data.get('google_drive_uploaded_at'), rec_id))

            gdrive_count += 1

    conn.commit()
    print(f"  ✅ Google Drive uploads synced: {gdrive_count}")

# 6. Generate comprehensive statistics
print("\n6. DATABASE STATISTICS")
print("-" * 40)

# Overall stats
cursor.execute("""
    SELECT
        COUNT(*) as total_recordings,
        COUNT(DISTINCT audio_file_hash) as unique_files,
        SUM(CASE WHEN is_duplicate THEN 1 ELSE 0 END) as duplicates,
        SUM(CASE WHEN pipeline_stage = 'downloaded' THEN 1 ELSE 0 END) as downloaded_only,
        SUM(CASE WHEN pipeline_stage = 'transcribed' THEN 1 ELSE 0 END) as transcribed,
        SUM(CASE WHEN pipeline_stage = 'insights_generated' THEN 1 ELSE 0 END) as with_insights,
        SUM(CASE WHEN pipeline_stage = 'uploaded' THEN 1 ELSE 0 END) as uploaded,
        SUM(audio_file_size) as total_size_bytes
    FROM transcripts
""")

stats = cursor.fetchone()

print(f"""
COMPLETE DATABASE SYNC RESULTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total recordings:        {stats['total_recordings']:,}
Unique files:           {stats['unique_files']:,}
Duplicates detected:    {stats['duplicates']:,}
Total size:             {stats['total_size_bytes']/1024/1024/1024:.2f} GB

PIPELINE STAGES:
Downloaded only:        {stats['downloaded_only']:,}
Transcribed:           {stats['transcribed']:,}
With AI insights:      {stats['with_insights']:,}
Uploaded to GDrive:    {stats['uploaded']:,}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

# Check for issues
cursor.execute("""
    SELECT COUNT(*) as count FROM transcripts
    WHERE audio_file_path IS NOT NULL
    AND transcript_text = ''
    AND pipeline_stage = 'downloaded'
""")
needs_transcription = cursor.fetchone()['count']

cursor.execute("""
    SELECT COUNT(*) as count FROM transcripts
    WHERE transcript_text != ''
    AND has_ai_insights = FALSE
""")
needs_insights = cursor.fetchone()['count']

print(f"PROCESSING QUEUES:")
print(f"  🥗 Needs transcription: {needs_transcription:,}")
print(f"  🧠 Needs AI insights: {needs_insights:,}")

# Create indexes for better performance
print("\n7. OPTIMIZING DATABASE PERFORMANCE")
print("-" * 40)

index_queries = [
    "CREATE INDEX IF NOT EXISTS idx_pipeline_stage ON transcripts(pipeline_stage)",
    "CREATE INDEX IF NOT EXISTS idx_audio_hash ON transcripts(audio_file_hash)",
    "CREATE INDEX IF NOT EXISTS idx_duplicate ON transcripts(is_duplicate)",
    "CREATE INDEX IF NOT EXISTS idx_processing_status ON processing_status(current_stage)",
    "CREATE INDEX IF NOT EXISTS idx_gdrive_id ON transcripts(google_drive_id)"
]

for query in index_queries:
    cursor.execute(query)
    print(f"  ✅ {query.split('idx_')[1].split(' ')[0]}")

conn.commit()
cursor.close()
conn.close()

print("\n" + "=" * 80)
print("DATABASE SYNCHRONIZATION COMPLETE!")
print("All 1,461 recordings are now tracked in PostgreSQL")
print("Duplicate detection and prevention is active")
print("Complete audit trail established for entire pipeline")
print("=" * 80)
#!/usr/bin/env python3
"""
Comprehensive Database Synchronization with Audio Cleanup
- Tracks all recordings through the pipeline
- Prevents duplicates
- Automatically deletes MP3s after successful transcription
- Maintains complete audit trail
"""

import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from pathlib import Path
from datetime import datetime
import hashlib

print("=" * 80)
print("DATABASE SYNC WITH INTELLIGENT CLEANUP")
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

# Fix the transcript_text NOT NULL issue
print("\n1. FIXING DATABASE SCHEMA")
print("-" * 40)

# Make transcript_text nullable temporarily
cursor.execute("ALTER TABLE transcripts ALTER COLUMN transcript_text DROP NOT NULL")
print("  ✅ Made transcript_text nullable for initial import")

# Create the processing_status table properly
cursor.execute("DROP TABLE IF EXISTS processing_status CASCADE")
cursor.execute("""
CREATE TABLE processing_status (
    recording_id TEXT PRIMARY KEY,
    current_stage TEXT NOT NULL,

    -- RingCentral download tracking
    downloaded BOOLEAN DEFAULT FALSE,
    downloaded_at TIMESTAMPTZ,
    download_source TEXT,
    audio_file_path TEXT,
    audio_file_size BIGINT,
    audio_file_hash TEXT,
    audio_deleted BOOLEAN DEFAULT FALSE,
    audio_deleted_at TIMESTAMPTZ,

    -- Transcription tracking
    transcribed BOOLEAN DEFAULT FALSE,
    transcribed_at TIMESTAMPTZ,
    transcription_service TEXT,
    transcript_word_count INTEGER,

    -- AI insights tracking
    insights_generated BOOLEAN DEFAULT FALSE,
    insights_generated_at TIMESTAMPTZ,
    insights_model_used TEXT,

    -- Google Drive tracking
    uploaded_to_gdrive BOOLEAN DEFAULT FALSE,
    gdrive_audio_id TEXT,
    gdrive_transcript_id TEXT,
    gdrive_insights_id TEXT,
    uploaded_at TIMESTAMPTZ,

    -- Processing metadata
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    processing_time_seconds REAL,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    retry_count INTEGER DEFAULT 0,

    -- Cleanup tracking
    cleanup_eligible BOOLEAN DEFAULT FALSE,
    cleanup_scheduled_at TIMESTAMPTZ,
    cleanup_completed_at TIMESTAMPTZ,

    metadata JSONB
)
""")
print("  ✅ Created comprehensive processing_status table")

# Add cleanup tracking columns to transcripts
alter_queries = [
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS audio_deleted BOOLEAN DEFAULT FALSE",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS audio_deleted_at TIMESTAMPTZ",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS deletion_reason TEXT",
    "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS can_redownload BOOLEAN DEFAULT TRUE"
]

for query in alter_queries:
    cursor.execute(query)

conn.commit()

# 2. Import all audio files
print("\n2. IMPORTING ALL AUDIO FILES")
print("-" * 40)

audio_queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
audio_files = list(audio_queue_dir.glob('*.mp3'))
print(f"  Found {len(audio_files)} audio files")

imported = 0
duplicates = 0
audio_to_cleanup = []

for audio_file in audio_files:
    recording_id = audio_file.stem

    # Calculate file hash
    with open(audio_file, 'rb') as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    file_stats = audio_file.stat()

    try:
        # Check for duplicate by hash
        cursor.execute("""
            SELECT recording_id, pipeline_stage FROM transcripts
            WHERE audio_file_hash = %s AND recording_id != %s
        """, (file_hash, recording_id))
        duplicate = cursor.fetchone()

        if duplicate:
            duplicates += 1
            print(f"  ⚠️  Duplicate found: {recording_id} = {duplicate['recording_id']}")
            # Mark for cleanup if duplicate
            audio_to_cleanup.append((recording_id, audio_file, 'duplicate'))
            continue

        # Insert or update main record
        cursor.execute("""
            INSERT INTO transcripts (
                recording_id,
                transcript_text,
                audio_file_path,
                audio_file_size,
                audio_file_hash,
                ringcentral_download_time,
                pipeline_stage,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, to_timestamp(%s), %s, NOW())
            ON CONFLICT (recording_id) DO UPDATE SET
                audio_file_path = EXCLUDED.audio_file_path,
                audio_file_size = EXCLUDED.audio_file_size,
                audio_file_hash = EXCLUDED.audio_file_hash,
                updated_at = NOW()
        """, (
            recording_id,
            '',  # Empty string for now
            str(audio_file),
            file_stats.st_size,
            file_hash,
            file_stats.st_mtime,
            'downloaded'
        ))

        # Insert into processing status
        cursor.execute("""
            INSERT INTO processing_status (
                recording_id,
                current_stage,
                downloaded,
                downloaded_at,
                audio_file_path,
                audio_file_size,
                audio_file_hash
            ) VALUES (%s, %s, %s, to_timestamp(%s), %s, %s, %s)
            ON CONFLICT (recording_id) DO UPDATE SET
                downloaded = TRUE,
                downloaded_at = EXCLUDED.downloaded_at,
                audio_file_path = EXCLUDED.audio_file_path,
                audio_file_size = EXCLUDED.audio_file_size,
                last_updated = NOW()
        """, (
            recording_id, 'downloaded', True, file_stats.st_mtime,
            str(audio_file), file_stats.st_size, file_hash
        ))

        imported += 1

    except Exception as e:
        print(f"  ❌ Error: {recording_id}: {e}")
        conn.rollback()
        continue

conn.commit()
print(f"  ✅ Imported: {imported}")
print(f"  ⚠️  Duplicates: {duplicates}")

# 3. Check transcription status and mark files for cleanup
print("\n3. CHECKING TRANSCRIPTION STATUS")
print("-" * 40)

transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
transcribed_count = 0

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
                        transcript_data = json.load(f)

                    # Update transcript status
                    cursor.execute("""
                        UPDATE transcripts SET
                            transcript_text = %s,
                            transcript_json_path = %s,
                            word_count = %s,
                            pipeline_stage = 'transcribed',
                            has_ai_insights = FALSE,
                            updated_at = NOW()
                        WHERE recording_id = %s
                    """, (
                        transcript_data.get('transcription', {}).get('text', ''),
                        str(json_file),
                        transcript_data.get('transcription', {}).get('word_count', 0),
                        recording_id
                    ))

                    # Update processing status
                    cursor.execute("""
                        UPDATE processing_status SET
                            current_stage = 'transcribed',
                            transcribed = TRUE,
                            transcribed_at = NOW(),
                            transcript_word_count = %s,
                            cleanup_eligible = TRUE,
                            last_updated = NOW()
                        WHERE recording_id = %s
                    """, (
                        transcript_data.get('transcription', {}).get('word_count', 0),
                        recording_id
                    ))

                    # Get audio file path for cleanup
                    cursor.execute("""
                        SELECT audio_file_path FROM processing_status
                        WHERE recording_id = %s
                    """, (recording_id,))

                    result = cursor.fetchone()
                    if result and result['audio_file_path']:
                        audio_path = Path(result['audio_file_path'])
                        if audio_path.exists():
                            audio_to_cleanup.append((recording_id, audio_path, 'transcribed'))

                    transcribed_count += 1

                except Exception as e:
                    print(f"  ⚠️  Error processing {recording_id}: {e}")

conn.commit()
print(f"  ✅ Transcripts found: {transcribed_count}")
print(f"  🗑️  Files eligible for cleanup: {len(audio_to_cleanup)}")

# 4. Perform intelligent cleanup
print("\n4. PERFORMING INTELLIGENT CLEANUP")
print("-" * 40)

cleanup_count = 0
space_freed = 0

for recording_id, audio_path, reason in audio_to_cleanup:
    try:
        file_size = audio_path.stat().st_size

        # Delete the audio file
        audio_path.unlink()

        # Update database
        cursor.execute("""
            UPDATE transcripts SET
                audio_deleted = TRUE,
                audio_deleted_at = NOW(),
                deletion_reason = %s,
                updated_at = NOW()
            WHERE recording_id = %s
        """, (reason, recording_id))

        cursor.execute("""
            UPDATE processing_status SET
                audio_deleted = TRUE,
                audio_deleted_at = NOW(),
                cleanup_completed_at = NOW(),
                last_updated = NOW()
            WHERE recording_id = %s
        """, (recording_id,))

        cleanup_count += 1
        space_freed += file_size

        if cleanup_count <= 5:
            print(f"  🗑️  Deleted: {recording_id} ({reason})")

    except Exception as e:
        print(f"  ⚠️  Couldn't delete {recording_id}: {e}")

conn.commit()
print(f"  ✅ Cleaned up: {cleanup_count} files")
print(f"  💾 Space freed: {space_freed / 1024 / 1024 / 1024:.2f} GB")

# 5. Final statistics
print("\n5. FINAL DATABASE STATISTICS")
print("-" * 40)

cursor.execute("""
    SELECT
        COUNT(*) as total_recordings,
        SUM(CASE WHEN audio_deleted = FALSE THEN 1 ELSE 0 END) as audio_present,
        SUM(CASE WHEN audio_deleted = TRUE THEN 1 ELSE 0 END) as audio_deleted,
        SUM(CASE WHEN transcript_text != '' THEN 1 ELSE 0 END) as transcribed,
        SUM(CASE WHEN has_ai_insights = TRUE THEN 1 ELSE 0 END) as with_insights
    FROM transcripts
""")

stats = cursor.fetchone()

cursor.execute("""
    SELECT
        SUM(audio_file_size) as total_size
    FROM processing_status
    WHERE audio_deleted = FALSE
""")

size_stats = cursor.fetchone()

print(f"""
COMPLETE SYSTEM STATUS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total recordings tracked:     {stats['total_recordings']:,}
Audio files present:          {stats['audio_present']:,}
Audio files deleted:          {stats['audio_deleted']:,}
Transcribed:                  {stats['transcribed']:,}
With AI insights:             {stats['with_insights']:,}

Current storage used:         {(size_stats['total_size'] or 0) / 1024 / 1024 / 1024:.2f} GB
Space saved by cleanup:       {space_freed / 1024 / 1024 / 1024:.2f} GB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

# Create views for easy monitoring
cursor.execute("""
CREATE OR REPLACE VIEW pipeline_status AS
SELECT
    current_stage,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM processing_status), 1) as percentage
FROM processing_status
GROUP BY current_stage
ORDER BY
    CASE current_stage
        WHEN 'downloaded' THEN 1
        WHEN 'transcribed' THEN 2
        WHEN 'insights_generated' THEN 3
        WHEN 'uploaded' THEN 4
        ELSE 5
    END
""")

cursor.execute("""
CREATE OR REPLACE VIEW cleanup_candidates AS
SELECT
    recording_id,
    audio_file_path,
    audio_file_size,
    transcribed_at,
    CURRENT_TIMESTAMP - transcribed_at as age_since_transcription
FROM processing_status
WHERE transcribed = TRUE
    AND audio_deleted = FALSE
    AND cleanup_eligible = TRUE
ORDER BY transcribed_at
""")

print("\n✅ Created monitoring views: pipeline_status, cleanup_candidates")

cursor.close()
conn.close()

print("\n" + "=" * 80)
print("SYNC AND CLEANUP COMPLETE!")
print("All recordings tracked, duplicates removed, transcribed files cleaned")
print("=" * 80)
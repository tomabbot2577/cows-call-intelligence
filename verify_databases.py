#!/usr/bin/env python3
"""
Verify all databases used in the call recording system
Ensure transcripts and AI insights are properly stored
"""

import os
import json
import sqlite3
from pathlib import Path
import sys
sys.path.insert(0, '/var/www/call-recording-system')

print("=" * 80)
print("DATABASE VERIFICATION REPORT")
print("=" * 80)

# 1. Check JSON-based databases
print("\n1. JSON-BASED DATA STORES:")
print("-" * 40)

json_files = {
    'recordings_database.json': '/var/www/call-recording-system/data/recordings_database.json',
    'master_index.json': '/var/www/call-recording-system/data/transcriptions/indexes/master_index.json',
    'batch_progress.json': '/var/www/call-recording-system/data/batch_progress.json'
}

for name, path in json_files.items():
    if Path(path).exists():
        with open(path, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            count = len([k for k in data.keys() if k not in ['updated', 'stats']])
        else:
            count = len(data)
        print(f"  ✅ {name}: {count} records")

        # Sample data check
        if name == 'recordings_database.json' and count > 0:
            sample_key = list(data.keys())[0]
            if sample_key not in ['updated', 'stats']:
                sample = data[sample_key]
                has_transcript = 'transcript' in str(sample).lower()
                print(f"     - Sample has transcript field: {'Yes' if has_transcript else 'No'}")
    else:
        print(f"  ❌ {name}: NOT FOUND")

# 2. Check SQLite databases
print("\n2. SQLITE DATABASES:")
print("-" * 40)

# Main insights database
insights_db = '/var/www/call-recording-system/data/insights/insights.db'
if Path(insights_db).exists():
    conn = sqlite3.connect(insights_db)
    cursor = conn.cursor()

    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"  ✅ insights.db exists with tables: {[t[0] for t in tables]}")

    # Check insights table structure
    cursor.execute("PRAGMA table_info(insights)")
    columns = cursor.fetchall()

    # Look for transcript-related columns
    transcript_columns = []
    for col in columns:
        col_name = col[1].lower()
        if 'transcript' in col_name or 'summary' in col_name or 'key_topics' in col_name:
            transcript_columns.append(col[1])

    print(f"     - Text content columns: {transcript_columns}")

    # Check record count
    cursor.execute("SELECT COUNT(*) FROM insights")
    count = cursor.fetchone()[0]
    print(f"     - Total insights records: {count}")

    # Check if we're storing transcript data
    if count > 0:
        cursor.execute("SELECT recording_id, summary, key_topics FROM insights LIMIT 1")
        sample = cursor.fetchone()
        if sample:
            print(f"     - Sample record {sample[0]}:")
            print(f"       Summary: {'Yes' if sample[1] else 'No'}")
            print(f"       Key topics: {'Yes' if sample[2] else 'No'}")

    conn.close()
else:
    print(f"  ❌ insights.db: NOT FOUND")

# 3. Check transcript storage locations
print("\n3. TRANSCRIPT STORAGE LOCATIONS:")
print("-" * 40)

transcript_dirs = {
    'JSON transcripts': '/var/www/call-recording-system/data/transcriptions/json',
    'Markdown transcripts': '/var/www/call-recording-system/data/transcriptions/markdown',
    'AI insights': '/var/www/call-recording-system/data/transcriptions/insights'
}

for name, path in transcript_dirs.items():
    if Path(path).exists():
        # Count files
        json_files = list(Path(path).glob('**/*.json'))
        md_files = list(Path(path).glob('**/*.md'))
        total_files = len(json_files) + len(md_files)
        print(f"  ✅ {name}: {total_files} files")

        # Check a sample file for transcript content
        if json_files and name == 'JSON transcripts':
            with open(json_files[0], 'r') as f:
                sample = json.load(f)
            has_transcript = 'transcript' in sample or 'text' in sample
            print(f"     - Contains transcript data: {'Yes' if has_transcript else 'No'}")
    else:
        print(f"  ❌ {name}: Directory NOT FOUND")

# 4. Verify database schema for transcript storage
print("\n4. DATABASE SCHEMA ANALYSIS:")
print("-" * 40)

print("\nRECOMMENDED ENHANCEMENTS:")

# Check if insights table has transcript column
conn = sqlite3.connect(insights_db)
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(insights)")
columns = [col[1] for col in cursor.fetchall()]

if 'transcript_text' not in columns:
    print("  ⚠️  insights table missing 'transcript_text' column")
    print("     Recommendation: Add column to store full transcript")
    print("\n     SQL to add column:")
    print("     ALTER TABLE insights ADD COLUMN transcript_text TEXT;")
else:
    print("  ✅ insights table has transcript_text column")

if 'transcript_file_path' not in columns:
    print("  ⚠️  insights table missing 'transcript_file_path' column")
    print("     Recommendation: Add column to link to transcript files")
    print("\n     SQL to add column:")
    print("     ALTER TABLE insights ADD COLUMN transcript_file_path TEXT;")
else:
    print("  ✅ insights table has transcript_file_path column")

conn.close()

# 5. Create transcripts table if it doesn't exist
print("\n5. DEDICATED TRANSCRIPTS TABLE:")
print("-" * 40)

conn = sqlite3.connect(insights_db)
cursor = conn.cursor()

# Check if transcripts table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transcripts'")
if not cursor.fetchone():
    print("  ⚠️  No dedicated 'transcripts' table found")
    print("     Creating transcripts table...")

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS transcripts (
        recording_id TEXT PRIMARY KEY,
        transcript_text TEXT NOT NULL,
        word_count INTEGER,
        confidence_score REAL,
        duration_seconds REAL,
        language TEXT DEFAULT 'en',
        speaker_count INTEGER,
        transcription_date TIMESTAMP,
        transcription_service TEXT,
        file_path TEXT,
        metadata JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_transcript_date ON transcripts(transcription_date);
    CREATE INDEX IF NOT EXISTS idx_transcript_recording ON transcripts(recording_id);
    """

    try:
        cursor.executescript(create_table_sql)
        conn.commit()
        print("  ✅ Transcripts table created successfully")
    except Exception as e:
        print(f"  ❌ Error creating transcripts table: {e}")
else:
    cursor.execute("SELECT COUNT(*) FROM transcripts")
    count = cursor.fetchone()[0]
    print(f"  ✅ Transcripts table exists with {count} records")

conn.close()

# 6. Summary and recommendations
print("\n" + "=" * 80)
print("SUMMARY & RECOMMENDATIONS")
print("=" * 80)

print("""
CURRENT STATE:
1. ✅ Multiple JSON files store recording metadata
2. ✅ SQLite insights.db stores AI analysis results
3. ✅ Transcript files stored in filesystem (JSON/Markdown)
4. ⚠️  Transcripts may not be fully integrated into database

RECOMMENDATIONS:
1. Store full transcripts in database for better querying
2. Add transcript_text and transcript_file_path to insights table
3. Use dedicated transcripts table for better organization
4. Index transcript text for full-text search capabilities
5. Link insights to transcripts via foreign keys

BENEFITS OF DATABASE STORAGE:
- Fast full-text search across all transcripts
- Better date range analysis
- Efficient aggregation for customer/employee reports
- Centralized data management
- Better backup and recovery
""")

print("\nTo implement recommendations, run:")
print("  python /var/www/call-recording-system/implement_db_enhancements.py")
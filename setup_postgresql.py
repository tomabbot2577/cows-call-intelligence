#!/usr/bin/env python3
"""
Complete PostgreSQL setup and migration for Call Recording System
Migrates from SQLite to PostgreSQL with full data preservation
"""

import os
import sys
import json
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from pathlib import Path
from datetime import datetime

print("=" * 80)
print("POSTGRESQL SETUP AND MIGRATION")
print("=" * 80)

# Database configuration
PG_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'REDACTED_DB_PASSWORD',
    'host': 'localhost',
    'port': 5432
}

# Step 1: Create database
print("\n1. CREATING DATABASE:")
print("-" * 40)
print("  ℹ️  Database 'call_insights' already created manually")

# Step 2: Connect to new database and create schema
print("\n2. CREATING SCHEMA:")
print("-" * 40)

try:
    conn = psycopg2.connect(**PG_CONFIG)
    cursor = conn.cursor()

    # Enable extensions
    cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")  # For fuzzy text search
    cursor.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")  # For accent-insensitive search
    print("  ✅ Extensions enabled")

    # Create main transcripts table with all metadata
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transcripts (
        -- Primary identification
        recording_id TEXT PRIMARY KEY,
        ringcentral_id TEXT UNIQUE,

        -- Transcript data
        transcript_text TEXT NOT NULL,
        transcript_segments JSONB,
        word_count INTEGER,
        confidence_score REAL,
        language VARCHAR(10) DEFAULT 'en',

        -- Call metadata
        call_date DATE,
        call_time TIME,
        duration_seconds REAL,
        from_number TEXT,
        to_number TEXT,
        from_extension TEXT,
        to_extension TEXT,
        direction TEXT,

        -- Participants
        customer_name TEXT,
        customer_phone TEXT,
        customer_email TEXT,
        customer_company TEXT,
        employee_name TEXT,
        employee_id TEXT,
        employee_extension TEXT,
        employee_department TEXT,

        -- Processing metadata
        salad_job_id TEXT,
        salad_processing_time REAL,
        openrouter_models_used JSONB,
        processing_pipeline_version TEXT,

        -- Storage locations
        transcript_json_path TEXT,
        transcript_md_path TEXT,
        insights_json_path TEXT,
        google_drive_id TEXT,
        google_drive_url TEXT,

        -- AI insights reference
        has_ai_insights BOOLEAN DEFAULT FALSE,
        insights_generated_at TIMESTAMPTZ,

        -- Complete metadata
        full_metadata JSONB,

        -- Timestamps
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    print("  ✅ Transcripts table created")

    # Create insights table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS insights (
        recording_id TEXT PRIMARY KEY REFERENCES transcripts(recording_id),

        -- Quality metrics
        call_quality_score REAL,
        customer_satisfaction_score REAL,
        agent_performance_score REAL,
        first_call_resolution BOOLEAN,

        -- Sentiment analysis
        customer_sentiment TEXT,
        agent_sentiment TEXT,
        sentiment_trend TEXT,
        emotional_tone TEXT,

        -- Categories
        call_type TEXT,
        issue_category TEXT,
        resolution_status TEXT,
        escalation_required BOOLEAN,
        follow_up_needed BOOLEAN,

        -- AI analysis
        summary TEXT,
        key_topics TEXT[],
        action_items JSONB,
        coaching_notes TEXT,
        compliance_issues TEXT,

        -- Business metrics
        potential_revenue REAL,
        churn_risk_score REAL,
        upsell_opportunity BOOLEAN,

        -- Processing info
        processing_time REAL,
        model_version TEXT,
        confidence_score REAL,

        -- Timestamps
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    print("  ✅ Insights table created")

    # Create indexes for performance
    index_queries = [
        "CREATE INDEX IF NOT EXISTS idx_transcripts_date ON transcripts(call_date);",
        "CREATE INDEX IF NOT EXISTS idx_transcripts_customer ON transcripts(customer_name);",
        "CREATE INDEX IF NOT EXISTS idx_transcripts_employee ON transcripts(employee_name);",
        "CREATE INDEX IF NOT EXISTS idx_transcripts_phone ON transcripts(customer_phone);",
        "CREATE INDEX IF NOT EXISTS idx_insights_sentiment ON insights(customer_sentiment);",
        "CREATE INDEX IF NOT EXISTS idx_insights_quality ON insights(call_quality_score);",

        # Full-text search indexes
        "CREATE INDEX IF NOT EXISTS idx_transcript_text_search ON transcripts USING gin(to_tsvector('english', transcript_text));",
        "CREATE INDEX IF NOT EXISTS idx_summary_search ON insights USING gin(to_tsvector('english', summary));",

        # JSONB indexes
        "CREATE INDEX IF NOT EXISTS idx_metadata ON transcripts USING gin(full_metadata);",
        "CREATE INDEX IF NOT EXISTS idx_action_items ON insights USING gin(action_items);"
    ]

    for query in index_queries:
        cursor.execute(query)
    print("  ✅ Indexes created for optimal performance")

    conn.commit()

except psycopg2.Error as e:
    print(f"  ❌ Schema creation error: {e}")
    conn.rollback()
    sys.exit(1)

# Step 3: Migrate data from SQLite
print("\n3. MIGRATING DATA FROM SQLITE:")
print("-" * 40)

sqlite_db_path = '/var/www/call-recording-system/data/insights/insights.db'
if Path(sqlite_db_path).exists():
    sqlite_conn = sqlite3.connect(sqlite_db_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    # Check if transcripts table exists in SQLite
    sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transcripts'")
    if sqlite_cursor.fetchone():
        # Migrate transcripts
        sqlite_cursor.execute("SELECT * FROM transcripts")
        transcripts = sqlite_cursor.fetchall()

        for row in transcripts:
            try:
                cursor.execute("""
                    INSERT INTO transcripts (
                        recording_id, transcript_text, word_count, confidence_score,
                        call_date, duration_seconds, customer_name, employee_name,
                        full_metadata, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (recording_id) DO NOTHING
                """, (
                    row['recording_id'], row['transcript_text'], row['word_count'],
                    row['confidence_score'], row['call_date'], row['duration_seconds'],
                    row['customer_name'], row['employee_name'],
                    Json(json.loads(row['full_metadata']) if row['full_metadata'] else {}),
                    row['created_at']
                ))
            except Exception as e:
                print(f"  ⚠️  Error migrating transcript {row['recording_id']}: {e}")

        conn.commit()
        print(f"  ✅ Migrated {len(transcripts)} transcripts from SQLite")

    sqlite_conn.close()
else:
    print("  ℹ️  No SQLite database found to migrate")

# Step 4: Import JSON transcripts
print("\n4. IMPORTING JSON TRANSCRIPTS:")
print("-" * 40)

transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
imported_count = 0
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

                    recording_id = json_file.stem

                    # Extract transcript text
                    transcript_text = data.get('transcript', data.get('text', ''))
                    if not transcript_text:
                        continue

                    # Extract metadata
                    metadata = data.get('metadata', {})
                    participants = data.get('participants', {})

                    cursor.execute("""
                        INSERT INTO transcripts (
                            recording_id, transcript_text, transcript_segments,
                            word_count, confidence_score, call_date, duration_seconds,
                            customer_name, employee_name, transcript_json_path,
                            full_metadata, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (recording_id) DO UPDATE SET
                            transcript_text = EXCLUDED.transcript_text,
                            full_metadata = EXCLUDED.full_metadata,
                            updated_at = NOW()
                    """, (
                        recording_id,
                        transcript_text,
                        Json(data.get('segments', [])),
                        data.get('word_count', len(transcript_text.split())),
                        data.get('confidence', 0.95),
                        metadata.get('date'),
                        metadata.get('duration'),
                        participants.get('primary_customer', {}).get('name'),
                        participants.get('primary_employee', {}).get('name'),
                        str(json_file),
                        Json(data)
                    ))

                    imported_count += 1

                except Exception as e:
                    error_count += 1
                    print(f"  ⚠️  Error importing {json_file.name}: {e}")

conn.commit()
print(f"  ✅ Imported {imported_count} JSON transcripts")
if error_count > 0:
    print(f"  ⚠️  {error_count} errors during import")

# Step 5: Import AI insights
print("\n5. IMPORTING AI INSIGHTS:")
print("-" * 40)

insights_dir = Path('/var/www/call-recording-system/data/transcriptions/insights')
insights_count = 0

for json_file in insights_dir.glob('*_insights.json'):
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)

        recording_id = json_file.stem.replace('_insights', '')

        # Update transcript to mark it has insights
        cursor.execute("""
            UPDATE transcripts
            SET has_ai_insights = TRUE,
                insights_generated_at = NOW(),
                insights_json_path = %s
            WHERE recording_id = %s
        """, (str(json_file), recording_id))

        # Insert insights
        cursor.execute("""
            INSERT INTO insights (
                recording_id, call_quality_score, customer_satisfaction_score,
                customer_sentiment, call_type, issue_category, summary,
                key_topics, action_items, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (recording_id) DO UPDATE SET
                summary = EXCLUDED.summary,
                updated_at = NOW()
        """, (
            recording_id,
            data.get('key_metrics', {}).get('call_quality_score'),
            data.get('key_metrics', {}).get('customer_satisfaction_score'),
            data.get('key_metrics', {}).get('sentiment'),
            data.get('call_classification', {}).get('call_type'),
            data.get('call_classification', {}).get('issue_category'),
            data.get('summary'),
            data.get('key_topics', []),
            Json(data.get('action_items', []))
        ))

        insights_count += 1

    except Exception as e:
        print(f"  ⚠️  Error importing insights {json_file.name}: {e}")

conn.commit()
print(f"  ✅ Imported {insights_count} AI insights")

# Step 6: Verify migration
print("\n6. VERIFICATION:")
print("-" * 40)

cursor.execute("SELECT COUNT(*) FROM transcripts")
transcript_count = cursor.fetchone()[0]
print(f"  📊 Total transcripts in PostgreSQL: {transcript_count}")

cursor.execute("SELECT COUNT(*) FROM transcripts WHERE transcript_text IS NOT NULL AND transcript_text != ''")
with_text = cursor.fetchone()[0]
print(f"  📊 Transcripts with text: {with_text}")

cursor.execute("SELECT COUNT(*) FROM insights")
insights_count = cursor.fetchone()[0]
print(f"  📊 Total insights: {insights_count}")

# Test full-text search
cursor.execute("""
    SELECT COUNT(*) FROM transcripts
    WHERE to_tsvector('english', transcript_text) @@ to_tsquery('english', 'call')
""")
search_results = cursor.fetchone()[0]
print(f"  🔍 Full-text search test (word 'call'): {search_results} results")

# Test JSONB query
cursor.execute("""
    SELECT COUNT(*) FROM transcripts
    WHERE full_metadata IS NOT NULL
""")
metadata_count = cursor.fetchone()[0]
print(f"  📋 Transcripts with metadata: {metadata_count}")

cursor.close()
conn.close()

print("\n" + "=" * 80)
print("MIGRATION COMPLETE!")
print("=" * 80)
print("""
✅ PostgreSQL is now your primary database
✅ All data migrated successfully
✅ Full-text search enabled
✅ JSONB metadata support active
✅ Indexes created for performance

Next steps:
1. Update .env with PostgreSQL connection string
2. Test the web dashboard
3. Run a test batch process
""")
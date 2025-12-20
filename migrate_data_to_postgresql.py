#!/usr/bin/env python3
"""
Import all transcript and insight data into PostgreSQL
Handles the actual data format from our processing pipeline
"""

import os
import sys
import json
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from pathlib import Path
from datetime import datetime

print("=" * 80)
print("DATA MIGRATION TO POSTGRESQL")
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
cursor = conn.cursor()

# Import transcript files
print("\nIMPORTING TRANSCRIPTS:")
print("-" * 40)

transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
imported_count = 0
error_count = 0

# Find all JSON files (excluding .enhanced.json files)
json_files = [f for f in transcript_dir.glob('**/*.json') if not f.name.endswith('.enhanced.json')]

for json_file in json_files:
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)

        recording_id = data.get('recording_id', json_file.stem)

        # Extract transcript text from different possible locations
        transcript_text = None
        if 'transcription' in data and isinstance(data['transcription'], dict):
            transcript_text = data['transcription'].get('text', '')
        elif 'transcript' in data:
            transcript_text = data['transcript']
        elif 'text' in data:
            transcript_text = data['text']

        if not transcript_text:
            print(f"  ⚠️  No transcript text found in {json_file.name}")
            continue

        # Extract metadata
        call_metadata = data.get('call_metadata', {})
        transcription = data.get('transcription', {})

        # Extract participant info
        participants = call_metadata.get('participants', {})
        customer_info = participants.get('primary_customer', {})
        employee_info = participants.get('primary_employee', {})

        # Insert transcript
        cursor.execute("""
            INSERT INTO transcripts (
                recording_id,
                transcript_text,
                transcript_segments,
                word_count,
                confidence_score,
                call_date,
                call_time,
                duration_seconds,
                from_number,
                to_number,
                customer_name,
                customer_phone,
                customer_company,
                employee_name,
                employee_id,
                employee_extension,
                employee_department,
                transcript_json_path,
                full_metadata,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT (recording_id) DO UPDATE SET
                transcript_text = EXCLUDED.transcript_text,
                full_metadata = EXCLUDED.full_metadata,
                updated_at = NOW()
        """, (
            recording_id,
            transcript_text,
            Json(transcription.get('segments', [])),
            transcription.get('word_count', len(transcript_text.split())),
            transcription.get('confidence', 0.95),
            call_metadata.get('date'),
            call_metadata.get('time'),
            call_metadata.get('duration'),
            call_metadata.get('from_number'),
            call_metadata.get('to_number'),
            customer_info.get('name'),
            customer_info.get('phone'),
            customer_info.get('company'),
            employee_info.get('name'),
            employee_info.get('employee_id'),
            employee_info.get('extension'),
            employee_info.get('department'),
            str(json_file),
            Json(data)
        ))

        imported_count += 1
        print(f"  ✅ Imported: {recording_id}")

    except Exception as e:
        error_count += 1
        print(f"  ❌ Error with {json_file.name}: {e}")
        conn.rollback()
        continue

conn.commit()
print(f"\n  📊 Total imported: {imported_count}")
if error_count > 0:
    print(f"  ⚠️  Errors: {error_count}")

# Import AI insights
print("\nIMPORTING AI INSIGHTS:")
print("-" * 40)

insights_dir = Path('/var/www/call-recording-system/data/transcriptions/insights')
insights_count = 0
insights_errors = 0

for json_file in insights_dir.glob('*_insights.json'):
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)

        recording_id = json_file.stem.replace('_insights', '')

        # Check if transcript exists first
        cursor.execute("SELECT 1 FROM transcripts WHERE recording_id = %s", (recording_id,))
        if not cursor.fetchone():
            print(f"  ⚠️  No transcript for insights: {recording_id}")
            # Create minimal transcript entry
            cursor.execute("""
                INSERT INTO transcripts (recording_id, transcript_text, created_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (recording_id) DO NOTHING
            """, (recording_id, 'Transcript not available'))

        # Extract key metrics
        key_metrics = data.get('key_metrics', {})
        call_classification = data.get('call_classification', {})

        # Insert insights
        cursor.execute("""
            INSERT INTO insights (
                recording_id,
                call_quality_score,
                customer_satisfaction_score,
                customer_sentiment,
                call_type,
                issue_category,
                resolution_status,
                escalation_required,
                follow_up_needed,
                summary,
                key_topics,
                action_items,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT (recording_id) DO UPDATE SET
                summary = EXCLUDED.summary,
                key_topics = EXCLUDED.key_topics,
                updated_at = NOW()
        """, (
            recording_id,
            key_metrics.get('call_quality_score'),
            key_metrics.get('customer_satisfaction_score'),
            key_metrics.get('sentiment', key_metrics.get('customer_sentiment')),
            call_classification.get('call_type'),
            call_classification.get('issue_category'),
            call_classification.get('outcome_status'),
            key_metrics.get('escalation_risk') == 'high',
            call_classification.get('follow_up_required', False),
            data.get('summary', ''),
            data.get('key_topics', []),
            Json(data.get('action_items', []))
        ))

        # Update transcript to mark it has insights
        cursor.execute("""
            UPDATE transcripts
            SET has_ai_insights = TRUE,
                insights_generated_at = NOW(),
                insights_json_path = %s
            WHERE recording_id = %s
        """, (str(json_file), recording_id))

        insights_count += 1
        print(f"  ✅ Imported insights: {recording_id}")

    except Exception as e:
        insights_errors += 1
        print(f"  ❌ Error with insights {json_file.name}: {e}")
        conn.rollback()
        continue

conn.commit()
print(f"\n  📊 Total insights: {insights_count}")
if insights_errors > 0:
    print(f"  ⚠️  Errors: {insights_errors}")

# Verification
print("\nVERIFICATION:")
print("-" * 40)

cursor.execute("SELECT COUNT(*) FROM transcripts")
transcript_count = cursor.fetchone()[0]
print(f"  📊 Total transcripts: {transcript_count}")

cursor.execute("SELECT COUNT(*) FROM transcripts WHERE transcript_text IS NOT NULL AND transcript_text != ''")
with_text = cursor.fetchone()[0]
print(f"  📊 Transcripts with text: {with_text}")

cursor.execute("SELECT COUNT(*) FROM insights")
insights_total = cursor.fetchone()[0]
print(f"  📊 Total insights: {insights_total}")

# Test search capabilities
cursor.execute("""
    SELECT COUNT(*) FROM transcripts
    WHERE to_tsvector('english', transcript_text) @@ to_tsquery('english', 'call | customer | support')
""")
search_test = cursor.fetchone()[0]
print(f"  🔍 Full-text search test: {search_test} results")

# Sample data
cursor.execute("""
    SELECT recording_id,
           substring(transcript_text, 1, 100) as sample_text,
           customer_name,
           employee_name
    FROM transcripts
    WHERE transcript_text IS NOT NULL
    LIMIT 3
""")
samples = cursor.fetchall()

if samples:
    print("\n  📝 Sample records:")
    for sample in samples:
        print(f"     ID: {sample[0]}")
        print(f"     Customer: {sample[2]}")
        print(f"     Employee: {sample[3]}")
        print(f"     Text: {sample[1]}...")
        print()

cursor.close()
conn.close()

print("=" * 80)
print("MIGRATION COMPLETE!")
print("=" * 80)
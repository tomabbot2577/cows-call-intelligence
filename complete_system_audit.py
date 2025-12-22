#!/usr/bin/env python3
"""
Complete system audit to find all recordings and their processing status
"""

import json
import os
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor

print("=" * 80)
print("COMPLETE SYSTEM AUDIT - CALL RECORDING SYSTEM")
print("=" * 80)

# 1. Count all audio files
print("\n📞 AUDIO FILES:")
print("-" * 40)

audio_queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
audio_files = list(audio_queue_dir.glob('*.mp3'))
print(f"  Total MP3 files in audio_queue: {len(audio_files)}")

# Get size
total_size = sum(f.stat().st_size for f in audio_files)
print(f"  Total size: {total_size / (1024**3):.2f} GB")

# Sample files
print("\n  Sample recordings:")
for f in sorted(audio_files)[:5]:
    print(f"    - {f.name} ({f.stat().st_size / (1024**2):.1f} MB)")

# 2. Check recordings database
print("\n📊 RECORDINGS DATABASE:")
print("-" * 40)

recordings_db = Path('/var/www/call-recording-system/data/recordings_database.json')
if recordings_db.exists():
    with open(recordings_db, 'r') as f:
        recordings = json.load(f)

    print(f"  Records in recordings_database.json: {len(recordings)}")

    # Count statuses
    statuses = {}
    for rec in recordings.values():
        status = rec.get('status', 'unknown')
        statuses[status] = statuses.get(status, 0) + 1

    for status, count in statuses.items():
        print(f"    - {status}: {count}")
else:
    print("  ⚠️  recordings_database.json not found")
    recordings = {}

# 3. Count transcriptions
print("\n📝 TRANSCRIPTIONS:")
print("-" * 40)

transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
transcript_files = []
for year_dir in transcript_dir.glob('*'):
    if year_dir.is_dir():
        for month_dir in year_dir.glob('*'):
            if month_dir.is_dir():
                for day_dir in month_dir.glob('*'):
                    if day_dir.is_dir():
                        transcript_files.extend(day_dir.glob('*.json'))

# Filter out enhanced files
transcript_files = [f for f in transcript_files if not f.name.endswith('.enhanced.json')]
print(f"  Total transcript JSON files: {len(transcript_files)}")

# Get recording IDs from transcripts
transcribed_ids = set(f.stem for f in transcript_files)
print(f"  Unique recordings transcribed: {len(transcribed_ids)}")

# 4. Count AI insights
print("\n🧠 AI INSIGHTS:")
print("-" * 40)

insights_dir = Path('/var/www/call-recording-system/data/transcriptions/insights')
insights_files = list(insights_dir.glob('*_insights.json'))
print(f"  Total insights files: {len(insights_files)}")

insights_ids = set(f.stem.replace('_insights', '') for f in insights_files)

# 5. PostgreSQL status
print("\n🗄️  POSTGRESQL DATABASE:")
print("-" * 40)

try:
    conn = psycopg2.connect(
        dbname='call_insights',
        user='call_insights_user',
        password=os.getenv('PG_PASSWORD', ''),
        host='localhost',
        cursor_factory=RealDictCursor
    )
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM transcripts")
    db_transcripts = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM insights")
    db_insights = cursor.fetchone()['count']

    print(f"  Transcripts in PostgreSQL: {db_transcripts}")
    print(f"  Insights in PostgreSQL: {db_insights}")

    cursor.close()
    conn.close()
except Exception as e:
    print(f"  ⚠️  Database error: {e}")

# 6. COMPREHENSIVE QUEUE ANALYSIS
print("\n" + "=" * 80)
print("COMPREHENSIVE QUEUE ANALYSIS")
print("=" * 80)

# Get all audio file IDs
audio_ids = set(f.stem for f in audio_files)
print(f"\n📊 TOTAL RECORDINGS FOUND: {len(audio_ids)}")

# Calculate processing stages
recordings_in_db = set(recordings.keys())
not_in_db = audio_ids - recordings_in_db

print(f"\n📈 PROCESSING STAGES:")
print(f"  1. Audio files downloaded: {len(audio_ids)}")
print(f"  2. Tracked in database: {len(recordings_in_db)}")
print(f"  3. Not tracked in database: {len(not_in_db)}")
print(f"  4. Transcribed (Salad Cloud): {len(transcribed_ids)}")
print(f"  5. AI Insights generated: {len(insights_ids)}")

# Calculate queues
print(f"\n📋 CURRENT QUEUES:")

# Transcription queue
needs_transcription = audio_ids - transcribed_ids
print(f"  🥗 Awaiting Salad Cloud transcription: {len(needs_transcription)}")
if len(needs_transcription) > 0:
    print(f"     First 5 in queue:")
    for rec_id in sorted(needs_transcription)[:5]:
        print(f"       - {rec_id}")

# AI insights queue
needs_insights = transcribed_ids - insights_ids
print(f"\n  🧠 Awaiting OpenRouter AI insights: {len(needs_insights)}")
if len(needs_insights) > 0:
    print(f"     First 5 in queue:")
    for rec_id in sorted(needs_insights)[:5]:
        print(f"       - {rec_id}")

# 7. SUMMARY
print("\n" + "=" * 80)
print("EXECUTIVE SUMMARY")
print("=" * 80)

completion_rate = (len(insights_ids) / len(audio_ids) * 100) if len(audio_ids) > 0 else 0

print(f"""
TOTAL RECORDINGS: {len(audio_ids):,}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stage                          Completed    Remaining
────────────────────────────────────────────────
Downloaded from RingCentral:   {len(audio_ids):>10,}   {0:>10}
Transcribed by Salad Cloud:    {len(transcribed_ids):>10,}   {len(needs_transcription):>10,}
AI Insights by OpenRouter:     {len(insights_ids):>10,}   {len(needs_insights):>10,}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COMPLETION RATE: {completion_rate:.1f}%

CRITICAL ISSUES:
""")

if len(not_in_db) > 0:
    print(f"  ⚠️  {len(not_in_db):,} recordings not tracked in database")
    print(f"     → Need to update recordings_database.json")

if len(needs_transcription) > 1000:
    print(f"  ⚠️  {len(needs_transcription):,} recordings waiting for transcription")
    print(f"     → Need to process through Salad Cloud API")

if len(needs_insights) > 100:
    print(f"  ⚠️  {len(needs_insights):,} transcripts waiting for AI insights")
    print(f"     → Need to run batch processor with OpenRouter")

print("\n" + "=" * 80)
#!/usr/bin/env python3
"""
Check detailed queue status for each processing stage
"""

import json
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor

print("=" * 80)
print("DETAILED QUEUE STATUS REPORT")
print("=" * 80)

# 1. RingCentral Downloads
print("\n📞 RINGCENTRAL DOWNLOADS:")
print("-" * 40)

recordings_db = Path('/var/www/call-recording-system/data/recordings_database.json')
if recordings_db.exists():
    with open(recordings_db, 'r') as f:
        recordings = json.load(f)

    total_recordings = len(recordings)
    completed = [r for r in recordings.values() if r.get('status') == 'completed']
    failed = [r for r in recordings.values() if r.get('status') == 'failed']

    print(f"  Total recordings downloaded: {total_recordings}")
    print(f"  ✅ Successfully completed: {len(completed)}")
    print(f"  ❌ Failed downloads: {len(failed)}")

    # Show failed recordings
    if failed:
        print("\n  Failed recordings:")
        for rec in failed[:5]:
            print(f"    - {rec['recording_id']}: {rec.get('error_message', 'Unknown error')}")

# 2. Transcription Queue (waiting for Salad Cloud)
print("\n🥗 TRANSCRIPTION QUEUE (Salad Cloud):")
print("-" * 40)

# Check which recordings have been transcribed
transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
transcribed_ids = set()

for json_file in transcript_dir.glob('**/*.json'):
    if not json_file.name.endswith('.enhanced.json'):
        transcribed_ids.add(json_file.stem)

# Compare with total recordings
recordings_needing_transcription = []
for rec_id in recordings.keys():
    if rec_id not in transcribed_ids and recordings[rec_id].get('status') == 'completed':
        recordings_needing_transcription.append(rec_id)

print(f"  Total transcripts completed: {len(transcribed_ids)}")
print(f"  Recordings awaiting transcription: {len(recordings_needing_transcription)}")

if recordings_needing_transcription:
    print("\n  Recordings in transcription queue:")
    for rec_id in recordings_needing_transcription[:10]:
        print(f"    - {rec_id}")

# 3. AI Insights Queue (waiting for OpenRouter LLMs)
print("\n🧠 AI INSIGHTS QUEUE (OpenRouter):")
print("-" * 40)

# Check which transcripts have insights
insights_dir = Path('/var/www/call-recording-system/data/transcriptions/insights')
insights_ids = set()

for json_file in insights_dir.glob('*_insights.json'):
    insights_ids.add(json_file.stem.replace('_insights', ''))

# Transcripts needing insights
transcripts_needing_insights = transcribed_ids - insights_ids

print(f"  Total AI insights generated: {len(insights_ids)}")
print(f"  Transcripts awaiting AI insights: {len(transcripts_needing_insights)}")

if transcripts_needing_insights:
    print("\n  Transcripts in AI insights queue:")
    for rec_id in sorted(transcripts_needing_insights)[:10]:
        print(f"    - {rec_id}")

# 4. Google Drive Upload Queue
print("\n☁️  GOOGLE DRIVE UPLOAD QUEUE:")
print("-" * 40)

recordings_with_gdrive = [r for r in recordings.values() if r.get('google_drive_id')]
recordings_without_gdrive = [r for r in recordings.values() if r.get('status') == 'completed' and not r.get('google_drive_id')]

print(f"  Total uploaded to Google Drive: {len(recordings_with_gdrive)}")
print(f"  Awaiting Google Drive upload: {len(recordings_without_gdrive)}")

if recordings_without_gdrive:
    print("\n  Recordings awaiting upload:")
    for rec in recordings_without_gdrive[:10]:
        print(f"    - {rec['recording_id']}")

# 5. Database sync status
print("\n🗄️  DATABASE SYNC STATUS:")
print("-" * 40)

try:
    conn = psycopg2.connect(
        dbname='call_insights',
        user='call_insights_user',
        password='call_insights_pass',
        host='localhost',
        cursor_factory=RealDictCursor
    )
    cursor = conn.cursor()

    # Count database entries
    cursor.execute("SELECT COUNT(*) as count FROM transcripts")
    db_transcripts = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM insights")
    db_insights = cursor.fetchone()['count']

    print(f"  Transcripts in PostgreSQL: {db_transcripts}")
    print(f"  Insights in PostgreSQL: {db_insights}")
    print(f"  Database sync status: {'✅ Up to date' if db_transcripts == len(transcribed_ids) else '⚠️ Needs sync'}")

    cursor.close()
    conn.close()
except Exception as e:
    print(f"  ⚠️ Database error: {e}")

# 6. Processing Summary
print("\n" + "=" * 80)
print("QUEUE SUMMARY")
print("=" * 80)

print(f"""
CURRENT QUEUE STATUS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stage                    Completed   In Queue    Total
─────────────────────────────────────────────────
RingCentral Downloads    {len(completed):^10} {len(failed):^10} {total_recordings:^10}
Salad Transcriptions     {len(transcribed_ids):^10} {len(recordings_needing_transcription):^10} {len(completed):^10}
AI Insights (OpenRouter) {len(insights_ids):^10} {len(transcripts_needing_insights):^10} {len(transcribed_ids):^10}
Google Drive Uploads     {len(recordings_with_gdrive):^10} {len(recordings_without_gdrive):^10} {len(completed):^10}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROCESSING BOTTLENECKS:
""")

if len(recordings_needing_transcription) > 0:
    print(f"  ⚠️ {len(recordings_needing_transcription)} recordings waiting for Salad Cloud transcription")

if len(transcripts_needing_insights) > 10:
    print(f"  ⚠️ {len(transcripts_needing_insights)} transcripts waiting for AI insights generation")
    print("     → Run batch processor to generate insights with OpenRouter LLMs")

if len(recordings_without_gdrive) > 0:
    print(f"  ⚠️ {len(recordings_without_gdrive)} files waiting for Google Drive upload")

if len(failed) > 0:
    print(f"  ❌ {len(failed)} failed RingCentral downloads need investigation")

print("\n" + "=" * 80)
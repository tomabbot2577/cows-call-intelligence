#!/usr/bin/env python3
"""
Comprehensive statistics for the Call Recording System
Shows all processing stages from RingCentral to Google Drive
"""

import json
import psycopg2
from psycopg2.extras import RealDictCursor
from pathlib import Path
from datetime import datetime

print("=" * 80)
print("CALL RECORDING SYSTEM - PROCESSING STATISTICS")
print(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# 1. Check recordings database (tracks RingCentral downloads)
print("\n📞 RINGCENTRAL RECORDINGS:")
print("-" * 40)

recordings_db = Path('/var/www/call-recording-system/data/recordings_database.json')
if recordings_db.exists():
    with open(recordings_db, 'r') as f:
        recordings = json.load(f)

    total_recordings = len(recordings)
    completed = len([r for r in recordings.values() if r.get('status') == 'completed'])
    failed = len([r for r in recordings.values() if r.get('status') == 'failed'])

    print(f"  Total recordings processed: {total_recordings}")
    print(f"  ✅ Successfully completed: {completed}")
    print(f"  ❌ Failed: {failed}")

    # Get Google Drive uploads from this file
    google_uploads = len([r for r in recordings.values() if r.get('google_drive_id')])
    print(f"  ☁️  Uploaded to Google Drive: {google_uploads}")

    # Show sample recordings
    print("\n  Recent recordings:")
    recent = sorted(recordings.items(), key=lambda x: x[1].get('processed_at', ''), reverse=True)[:5]
    for rec_id, data in recent:
        status = "✅" if data['status'] == 'completed' else "❌"
        gdrive = "📁" if data.get('google_drive_id') else "  "
        print(f"    {status} {gdrive} {rec_id}: {data.get('word_count', 0)} words")

# 2. Check Salad Cloud transcriptions
print("\n🥗 SALAD CLOUD TRANSCRIPTIONS:")
print("-" * 40)

transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
transcript_files = list(transcript_dir.glob('**/*.json'))
transcript_count = len([f for f in transcript_files if not f.name.endswith('.enhanced.json')])

print(f"  Total transcripts: {transcript_count}")

# Check master index
master_index = Path('/var/www/call-recording-system/data/transcriptions/indexes/master_index.json')
if master_index.exists():
    with open(master_index, 'r') as f:
        index_data = json.load(f)
    recordings_indexed = len(index_data.get('recordings', {}))
    print(f"  Indexed in master: {recordings_indexed}")

    # Show breakdown by date
    by_date = {}
    for rec_id, rec_data in index_data.get('recordings', {}).items():
        date = rec_data.get('date', 'unknown')
        by_date[date] = by_date.get(date, 0) + 1

    print("\n  Transcripts by date:")
    for date, count in sorted(by_date.items(), reverse=True)[:5]:
        print(f"    {date}: {count} transcripts")

# 3. Check AI Insights
print("\n🧠 AI INSIGHTS (OpenRouter LLMs):")
print("-" * 40)

insights_dir = Path('/var/www/call-recording-system/data/transcriptions/insights')
insights_files = list(insights_dir.glob('*_insights.json'))
insights_count = len(insights_files)

print(f"  Total AI insights generated: {insights_count}")

if insights_files:
    # Analyze insights content
    call_types = {}
    sentiments = {}

    for insight_file in insights_files:
        try:
            with open(insight_file, 'r') as f:
                data = json.load(f)

            # Count call types
            call_type = data.get('call_classification', {}).get('call_type', 'unknown')
            call_types[call_type] = call_types.get(call_type, 0) + 1

            # Count sentiments
            sentiment = data.get('key_metrics', {}).get('sentiment', 'unknown')
            sentiments[sentiment] = sentiments.get(sentiment, 0) + 1
        except:
            pass

    print("\n  Call types analyzed:")
    for call_type, count in sorted(call_types.items(), key=lambda x: x[1], reverse=True):
        print(f"    {call_type}: {count}")

    print("\n  Sentiment distribution:")
    for sentiment, count in sorted(sentiments.items(), key=lambda x: x[1], reverse=True):
        emoji = "😊" if sentiment == "positive" else "😐" if sentiment == "neutral" else "😔"
        print(f"    {emoji} {sentiment}: {count}")

# 4. Check PostgreSQL Database
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

    # Count transcripts
    cursor.execute("SELECT COUNT(*) as count FROM transcripts")
    transcript_db_count = cursor.fetchone()['count']

    # Count insights
    cursor.execute("SELECT COUNT(*) as count FROM insights")
    insights_db_count = cursor.fetchone()['count']

    # Get total word count
    cursor.execute("SELECT SUM(word_count) as total FROM transcripts WHERE word_count IS NOT NULL")
    total_words = cursor.fetchone()['total'] or 0

    # Get date range
    cursor.execute("""
        SELECT MIN(call_date) as earliest, MAX(call_date) as latest
        FROM transcripts
        WHERE call_date IS NOT NULL
    """)
    dates = cursor.fetchone()

    print(f"  Transcripts in database: {transcript_db_count}")
    print(f"  Insights in database: {insights_db_count}")
    print(f"  Total words transcribed: {total_words:,}")
    if dates['earliest']:
        print(f"  Date range: {dates['earliest']} to {dates['latest']}")

    cursor.close()
    conn.close()
except Exception as e:
    print(f"  ⚠️  Database connection error: {e}")

# 5. Check Google Drive uploads
print("\n☁️  GOOGLE DRIVE UPLOADS:")
print("-" * 40)

# Count markdown files (also uploaded to Google Drive)
md_dir = Path('/var/www/call-recording-system/data/transcriptions/markdown')
md_files = list(md_dir.glob('**/*.md'))
md_count = len([f for f in md_files if not f.name.endswith('_enhanced.md')])

print(f"  JSON uploads: {google_uploads}")
print(f"  Markdown files created: {md_count}")
print(f"  Total Google Drive files: {google_uploads + md_count}")

# 6. Check batch processing status
print("\n⚙️  BATCH PROCESSING STATUS:")
print("-" * 40)

batch_progress = Path('/var/www/call-recording-system/data/batch_progress.json')
if batch_progress.exists():
    with open(batch_progress, 'r') as f:
        batch = json.load(f)

    stats = batch.get('stats', {})
    print(f"  Last batch run: {stats.get('start_time', 'unknown')}")
    if 'end_time' in stats:
        print(f"  Completed at: {stats.get('end_time')}")
        print(f"  Duration: {stats.get('elapsed_seconds', 0)/60:.1f} minutes")
    print(f"  Files processed: {stats.get('processed', 0)}")
    print(f"  Failed: {stats.get('failed', 0)}")
    print(f"  Google Drive uploaded: {stats.get('google_drive_uploaded', 0)}")

# 7. Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

print(f"""
PROCESSING PIPELINE STATUS:
1. RingCentral Downloads:     {total_recordings} recordings
2. Salad Cloud Transcriptions: {transcript_count} completed
3. AI Insights (OpenRouter):   {insights_count} generated
4. Google Drive Uploads:       {google_uploads} files
5. PostgreSQL Database:        {transcript_db_count} transcripts, {insights_db_count} insights

SUCCESS RATE:
- Download success rate:       {(completed/total_recordings*100):.1f}%
- Transcription rate:          {(transcript_count/total_recordings*100):.1f}%
- AI insights rate:            {(insights_count/total_recordings*100):.1f}%
- Google Drive upload rate:    {(google_uploads/total_recordings*100):.1f}%

TOTAL WORDS PROCESSED: {total_words:,}
""")

# Check for any running background processes
print("\n🔄 ACTIVE BACKGROUND PROCESSES:")
print("-" * 40)

import subprocess
try:
    result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
    processes = result.stdout.split('\n')

    relevant_processes = []
    for proc in processes:
        if 'process_queue_batch' in proc or 'insights_dashboard' in proc:
            relevant_processes.append(proc)

    if relevant_processes:
        for proc in relevant_processes[:5]:
            parts = proc.split()
            if len(parts) > 10:
                cmd = ' '.join(parts[10:])[:80]
                print(f"  • {cmd}...")
    else:
        print("  No active batch processing")
except:
    print("  Unable to check processes")

print("\n" + "=" * 80)
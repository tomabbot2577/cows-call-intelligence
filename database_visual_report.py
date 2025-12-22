#!/usr/bin/env python3
"""
Visual Database Report - Shows complete status with formatting
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from pathlib import Path

# Database configuration
PG_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': os.getenv('PG_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432
}

# Connect
conn = psycopg2.connect(**PG_CONFIG)
cursor = conn.cursor(cursor_factory=RealDictCursor)

print("\n" + "=" * 100)
print("📊 POSTGRESQL DATABASE - COMPLETE VISUAL REPORT")
print("=" * 100)
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

# 1. Overall Statistics
print("\n🔢 OVERALL STATISTICS")
print("-" * 100)

cursor.execute("""
    SELECT
        COUNT(*) as total_recordings,
        SUM(CASE WHEN audio_file_path IS NOT NULL THEN 1 ELSE 0 END) as has_audio,
        SUM(CASE WHEN transcript_text != '' AND transcript_text IS NOT NULL THEN 1 ELSE 0 END) as transcribed,
        SUM(CASE WHEN has_ai_insights = true THEN 1 ELSE 0 END) as has_insights,
        SUM(CASE WHEN google_drive_id IS NOT NULL THEN 1 ELSE 0 END) as in_gdrive,
        ROUND(SUM(audio_file_size)/1024/1024/1024.0, 2) as total_gb
    FROM transcripts
""")

stats = cursor.fetchone()

print(f"""
┌─────────────────────────────────────────────────────────────────────┐
│ TOTAL RECORDINGS IN DATABASE: {stats['total_recordings']:,}                                 │
├─────────────────────────────────────────────────────────────────────┤
│ ✅ Has Audio File:        {stats['has_audio']:>6,} recordings                    │
│ 📝 Transcribed:           {stats['transcribed']:>6,} recordings                    │
│ 🧠 Has AI Insights:       {stats['has_insights']:>6,} recordings                    │
│ ☁️  In Google Drive:       {stats['in_gdrive']:>6,} recordings                    │
│ 💾 Total Storage:         {stats['total_gb']:>6.2f} GB                           │
└─────────────────────────────────────────────────────────────────────┘
""")

# 2. Pipeline Status Distribution
print("\n📈 PIPELINE STATUS DISTRIBUTION")
print("-" * 100)

cursor.execute("""
    SELECT
        pipeline_stage,
        COUNT(*) as count,
        ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM transcripts), 1) as percentage
    FROM transcripts
    WHERE pipeline_stage IS NOT NULL
    GROUP BY pipeline_stage
    ORDER BY count DESC
""")

pipeline_stats = cursor.fetchall()

print("\n┌────────────────────┬──────────┬────────────┐")
print("│ Stage              │ Count    │ Percentage │")
print("├────────────────────┼──────────┼────────────┤")
for row in pipeline_stats:
    bar = '█' * int(row['percentage'] / 2)
    print(f"│ {row['pipeline_stage']:<18} │ {row['count']:>8,} │ {row['percentage']:>5.1f}% {bar:<40} │")
print("└────────────────────┴──────────┴────────────┘")

# 3. Sample Records with Details
print("\n📋 SAMPLE RECORDS WITH FULL DETAILS")
print("-" * 100)

cursor.execute("""
    SELECT
        recording_id,
        ROUND(audio_file_size/1024.0/1024.0, 2) as size_mb,
        pipeline_stage,
        word_count,
        has_ai_insights,
        DATE(created_at) as date_added
    FROM transcripts
    WHERE audio_file_size > 0
    ORDER BY created_at DESC
    LIMIT 10
""")

records = cursor.fetchall()

print("\n┌─────────────────┬─────────┬────────────────┬────────────┬──────────┬──────────────┐")
print("│ Recording ID    │ Size MB │ Pipeline Stage │ Word Count │ Insights │ Date Added   │")
print("├─────────────────┼─────────┼────────────────┼────────────┼──────────┼──────────────┤")
for rec in records:
    insights = "✅" if rec['has_ai_insights'] else "❌"
    words = str(rec['word_count']) if rec['word_count'] else "-"
    print(f"│ {rec['recording_id']:<15} │ {rec['size_mb']:>7.2f} │ {rec['pipeline_stage']:<14} │ {words:>10} │ {insights:^8} │ {rec['date_added']} │")
print("└─────────────────┴─────────┴────────────────┴────────────┴──────────┴──────────────┘")

# 4. Processing Status Table
print("\n⚙️  PROCESSING STATUS TRACKING")
print("-" * 100)

cursor.execute("""
    SELECT
        current_stage,
        COUNT(*) as count,
        SUM(CASE WHEN downloaded = true THEN 1 ELSE 0 END) as downloaded,
        SUM(CASE WHEN transcribed = true THEN 1 ELSE 0 END) as transcribed,
        SUM(CASE WHEN audio_deleted = true THEN 1 ELSE 0 END) as audio_deleted
    FROM processing_status
    GROUP BY current_stage
""")

processing = cursor.fetchall()

if processing:
    print("\n┌────────────────────┬───────┬────────────┬─────────────┬───────────────┐")
    print("│ Current Stage      │ Count │ Downloaded │ Transcribed │ Audio Deleted │")
    print("├────────────────────┼───────┼────────────┼─────────────┼───────────────┤")
    for row in processing:
        print(f"│ {row['current_stage']:<18} │ {row['count']:>5} │ {row['downloaded']:>10} │ {row['transcribed']:>11} │ {row['audio_deleted']:>13} │")
    print("└────────────────────┴───────┴────────────┴─────────────┴───────────────┘")
else:
    print("No processing status records yet")

# 5. Transcribed Records
print("\n📝 TRANSCRIBED RECORDINGS")
print("-" * 100)

cursor.execute("""
    SELECT
        recording_id,
        word_count,
        customer_name,
        employee_name,
        DATE(call_date) as call_date
    FROM transcripts
    WHERE transcript_text IS NOT NULL AND transcript_text != ''
    ORDER BY word_count DESC NULLS LAST
    LIMIT 10
""")

transcribed = cursor.fetchall()

if transcribed:
    print("\n┌─────────────────┬────────────┬──────────────────┬──────────────────┬──────────────┐")
    print("│ Recording ID    │ Word Count │ Customer         │ Employee         │ Call Date    │")
    print("├─────────────────┼────────────┼──────────────────┼──────────────────┼──────────────┤")
    for rec in transcribed:
        customer = (rec['customer_name'] or '-')[:16]
        employee = (rec['employee_name'] or '-')[:16]
        call_date = str(rec['call_date']) if rec['call_date'] else '-'
        words = rec['word_count'] if rec['word_count'] else 0
        print(f"│ {rec['recording_id']:<15} │ {words:>10,} │ {customer:<16} │ {employee:<16} │ {call_date:<12} │")
    print("└─────────────────┴────────────┴──────────────────┴──────────────────┴──────────────┘")

# 6. AI Insights Status
print("\n🧠 AI INSIGHTS STATUS")
print("-" * 100)

cursor.execute("""
    SELECT
        i.recording_id,
        i.customer_sentiment,
        i.call_quality_score,
        i.call_type,
        t.word_count
    FROM insights i
    JOIN transcripts t ON i.recording_id = t.recording_id
    LIMIT 10
""")

insights = cursor.fetchall()

if insights:
    print("\n┌─────────────────┬────────────┬───────────┬─────────────────┬────────────┐")
    print("│ Recording ID    │ Sentiment  │ Quality   │ Call Type       │ Word Count │")
    print("├─────────────────┼────────────┼───────────┼─────────────────┼────────────┤")
    for rec in insights:
        sentiment = (rec['customer_sentiment'] or '-')[:10]
        quality = f"{rec['call_quality_score']:.1f}" if rec['call_quality_score'] else '-'
        call_type = (rec['call_type'] or '-')[:15]
        words = rec['word_count'] if rec['word_count'] else 0
        print(f"│ {rec['recording_id']:<15} │ {sentiment:<10} │ {quality:>9} │ {call_type:<15} │ {words:>10,} │")
    print("└─────────────────┴────────────┴───────────┴─────────────────┴────────────┘")
else:
    print("No AI insights generated yet")

# 7. Queue Summary
print("\n📊 PROCESSING QUEUE SUMMARY")
print("-" * 100)

cursor.execute("""
    SELECT
        (SELECT COUNT(*) FROM transcripts WHERE audio_file_path IS NOT NULL) as total_audio,
        (SELECT COUNT(*) FROM transcripts WHERE transcript_text != '' AND transcript_text IS NOT NULL) as transcribed,
        (SELECT COUNT(*) FROM transcripts WHERE has_ai_insights = true) as with_insights
""")

queue = cursor.fetchone()

needs_transcription = queue['total_audio'] - queue['transcribed']
needs_insights = queue['transcribed'] - queue['with_insights']

print(f"""
┌─────────────────────────────────────────────────────────────────────┐
│                       QUEUE STATUS                                  │
├─────────────────────────────────────────────────────────────────────┤
│ 🎤 Awaiting Transcription:     {needs_transcription:>6,} recordings              │
│ 🧠 Awaiting AI Insights:       {needs_insights:>6,} recordings              │
│ ✅ Fully Processed:            {queue['with_insights']:>6,} recordings              │
└─────────────────────────────────────────────────────────────────────┘
""")

# 8. Database Tables Info
print("\n🗄️  DATABASE TABLES INFORMATION")
print("-" * 100)

cursor.execute("""
    SELECT
        schemaname,
        tablename,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
    FROM pg_tables
    WHERE schemaname = 'public'
    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
""")

tables = cursor.fetchall()

print("\n┌──────────────────────────┬────────────┐")
print("│ Table Name               │ Size       │")
print("├──────────────────────────┼────────────┤")
for table in tables:
    print(f"│ {table['tablename']:<24} │ {table['size']:>10} │")
print("└──────────────────────────┴────────────┘")

cursor.close()
conn.close()

print("\n" + "=" * 100)
print("📊 END OF DATABASE REPORT")
print("=" * 100)
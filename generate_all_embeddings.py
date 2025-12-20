#!/usr/bin/env python3
"""
Generate embeddings for all transcripts that don't have them yet
"""

import os
import sys
import time
sys.path.insert(0, '/var/www/call-recording-system')

from src.insights.embeddings_manager import EmbeddingsManager
import psycopg2
from psycopg2.extras import RealDictCursor

# Load API key from environment (set in .env file)
from dotenv import load_dotenv
load_dotenv()

if not os.getenv('OPENAI_API_KEY'):
    print("ERROR: OPENAI_API_KEY not set in environment. Add it to .env file.")
    sys.exit(1)

def main():
    # Database configuration
    db_config = {
        'dbname': 'call_insights',
        'user': 'call_insights_user',
        'password': 'call_insights_pass',
        'host': 'localhost',
        'port': 5432
    }

    # Connect to database
    conn = psycopg2.connect(**db_config, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Initialize embeddings manager
    mgr = EmbeddingsManager()

    # Get transcripts without embeddings
    cursor.execute("""
        SELECT t.recording_id, t.transcript_text, t.customer_name, t.employee_name,
               t.call_date, t.duration_seconds, t.word_count,
               i.customer_sentiment, i.call_quality_score, i.customer_satisfaction_score,
               i.call_type, i.issue_category, i.summary, i.key_topics
        FROM transcripts t
        LEFT JOIN insights i ON t.recording_id = i.recording_id
        WHERE t.transcript_text IS NOT NULL
          AND LENGTH(t.transcript_text) > 100
          AND NOT EXISTS (
              SELECT 1 FROM transcript_embeddings te
              WHERE te.recording_id = t.recording_id
          )
        LIMIT 100
    """)

    records = cursor.fetchall()
    print(f"Found {len(records)} transcripts without embeddings\n")

    success_count = 0

    for i, record in enumerate(records, 1):
        recording_id = record['recording_id']
        print(f"{i}/{len(records)}: Processing {recording_id}...")

        try:
            # Process the transcript
            if mgr.process_transcript(recording_id):
                success_count += 1
                print(f"  ✅ Embedding generated successfully")
            else:
                print(f"  ❌ Failed to generate embedding")

            # Rate limiting - avoid hitting API limits
            if i % 10 == 0:
                print(f"\n--- Progress: {i}/{len(records)} processed, {success_count} successful ---\n")
                time.sleep(2)  # Pause every 10 requests

        except Exception as e:
            print(f"  ❌ Error: {e}")

    print(f"\n✅ Completed! Generated {success_count}/{len(records)} embeddings")

    # Show total embeddings in database
    cursor.execute("SELECT COUNT(*) as total FROM transcript_embeddings WHERE embedding IS NOT NULL")
    total = cursor.fetchone()['total']
    print(f"📊 Total embeddings in database: {total}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()
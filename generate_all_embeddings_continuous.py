#!/usr/bin/env python3
"""
Generate embeddings for all transcripts that don't have them yet
Runs continuously until all embeddings are complete
"""

import os
import sys
import time
import argparse
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
    parser = argparse.ArgumentParser(description='Generate embeddings continuously')
    parser.add_argument('--batch-size', type=int, default=100, help='Number of transcripts per batch')
    parser.add_argument('--max-total', type=int, default=None, help='Maximum total to process (for testing)')
    args = parser.parse_args()

    BATCH_SIZE = args.batch_size
    MAX_TOTAL = args.max_total

    # Database configuration
    db_config = {
        'dbname': 'call_insights',
        'user': 'call_insights_user',
        'password': 'REDACTED_DB_PASSWORD',
        'host': 'localhost',
        'port': 5432
    }

    # Connect to database
    conn = psycopg2.connect(**db_config, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Initialize embeddings manager
    mgr = EmbeddingsManager()

    processed_total = 0
    batch_num = 0

    print(f"Starting continuous embedding generation with batch size {BATCH_SIZE}")
    print("=" * 60)

    while True:
        batch_num += 1

        # Get next batch of transcripts without embeddings
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
            LIMIT %s
        """, (BATCH_SIZE,))

        records = cursor.fetchall()

        if not records:
            print(f"\n🎉 All embeddings complete! Total processed: {processed_total}")
            break

        if MAX_TOTAL and processed_total >= MAX_TOTAL:
            print(f"\n📊 Reached maximum limit of {MAX_TOTAL}. Stopping.")
            break

        print(f"\n📦 Batch {batch_num}: Found {len(records)} transcripts without embeddings")

        batch_success = 0
        batch_failed = 0

        for i, record in enumerate(records, 1):
            recording_id = record['recording_id']
            print(f"  [{i}/{len(records)}] Processing {recording_id}...", end="")

            try:
                # Process the transcript
                if mgr.process_transcript(recording_id):
                    batch_success += 1
                    processed_total += 1
                    print(" ✅")
                else:
                    batch_failed += 1
                    print(" ❌ Failed")

                # Rate limiting - avoid hitting API limits
                if i % 10 == 0:
                    print(f"    Progress: {i}/{len(records)} in batch, {processed_total} total")
                    time.sleep(2)  # Pause every 10 requests

            except Exception as e:
                batch_failed += 1
                print(f" ❌ Error: {e}")

        # Batch summary
        print(f"\n✅ Batch {batch_num} complete:")
        print(f"   - Success: {batch_success}")
        print(f"   - Failed: {batch_failed}")
        print(f"   - Total processed so far: {processed_total}")

        # Get current database totals
        cursor.execute("SELECT COUNT(*) as total FROM transcript_embeddings WHERE embedding IS NOT NULL")
        db_total = cursor.fetchone()['total']

        cursor.execute("""
            SELECT COUNT(*) as remaining
            FROM transcripts t
            WHERE t.transcript_text IS NOT NULL
              AND LENGTH(t.transcript_text) > 100
              AND NOT EXISTS (
                  SELECT 1 FROM transcript_embeddings te
                  WHERE te.recording_id = t.recording_id
              )
        """)
        remaining = cursor.fetchone()['remaining']

        print(f"📊 Database status: {db_total} embeddings, {remaining} remaining")
        print("=" * 60)

        # Brief pause between batches
        if remaining > 0:
            time.sleep(3)

    # Final statistics
    cursor.execute("SELECT COUNT(*) as total FROM transcript_embeddings WHERE embedding IS NOT NULL")
    final_total = cursor.fetchone()['total']
    print(f"\n🏁 Final statistics:")
    print(f"   - Total embeddings in database: {final_total}")
    print(f"   - Processed in this session: {processed_total}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()
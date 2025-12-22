#!/usr/bin/env python3
"""
Process complete insights continuously until all records are done
Handles all 4 layers of AI analysis with automatic retry and completion
"""

import os
import sys
import time
import argparse
import logging
from datetime import datetime

sys.path.insert(0, '/var/www/call-recording-system')

from src.insights.insights_manager_postgresql import PostgreSQLInsightsManager as InsightsManager
import psycopg2
from psycopg2.extras import RealDictCursor

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description='Process AI insights continuously')
    parser.add_argument('--batch-size', type=int, default=50, help='Number of records per batch')
    parser.add_argument('--max-total', type=int, default=None, help='Maximum total to process (for testing)')
    parser.add_argument('--batch-id', type=str, default='continuous', help='Batch ID for logging')
    args = parser.parse_args()

    BATCH_SIZE = args.batch_size
    MAX_TOTAL = args.max_total
    BATCH_ID = args.batch_id

    # Database configuration
    db_config = {
        'dbname': 'call_insights',
        'user': 'call_insights_user',
        'password': os.getenv('PG_PASSWORD', ''),
        'host': 'localhost',
        'port': 5432
    }

    # Connect to database
    conn = psycopg2.connect(**db_config, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    # Initialize insights manager
    mgr = InsightsManager()

    processed_total = 0
    batch_num = 0

    print(f"🚀 Starting continuous AI insights processing")
    print(f"   Batch size: {BATCH_SIZE}")
    print(f"   Batch ID: {BATCH_ID}")
    print("=" * 60)

    while True:
        batch_num += 1

        # Get current status
        cursor.execute("""
            SELECT
                (SELECT COUNT(*) FROM transcript_embeddings) as total_embeddings,
                (SELECT COUNT(*) FROM insights) as insights_count,
                (SELECT COUNT(*) FROM call_recommendations) as recommendations_count,
                (SELECT COUNT(*) FROM call_resolutions) as resolutions_count
        """)
        status = cursor.fetchone()

        print(f"\n📊 Current Status:")
        print(f"   Embeddings: {status['total_embeddings']}")
        print(f"   Insights: {status['insights_count']}")
        print(f"   Recommendations: {status['recommendations_count']}")
        print(f"   Resolutions: {status['resolutions_count']}")

        # Get next batch of records that need AI processing
        cursor.execute("""
            SELECT te.recording_id
            FROM transcript_embeddings te
            WHERE NOT EXISTS (
                SELECT 1 FROM insights i
                WHERE i.recording_id = te.recording_id
                AND i.customer_sentiment IS NOT NULL
            )
            ORDER BY te.recording_id
            LIMIT %s
        """, (BATCH_SIZE,))

        records = cursor.fetchall()

        if not records:
            print(f"\n🎉 All AI insights complete! Total processed: {processed_total}")
            break

        if MAX_TOTAL and processed_total >= MAX_TOTAL:
            print(f"\n📊 Reached maximum limit of {MAX_TOTAL}. Stopping.")
            break

        print(f"\n📦 Batch {batch_num}: Processing {len(records)} records")

        batch_success = 0
        batch_failed = 0

        for i, record in enumerate(records, 1):
            recording_id = record['recording_id']
            print(f"  [{i}/{len(records)}] Processing {recording_id}...", end="")

            try:
                # Process all 4 layers for this recording
                layers_complete = []

                # Layer 1: Entity Extraction (handled by insights manager)
                # Layer 2: Sentiment & Quality (handled by insights manager)
                if mgr.process_recording(recording_id):
                    layers_complete.append("insights")

                    # Layer 3: Call Resolution
                    if mgr.generate_call_resolution(recording_id):
                        layers_complete.append("resolution")

                    # Layer 4: Recommendations
                    if mgr.generate_recommendations(recording_id):
                        layers_complete.append("recommendations")

                if len(layers_complete) == 3:
                    batch_success += 1
                    processed_total += 1
                    print(f" ✅ All layers")
                else:
                    batch_failed += 1
                    print(f" ⚠️ Partial: {layers_complete}")

                # Rate limiting to avoid API overload
                if i % 10 == 0:
                    print(f"    Progress: {i}/{len(records)} in batch, {processed_total} total")
                    time.sleep(3)  # Pause every 10 requests
                else:
                    time.sleep(2)  # Regular pause between requests

            except Exception as e:
                batch_failed += 1
                print(f" ❌ Error: {e}")
                time.sleep(5)  # Longer pause after error

        # Batch summary
        print(f"\n✅ Batch {batch_num} complete:")
        print(f"   - Success: {batch_success}")
        print(f"   - Failed: {batch_failed}")
        print(f"   - Total processed so far: {processed_total}")

        # Get updated totals
        cursor.execute("""
            SELECT
                COUNT(*) as remaining
            FROM transcript_embeddings te
            WHERE NOT EXISTS (
                SELECT 1 FROM insights i
                WHERE i.recording_id = te.recording_id
                AND i.customer_sentiment IS NOT NULL
            )
        """)
        remaining = cursor.fetchone()['remaining']

        print(f"📊 Remaining to process: {remaining}")
        print("=" * 60)

        # Brief pause between batches
        if remaining > 0:
            time.sleep(5)

    # Final statistics
    cursor.execute("""
        SELECT
            (SELECT COUNT(*) FROM transcript_embeddings) as embeddings,
            (SELECT COUNT(*) FROM insights) as insights,
            (SELECT COUNT(*) FROM call_recommendations) as recommendations,
            (SELECT COUNT(*) FROM call_resolutions) as resolutions
    """)
    final_stats = cursor.fetchone()

    print(f"\n🏁 Final statistics:")
    print(f"   - Total embeddings: {final_stats['embeddings']}")
    print(f"   - Total insights: {final_stats['insights']}")
    print(f"   - Total recommendations: {final_stats['recommendations']}")
    print(f"   - Total resolutions: {final_stats['resolutions']}")
    print(f"   - Processed in this session: {processed_total}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Process AI insights continuously in batches
"""

import os
import sys
import time
import logging
from datetime import datetime

sys.path.insert(0, '/var/www/call-recording-system')

from src.insights.insights_manager_postgresql import PostgreSQLInsightsManager
import psycopg2
from psycopg2.extras import RealDictCursor

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-size', type=int, default=30)
    parser.add_argument('--batch-id', type=str, default='batch')
    args = parser.parse_args()

    BATCH_SIZE = args.batch_size
    BATCH_ID = args.batch_id

    # Database configuration
    db_config = {
        'dbname': 'call_insights',
        'user': 'call_insights_user',
        'password': 'REDACTED_DB_PASSWORD',
        'host': 'localhost',
        'port': 5432
    }

    logger.info(f"🚀 Starting AI batch processor {BATCH_ID} with batch size {BATCH_SIZE}")

    # Initialize manager
    mgr = PostgreSQLInsightsManager()

    processed_total = 0
    batch_num = 0

    while True:
        batch_num += 1

        # Connect for each batch
        conn = psycopg2.connect(**db_config, cursor_factory=RealDictCursor)
        cursor = conn.cursor()

        # Get unprocessed recordings
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

        recordings = cursor.fetchall()

        if not recordings:
            logger.info(f"✅ Batch {BATCH_ID} complete! Total processed: {processed_total}")
            cursor.close()
            conn.close()
            break

        logger.info(f"📦 Batch {batch_num}: Processing {len(recordings)} recordings")

        for i, rec in enumerate(recordings, 1):
            recording_id = rec['recording_id']

            try:
                logger.info(f"  [{i}/{len(recordings)}] Processing {recording_id}")

                # Process all layers
                result = mgr.process_recording(recording_id)

                if result:
                    processed_total += 1
                    logger.info(f"    ✅ Success")
                else:
                    logger.warning(f"    ⚠️ Failed")

                # Rate limit
                time.sleep(3)

            except Exception as e:
                logger.error(f"    ❌ Error: {e}")
                time.sleep(5)

        cursor.close()
        conn.close()

        logger.info(f"Batch {batch_num} done. Total processed: {processed_total}")
        time.sleep(5)

    logger.info(f"🏁 {BATCH_ID} finished! Processed {processed_total} total recordings")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Process AI insights continuously until all records are complete
"""

import subprocess
import time
import psycopg2
from psycopg2.extras import RealDictCursor

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-size', type=int, default=20)
    parser.add_argument('--batch-id', type=str, default='batch')
    parser.add_argument('--delay', type=int, default=3, help='Delay between records')
    args = parser.parse_args()

    db_config = {
        'dbname': 'call_insights',
        'user': 'call_insights_user',
        'password': 'call_insights_pass',
        'host': 'localhost',
        'port': 5432
    }

    print(f"🚀 Starting continuous AI processor {args.batch_id}")
    print(f"   Batch size: {args.batch_size}, Delay: {args.delay}s")

    processed = 0
    errors = 0

    while True:
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
        """, (args.batch_size,))

        records = cursor.fetchall()
        cursor.close()
        conn.close()

        if not records:
            print(f"✅ All done! Processed: {processed}, Errors: {errors}")
            break

        print(f"📦 Processing batch of {len(records)} recordings...")

        for rec in records:
            recording_id = rec['recording_id']
            print(f"  Processing {recording_id}...")

            try:
                # Call process_complete_insights.py directly
                result = subprocess.run(
                    ['python', 'process_complete_insights.py', recording_id],
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if result.returncode == 0:
                    processed += 1
                    print(f"    ✅ Success (Total: {processed})")
                else:
                    errors += 1
                    print(f"    ⚠️ Failed: {result.stderr[:100]}")

            except subprocess.TimeoutExpired:
                errors += 1
                print(f"    ⏱️ Timeout")
            except Exception as e:
                errors += 1
                print(f"    ❌ Error: {e}")

            time.sleep(args.delay)

        print(f"Batch complete. Processed: {processed}, Errors: {errors}")
        time.sleep(5)

    print(f"🏁 Finished! Total processed: {processed}, Total errors: {errors}")

if __name__ == "__main__":
    main()
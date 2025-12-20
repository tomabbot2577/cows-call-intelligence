#!/usr/bin/env python3
"""
Fix call metadata in database
- Updates duration_seconds from transcription JSON files
- Eventually will fix actual call dates when RingCentral data is available
"""

import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'REDACTED_DB_PASSWORD',
    'host': 'localhost',
    'port': 5432
}

def update_durations():
    """Update duration_seconds in database from JSON files"""

    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    try:
        # Get all transcripts that need duration updates
        cursor.execute("""
            SELECT recording_id, call_date
            FROM transcripts
            WHERE duration_seconds IS NULL OR duration_seconds = 0
        """)

        recordings = cursor.fetchall()
        logger.info(f"Found {len(recordings)} recordings needing duration updates")

        updated_count = 0
        for rec in recordings:
            recording_id = rec['recording_id']

            # Find the JSON file
            json_pattern = f"/var/www/call-recording-system/data/transcriptions/json/**/{recording_id}.json"
            json_files = list(Path("/var/www/call-recording-system/data/transcriptions/json").rglob(f"{recording_id}.json"))

            if json_files:
                json_file = json_files[0]
                try:
                    with open(json_file, 'r') as f:
                        data = json.load(f)

                    # Get duration from various possible locations
                    duration = None

                    # Check call_metadata first
                    if 'call_metadata' in data and 'duration_seconds' in data['call_metadata']:
                        duration = data['call_metadata']['duration_seconds']
                    # Check transcription section
                    elif 'transcription' in data and 'duration_seconds' in data['transcription']:
                        duration = data['transcription']['duration_seconds']
                    # Check root level
                    elif 'duration_seconds' in data:
                        duration = data['duration_seconds']

                    if duration and duration > 0:
                        # Update database
                        cursor.execute("""
                            UPDATE transcripts
                            SET duration_seconds = %s
                            WHERE recording_id = %s
                        """, (duration, recording_id))

                        updated_count += 1
                        logger.info(f"Updated {recording_id}: duration = {duration:.1f} seconds")

                except Exception as e:
                    logger.error(f"Error processing {json_file}: {e}")

        conn.commit()
        logger.info(f"✅ Updated {updated_count} recordings with duration data")

    except Exception as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def main():
    """Main function"""
    logger.info("🔧 Fixing call metadata in database...")

    # Update durations from JSON files
    update_durations()

    # TODO: In future, update actual call dates from RingCentral data
    # This would require parsing the original RingCentral metadata
    # or re-downloading with proper date extraction

    logger.info("✅ Metadata fix complete!")

if __name__ == "__main__":
    main()
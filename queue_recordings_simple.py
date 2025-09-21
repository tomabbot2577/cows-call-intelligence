#!/usr/bin/env python3
"""
Simple queue script that directly inserts recordings into database
Avoids ORM model issues by using raw SQL
"""

import os
import sys
import logging
import json
import psycopg2
from datetime import datetime, timezone
from typing import Dict, Any, List, Set
import time

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
from ringcentral import SDK

# Load environment
load_dotenv('/var/www/call-recording-system/.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Get direct PostgreSQL connection"""
    db_url = os.getenv('DATABASE_URL')
    # Parse the URL
    # Format: postgresql://user:password@host:port/database
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', '')

    parts = db_url.split('@')
    user_pass = parts[0].split(':')
    host_db = parts[1].split('/')
    host_port = host_db[0].split(':')

    return psycopg2.connect(
        host=host_port[0],
        port=host_port[1] if len(host_port) > 1 else 5432,
        database=host_db[1],
        user=user_pass[0],
        password=user_pass[1]
    )


def get_existing_recording_ids() -> Set[str]:
    """Get existing recording IDs from database"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT recording_id FROM call_recordings WHERE recording_id IS NOT NULL")
        existing = {row[0] for row in cur.fetchall()}
        logger.info(f"Found {len(existing)} existing recordings in database")
        return existing
    finally:
        cur.close()
        conn.close()


def fetch_ringcentral_recordings(start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
    """Fetch recordings from RingCentral"""
    logger.info(f"Fetching recordings from {start_date.date()} to {end_date.date()}")

    rcsdk = SDK(
        os.getenv('RINGCENTRAL_CLIENT_ID'),
        os.getenv('RINGCENTRAL_CLIENT_SECRET'),
        os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')
    )

    platform = rcsdk.platform()

    try:
        # Authenticate
        platform.login(jwt=os.getenv('RINGCENTRAL_JWT_TOKEN'))
        logger.info("✅ Authenticated with RingCentral")

        # Format dates
        date_from = start_date.strftime('%Y-%m-%dT00:00:00.000Z')
        date_to = end_date.strftime('%Y-%m-%dT23:59:59.999Z')

        all_recordings = []
        page = 1

        while True:
            logger.info(f"  Fetching page {page}...")

            response = platform.get(
                '/restapi/v1.0/account/~/call-log',
                {
                    'dateFrom': date_from,
                    'dateTo': date_to,
                    'type': 'Voice',
                    'view': 'Detailed',
                    'recordingType': 'All',
                    'perPage': 1000,
                    'page': page
                }
            )

            data = response.json()

            # Extract records
            if hasattr(data, 'records'):
                records = data.records
                navigation = data.navigation if hasattr(data, 'navigation') else None
            else:
                records = data.get('records', [])
                navigation = data.get('navigation', {})

            # Process records
            for record in records:
                recording_info = None

                if hasattr(record, 'recording'):
                    recording_info = record.recording
                elif isinstance(record, dict) and record.get('recording'):
                    recording_info = record['recording']

                if recording_info:
                    # Extract info carefully
                    rec_data = {}

                    # Handle object or dict format
                    if hasattr(record, '__dict__'):
                        rec_data['id'] = getattr(record, 'id', None)
                        rec_data['session_id'] = getattr(record, 'sessionId', None)
                        rec_data['start_time'] = getattr(record, 'startTime', None)
                        rec_data['duration'] = getattr(record, 'duration', 0)
                        rec_data['direction'] = getattr(record, 'direction', None)

                        # Handle from field
                        from_obj = getattr(record, 'from_', None) or getattr(record, 'from', None)
                        if from_obj:
                            rec_data['from_number'] = getattr(from_obj, 'phoneNumber', 'Unknown')
                            rec_data['from_name'] = getattr(from_obj, 'name', '')
                        else:
                            rec_data['from_number'] = 'Unknown'
                            rec_data['from_name'] = ''

                        # Handle to field
                        to_obj = getattr(record, 'to', None)
                        if to_obj:
                            rec_data['to_number'] = getattr(to_obj, 'phoneNumber', 'Unknown')
                            rec_data['to_name'] = getattr(to_obj, 'name', '')
                        else:
                            rec_data['to_number'] = 'Unknown'
                            rec_data['to_name'] = ''

                        # Recording info
                        rec_data['recording_id'] = getattr(recording_info, 'id', None)
                        rec_data['recording_type'] = getattr(recording_info, 'type', 'Unknown')
                    else:
                        rec_data['id'] = record.get('id')
                        rec_data['session_id'] = record.get('sessionId')
                        rec_data['start_time'] = record.get('startTime')
                        rec_data['duration'] = record.get('duration', 0)
                        rec_data['direction'] = record.get('direction')
                        rec_data['from_number'] = record.get('from', {}).get('phoneNumber', 'Unknown')
                        rec_data['from_name'] = record.get('from', {}).get('name', '')
                        rec_data['to_number'] = record.get('to', {}).get('phoneNumber', 'Unknown')
                        rec_data['to_name'] = record.get('to', {}).get('name', '')
                        rec_data['recording_id'] = recording_info.get('id')
                        rec_data['recording_type'] = recording_info.get('type', 'Unknown')

                    all_recordings.append(rec_data)

            # Check for more pages
            has_next = False
            if hasattr(navigation, 'nextPage'):
                has_next = bool(navigation.nextPage)
            elif isinstance(navigation, dict):
                has_next = bool(navigation.get('nextPage'))

            if not has_next:
                break

            page += 1
            time.sleep(0.5)  # Rate limit

        logger.info(f"✅ Found {len(all_recordings)} recordings")
        return all_recordings

    finally:
        try:
            platform.logout()
        except:
            pass


def queue_recordings(recordings: List[Dict[str, Any]], existing_ids: Set[str]):
    """Queue recordings to database using direct SQL"""
    conn = get_db_connection()
    cur = conn.cursor()

    queued = 0
    skipped = 0
    failed = 0

    for rec in recordings:
        recording_id = rec['recording_id']

        if recording_id in existing_ids:
            skipped += 1
            continue

        try:
            # Parse datetime
            start_time = None
            if rec['start_time']:
                start_time = datetime.fromisoformat(rec['start_time'].replace('Z', '+00:00'))

            # Insert record
            cur.execute("""
                INSERT INTO call_recordings (
                    call_id, recording_id, session_id, start_time, duration,
                    from_number, from_name, to_number, to_name,
                    direction, recording_type,
                    download_status, transcription_status, upload_status,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    'pending', 'pending', 'pending',
                    NOW(), NOW()
                )
            """, (
                rec['id'], recording_id, rec['session_id'], start_time, rec['duration'],
                rec['from_number'], rec['from_name'], rec['to_number'], rec['to_name'],
                rec['direction'], rec['recording_type']
            ))

            conn.commit()
            queued += 1

            if queued % 100 == 0:
                logger.info(f"  Progress: {queued} queued, {skipped} skipped")

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to queue {recording_id}: {e}")
            failed += 1

    cur.close()
    conn.close()

    return queued, skipped, failed


def main():
    """Main entry point"""
    print("\n" + "="*80)
    print("🚀 SIMPLE QUEUE LOADER - JUNE 1 TO SEPTEMBER 18, 2025")
    print("="*80)

    # Date range
    start_date = datetime(2025, 6, 1, tzinfo=timezone.utc)
    end_date = datetime(2025, 9, 18, 23, 59, 59, tzinfo=timezone.utc)

    print(f"\n📅 Date Range: {start_date.date()} to {end_date.date()}")

    # Get existing recordings
    existing_ids = get_existing_recording_ids()

    # Fetch from RingCentral
    recordings = fetch_ringcentral_recordings(start_date, end_date)

    # Filter new recordings
    new_recordings = [r for r in recordings if r['recording_id'] not in existing_ids]

    print(f"\n📊 Summary:")
    print(f"  Total found: {len(recordings)}")
    print(f"  Already in database: {len(recordings) - len(new_recordings)}")
    print(f"  New to queue: {len(new_recordings)}")

    if new_recordings:
        print(f"\n🔄 Queueing {len(new_recordings)} recordings...")
        queued, skipped, failed = queue_recordings(new_recordings, existing_ids)

        print(f"\n✅ Results:")
        print(f"  Queued: {queued}")
        print(f"  Skipped: {skipped}")
        print(f"  Failed: {failed}")
    else:
        print("\n✅ All recordings already in database!")

    print("\n✨ Complete!")


if __name__ == "__main__":
    main()
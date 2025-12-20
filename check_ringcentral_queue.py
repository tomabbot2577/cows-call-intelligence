#!/usr/bin/env python3
"""
Check RingCentral Recording Queue
Shows how many recordings are available for processing
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
import json

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
from src.ringcentral.auth import RingCentralAuth
from src.database.session import SessionManager
from src.database.models import CallRecording

def get_session():
    """Get database session"""
    session_mgr = SessionManager(os.getenv('DATABASE_URL'))
    return session_mgr.create_session()

def check_recording_queue():
    """Check RingCentral for available recordings"""

    print("\n" + "="*80)
    print("RINGCENTRAL RECORDING QUEUE CHECK")
    print("="*80)

    # Load environment
    load_dotenv('/var/www/call-recording-system/.env')

    # Initialize RingCentral
    print("\n🔐 Authenticating with RingCentral...")
    auth = RingCentralAuth()
    platform = auth.authenticate()

    if not platform:
        print("❌ Failed to authenticate with RingCentral")
        return

    print("✅ Successfully authenticated")

    # Set date range (last 60 days)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=60)

    print(f"\n📅 Date Range:")
    print(f"  From: {start_date.strftime('%Y-%m-%d')}")
    print(f"  To: {end_date.strftime('%Y-%m-%d')}")

    # Get call log with recordings
    print("\n🔍 Fetching call records...")

    try:
        # Format dates for RingCentral API
        date_from = start_date.strftime('%Y-%m-%dT00:00:00.000Z')
        date_to = end_date.strftime('%Y-%m-%dT23:59:59.999Z')

        # Get call log
        response = platform.get(
            '/restapi/v1.0/account/~/call-log',
            {
                'dateFrom': date_from,
                'dateTo': date_to,
                'type': 'Voice',
                'view': 'Detailed',
                'recordingType': 'All',
                'perPage': 1000
            }
        )

        if response.ok():
            data = response.json()
            records = data.get('records', [])

            print(f"✅ Found {len(records)} total call records")

            # Filter records with recordings
            recordings_available = []
            for record in records:
                if record.get('recording'):
                    recording_info = record['recording']
                    recordings_available.append({
                        'id': record.get('id'),
                        'session_id': record.get('sessionId'),
                        'start_time': record.get('startTime'),
                        'duration': record.get('duration', 0),
                        'direction': record.get('direction'),
                        'from': record.get('from', {}).get('phoneNumber', 'Unknown'),
                        'from_name': record.get('from', {}).get('name', 'Unknown'),
                        'to': record.get('to', {}).get('phoneNumber', 'Unknown'),
                        'to_name': record.get('to', {}).get('name', 'Unknown'),
                        'recording_id': recording_info.get('id'),
                        'recording_uri': recording_info.get('contentUri'),
                        'recording_type': recording_info.get('type', 'Unknown')
                    })

            print(f"\n📞 Recordings Available: {len(recordings_available)}")

            if recordings_available:
                # Check database for already processed recordings
                print("\n🗄️ Checking database for processed recordings...")

                db = get_session()
                processed_ids = set()

                try:
                    # Get all processed recording IDs
                    processed = db.query(CallRecording.recording_id).filter(
                        CallRecording.transcription_status.in_(['completed', 'processing'])
                    ).all()

                    processed_ids = {r.recording_id for r in processed}
                    print(f"  Found {len(processed_ids)} already processed")
                except Exception as e:
                    print(f"  Warning: Could not check database: {e}")
                finally:
                    db.close()

                # Filter unprocessed recordings
                unprocessed = [r for r in recordings_available if r['recording_id'] not in processed_ids]

                print(f"\n📊 Queue Summary:")
                print(f"  Total recordings found: {len(recordings_available)}")
                print(f"  Already processed: {len(processed_ids)}")
                print(f"  📌 New recordings to process: {len(unprocessed)}")

                # Group by date
                print(f"\n📅 Recordings by Date:")
                date_counts = {}
                for recording in unprocessed:
                    date = recording['start_time'][:10] if recording['start_time'] else 'Unknown'
                    date_counts[date] = date_counts.get(date, 0) + 1

                for date in sorted(date_counts.keys(), reverse=True)[:10]:
                    print(f"  {date}: {date_counts[date]} recordings")

                # Show sample of recent unprocessed recordings
                print(f"\n📞 Recent Unprocessed Recordings (showing first 10):")
                for i, recording in enumerate(unprocessed[:10], 1):
                    duration_min = recording['duration'] // 60
                    duration_sec = recording['duration'] % 60
                    print(f"\n  {i}. Recording ID: {recording['recording_id']}")
                    print(f"     Date: {recording['start_time'][:19] if recording['start_time'] else 'Unknown'}")
                    print(f"     Duration: {duration_min}:{duration_sec:02d}")
                    print(f"     Direction: {recording['direction']}")
                    print(f"     From: {recording['from_name']} ({recording['from']})")
                    print(f"     To: {recording['to_name']} ({recording['to']})")

                # Calculate total duration
                total_duration = sum(r['duration'] for r in unprocessed)
                total_hours = total_duration // 3600
                total_minutes = (total_duration % 3600) // 60

                print(f"\n⏱️ Total Duration of Unprocessed Recordings:")
                print(f"  {total_hours} hours {total_minutes} minutes")

                # Estimate processing time (approximately 1/3 of audio duration for Salad)
                est_processing = total_duration // 3
                est_hours = est_processing // 3600
                est_minutes = (est_processing % 3600) // 60

                print(f"\n⚡ Estimated Processing Time:")
                print(f"  {est_hours} hours {est_minutes} minutes")

                # Save queue details to file
                queue_file = '/var/www/call-recording-system/ringcentral_queue.json'
                with open(queue_file, 'w') as f:
                    json.dump({
                        'check_time': datetime.now().isoformat(),
                        'date_range': {
                            'from': start_date.isoformat(),
                            'to': end_date.isoformat()
                        },
                        'summary': {
                            'total_found': len(recordings_available),
                            'already_processed': len(processed_ids),
                            'to_process': len(unprocessed),
                            'total_duration_seconds': total_duration,
                            'estimated_processing_seconds': est_processing
                        },
                        'unprocessed_recordings': unprocessed[:100]  # Save first 100
                    }, f, indent=2)

                print(f"\n💾 Queue details saved to: {queue_file}")

            else:
                print("\n✅ No recordings found in the specified date range")

        else:
            print(f"❌ Failed to fetch call log: {response.text()}")

    except Exception as e:
        print(f"\n❌ Error checking recordings: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*80)
    print("QUEUE CHECK COMPLETE")
    print("="*80)

if __name__ == "__main__":
    check_recording_queue()
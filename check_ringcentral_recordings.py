#!/usr/bin/env python3
"""
Check RingCentral Recording Queue using SDK
"""

import os
import sys
from datetime import datetime, timedelta, timezone
import json
from ringcentral import SDK

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv

def check_recordings():
    """Check RingCentral for available recordings"""

    print("\n" + "="*80)
    print("RINGCENTRAL RECORDING QUEUE CHECK")
    print("="*80)

    # Load environment
    load_dotenv('/var/www/call-recording-system/.env')

    # Initialize RingCentral SDK
    print("\n🔐 Authenticating with RingCentral...")

    rcsdk = SDK(
        os.getenv('RINGCENTRAL_CLIENT_ID'),
        os.getenv('RINGCENTRAL_CLIENT_SECRET'),
        os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')
    )

    platform = rcsdk.platform()

    try:
        # Authenticate with JWT
        platform.login(jwt=os.getenv('RINGCENTRAL_JWT_TOKEN'))
        print("✅ Successfully authenticated")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return

    # Set date range (last 30 days)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=30)

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

        data = response.json()
        # Handle RingCentral SDK response format
        if hasattr(data, '__dict__'):
            records = data.records if hasattr(data, 'records') else []
        else:
            records = data.get('records', [])

        print(f"✅ Found {len(records)} total call records")

        # Filter records with recordings
        recordings_available = []
        for record in records:
            # Handle SDK object format
            if hasattr(record, 'recording'):
                recording_info = record.recording
                recordings_available.append({
                    'id': getattr(record, 'id', None),
                    'session_id': getattr(record, 'sessionId', None),
                    'start_time': getattr(record, 'startTime', None),
                    'duration': getattr(record, 'duration', 0),
                    'direction': getattr(record, 'direction', None),
                    'from': getattr(getattr(record, 'from_', getattr(record, 'from', None)), 'phoneNumber', 'Unknown') if hasattr(record, 'from_') or hasattr(record, 'from') else 'Unknown',
                    'from_name': getattr(getattr(record, 'from_', getattr(record, 'from', None)), 'name', '') if hasattr(record, 'from_') or hasattr(record, 'from') else '',
                    'from_extension': getattr(getattr(record, 'from_', getattr(record, 'from', None)), 'extensionNumber', '') if hasattr(record, 'from_') or hasattr(record, 'from') else '',
                    'to': getattr(record.to, 'phoneNumber', 'Unknown') if hasattr(record, 'to') else 'Unknown',
                    'to_name': getattr(record.to, 'name', '') if hasattr(record, 'to') else '',
                    'to_extension': getattr(record.to, 'extensionNumber', '') if hasattr(record, 'to') else '',
                    'recording_id': getattr(recording_info, 'id', None),
                    'recording_uri': getattr(recording_info, 'contentUri', None),
                    'recording_type': getattr(recording_info, 'type', 'Unknown')
                })
            elif isinstance(record, dict) and record.get('recording'):
                recording_info = record['recording']
                recordings_available.append({
                    'id': record.get('id'),
                    'session_id': record.get('sessionId'),
                    'start_time': record.get('startTime'),
                    'duration': record.get('duration', 0),
                    'direction': record.get('direction'),
                    'from': record.get('from', {}).get('phoneNumber', 'Unknown'),
                    'from_name': record.get('from', {}).get('name', ''),
                    'from_extension': record.get('from', {}).get('extensionNumber', ''),
                    'to': record.get('to', {}).get('phoneNumber', 'Unknown'),
                    'to_name': record.get('to', {}).get('name', ''),
                    'to_extension': record.get('to', {}).get('extensionNumber', ''),
                    'recording_id': recording_info.get('id'),
                    'recording_uri': recording_info.get('contentUri'),
                    'recording_type': recording_info.get('type', 'Unknown')
                })

        print(f"\n📞 Recordings Available: {len(recordings_available)}")

        if recordings_available:
            # Group by date
            print(f"\n📅 Recordings by Date:")
            date_counts = {}
            for recording in recordings_available:
                date = recording['start_time'][:10] if recording['start_time'] else 'Unknown'
                date_counts[date] = date_counts.get(date, 0) + 1

            # Show last 10 dates
            for date in sorted(date_counts.keys(), reverse=True)[:10]:
                print(f"  {date}: {date_counts[date]} recordings")

            # Group by extension
            print(f"\n☎️ Recordings by Extension:")
            ext_counts = {}
            for recording in recordings_available:
                # Check both from and to extensions
                from_ext = recording.get('from_extension', '')
                to_ext = recording.get('to_extension', '')

                if from_ext:
                    ext_counts[from_ext] = ext_counts.get(from_ext, 0) + 1
                if to_ext and to_ext != from_ext:
                    ext_counts[to_ext] = ext_counts.get(to_ext, 0) + 1

            # Show top extensions
            for ext, count in sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
                print(f"  Extension {ext}: {count} recordings")

            # Show sample of recent recordings
            print(f"\n📞 Recent Recordings (showing first 10):")
            for i, recording in enumerate(recordings_available[:10], 1):
                duration_min = recording['duration'] // 60
                duration_sec = recording['duration'] % 60

                # Format from/to with extension if available
                from_info = recording['from_name'] or recording['from']
                if recording['from_extension']:
                    from_info = f"{from_info} (ext. {recording['from_extension']})"

                to_info = recording['to_name'] or recording['to']
                if recording['to_extension']:
                    to_info = f"{to_info} (ext. {recording['to_extension']})"

                print(f"\n  {i}. Recording ID: {recording['recording_id']}")
                print(f"     Date: {recording['start_time'][:19] if recording['start_time'] else 'Unknown'}")
                print(f"     Duration: {duration_min}:{duration_sec:02d}")
                print(f"     Direction: {recording['direction']}")
                print(f"     From: {from_info}")
                print(f"     To: {to_info}")

            # Calculate total duration
            total_duration = sum(r['duration'] for r in recordings_available)
            total_hours = total_duration // 3600
            total_minutes = (total_duration % 3600) // 60

            print(f"\n⏱️ Total Duration of All Recordings:")
            print(f"  {total_hours} hours {total_minutes} minutes")
            print(f"  ({len(recordings_available)} recordings)")

            # Estimate processing time
            est_processing = total_duration // 3  # Salad is fast
            est_hours = est_processing // 3600
            est_minutes = (est_processing % 3600) // 60

            print(f"\n⚡ Estimated Processing Time with Salad:")
            print(f"  {est_hours} hours {est_minutes} minutes")
            print(f"  (Approximately 1/3 of audio duration)")

            # Save queue details
            queue_file = '/var/www/call-recording-system/ringcentral_recordings.json'
            with open(queue_file, 'w') as f:
                json.dump({
                    'check_time': datetime.now().isoformat(),
                    'date_range': {
                        'from': start_date.isoformat(),
                        'to': end_date.isoformat()
                    },
                    'summary': {
                        'total_recordings': len(recordings_available),
                        'total_duration_seconds': total_duration,
                        'estimated_processing_seconds': est_processing,
                        'by_date': date_counts,
                        'by_extension': ext_counts
                    },
                    'recordings': recordings_available[:100]  # Save first 100
                }, f, indent=2, default=str)

            print(f"\n💾 Recording details saved to: {queue_file}")

        else:
            print("\n✅ No recordings found in the specified date range")

    except Exception as e:
        print(f"\n❌ Error checking recordings: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Logout
        try:
            platform.logout()
        except:
            pass

    print("\n" + "="*80)
    print("QUEUE CHECK COMPLETE")
    print("="*80)

if __name__ == "__main__":
    check_recordings()
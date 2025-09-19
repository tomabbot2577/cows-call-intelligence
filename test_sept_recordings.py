#!/usr/bin/env python3
"""
Test script to fetch RingCentral call logs with recordings for September 2025
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from src.config.settings import Settings
from src.ringcentral.auth import RingCentralAuth
from src.ringcentral.client import RingCentralClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def fetch_september_2025_recordings() -> List[Dict[str, Any]]:
    """
    Fetch all call recordings for September 2025

    Returns:
        List of call recordings with metadata
    """
    # Initialize settings
    settings = Settings()

    # Initialize RingCentral authentication
    logger.info("Initializing RingCentral authentication...")
    ringcentral_auth = RingCentralAuth(
        jwt_token=settings.ringcentral_jwt_token,
        client_id=settings.ringcentral_client_id,
        client_secret=settings.ringcentral_client_secret,
        sandbox=getattr(settings, 'ringcentral_sandbox', False)
    )

    # The auth handler will authenticate when needed
    logger.info("Creating RingCentral client...")

    # Create RingCentral client
    ringcentral_client = RingCentralClient(auth=ringcentral_auth)

    # Define date range for September 2025
    date_from = datetime(2025, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2025, 9, 30, 23, 59, 59, tzinfo=timezone.utc)

    logger.info(f"Fetching call logs from {date_from} to {date_to}")

    # Fetch all call logs with recordings
    recordings = []
    try:
        for record in ringcentral_client.get_all_call_logs(
            date_from=date_from,
            date_to=date_to,
            recording_type='All'
        ):
            recording_info = record.get('recording', {})

            # Extract key information
            call_info = {
                'call_id': record.get('id'),
                'session_id': record.get('sessionId'),
                'start_time': record.get('startTime'),
                'duration': record.get('duration'),
                'from_name': record.get('from', {}).get('name'),
                'from_number': record.get('from', {}).get('phoneNumber'),
                'to_name': record.get('to', {}).get('name'),
                'to_number': record.get('to', {}).get('phoneNumber'),
                'direction': record.get('direction'),
                'recording_id': recording_info.get('id'),
                'recording_uri': recording_info.get('uri'),
                'recording_type': recording_info.get('type'),
                'recording_duration': recording_info.get('duration')
            }

            recordings.append(call_info)

    except Exception as e:
        logger.error(f"Error fetching call logs: {e}")
        raise

    return recordings


def display_recordings(recordings: List[Dict[str, Any]]):
    """Display recordings in a formatted way"""

    if not recordings:
        print("\n❌ No recordings found for September 2025")
        return

    print(f"\n✅ Found {len(recordings)} call recordings for September 2025\n")
    print("=" * 100)

    for idx, recording in enumerate(recordings, 1):
        print(f"\n📞 Recording #{idx}")
        print("-" * 50)
        print(f"  Call ID: {recording['call_id']}")
        print(f"  Session ID: {recording['session_id']}")
        print(f"  Start Time: {recording['start_time']}")
        print(f"  Duration: {recording['duration']} seconds")
        print(f"  Direction: {recording['direction']}")
        print(f"  From: {recording['from_name']} ({recording['from_number']})")
        print(f"  To: {recording['to_name']} ({recording['to_number']})")
        print(f"  Recording ID: {recording['recording_id']}")
        print(f"  Recording Duration: {recording['recording_duration']} seconds")
        print(f"  Recording Type: {recording['recording_type']}")

        if idx >= 10 and len(recordings) > 10:
            remaining = len(recordings) - 10
            print(f"\n... and {remaining} more recordings")
            break

    print("\n" + "=" * 100)

    # Summary statistics
    total_duration = sum(r['recording_duration'] or 0 for r in recordings)
    avg_duration = total_duration / len(recordings) if recordings else 0

    print("\n📊 Summary Statistics:")
    print(f"  Total Recordings: {len(recordings)}")
    print(f"  Total Recording Duration: {total_duration} seconds ({total_duration/60:.1f} minutes)")
    print(f"  Average Recording Duration: {avg_duration:.1f} seconds")

    # Group by direction
    inbound = len([r for r in recordings if r['direction'] == 'Inbound'])
    outbound = len([r for r in recordings if r['direction'] == 'Outbound'])

    print(f"\n📈 Call Direction:")
    print(f"  Inbound: {inbound}")
    print(f"  Outbound: {outbound}")


def main():
    """Main function"""
    try:
        print("\n🔍 Testing RingCentral API - Fetching September 2025 Call Recordings")
        print("=" * 70)

        # Fetch recordings
        recordings = fetch_september_2025_recordings()

        # Display results
        display_recordings(recordings)

        # Save to JSON for further analysis
        if recordings:
            import json
            output_file = "september_2025_recordings.json"
            with open(output_file, 'w') as f:
                json.dump(recordings, f, indent=2, default=str)
            print(f"\n💾 Full recording list saved to: {output_file}")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"\n❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    main()
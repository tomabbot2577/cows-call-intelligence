#!/usr/bin/env python3
"""
RingCentral Call Log Checker v2
Tracks ALL calls (with or without recordings) for complete workflow visibility
Runs every 12 hours via cron

Updated: 2025-12-21
"""

import os
import sys
import json
import logging
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directory to path
sys.path.insert(0, '/var/www/call-recording-system')

from ringcentral import SDK

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RingCentralCheckerV2:
    """
    Checks RingCentral for ALL calls and downloads recordings.
    Tracks missed calls, voicemails, abandoned calls, etc.
    """

    def __init__(self):
        """Initialize the RingCentral checker"""

        # Load environment variables (support both RC_ and RINGCENTRAL_ prefixes)
        self.client_id = os.getenv('RC_CLIENT_ID') or os.getenv('RINGCENTRAL_CLIENT_ID')
        self.client_secret = os.getenv('RC_CLIENT_SECRET') or os.getenv('RINGCENTRAL_CLIENT_SECRET')
        self.jwt_token = os.getenv('RC_JWT_TOKEN') or os.getenv('RINGCENTRAL_JWT_TOKEN')
        self.server_url = os.getenv('RC_SERVER_URL') or os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')

        # Database connection - use call_insights database (not call_recordings from DATABASE_URL)
        self.db_url = '" + os.getenv('DATABASE_URL', '')'

        if not all([self.client_id, self.client_secret, self.jwt_token]):
            raise ValueError("Missing required RingCentral credentials in environment")

        # Initialize SDK (positional args: key, secret, server)
        self.sdk = SDK(self.client_id, self.client_secret, self.server_url)

        # Authenticate
        self._authenticate()

        # Set up paths
        self.queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        self.queue_dir.mkdir(parents=True, exist_ok=True)

        # Load state
        self.state_file = Path('/var/www/call-recording-system/data/scheduler/last_check_v2.json')
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

        logger.info("RingCentralCheckerV2 initialized")

    def _authenticate(self):
        """Authenticate with RingCentral using JWT"""
        try:
            self.platform = self.sdk.platform()
            self.platform.login(jwt=self.jwt_token)
            logger.info("Successfully authenticated with RingCentral")
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise

    def _get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.db_url)

    def _load_state(self) -> Dict:
        """Load the last check timestamp and state"""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                return json.load(f)

        # Default state - check last 14 hours on first run (overlap for 12hr schedule)
        return {
            'last_check': (datetime.now(timezone.utc) - timedelta(hours=14)).isoformat(),
            'total_calls_logged': 0,
            'total_recordings_downloaded': 0
        }

    def _save_state(self):
        """Save the current state"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def _safe_get(self, obj, attr, default=None):
        """Safely get attribute from dict or JsonObject"""
        if obj is None:
            return default
        if hasattr(obj, attr):
            return getattr(obj, attr, default)
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return default

    def _to_dict(self, obj) -> Dict:
        """Convert JsonObject to dict recursively for JSON storage"""
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, list):
            return [self._to_dict(item) for item in obj]
        if isinstance(obj, dict):
            return {k: self._to_dict(v) for k, v in obj.items()}
        # JsonObject - convert by getting all non-private attributes
        result = {}
        for attr in dir(obj):
            if not attr.startswith('_'):
                try:
                    val = getattr(obj, attr)
                    if not callable(val):
                        result[attr] = self._to_dict(val)
                except:
                    pass
        return result

    def _extract_call_data(self, record) -> Dict:
        """
        Extract ALL relevant data from a RingCentral call log record.

        Args:
            record: Raw call log record from RingCentral API (JsonObject or dict)

        Returns:
            Structured call data dictionary
        """
        recording = self._safe_get(record, 'recording')
        from_party = self._safe_get(record, 'from') or getattr(record, 'from_', None)
        to_party = self._safe_get(record, 'to')
        legs = self._safe_get(record, 'legs')

        return {
            # RingCentral Identifiers
            'ringcentral_id': self._safe_get(record, 'id'),
            'session_id': self._safe_get(record, 'sessionId'),
            'telephony_session_id': self._safe_get(record, 'telephonySessionId'),

            # Timing
            'start_time': self._safe_get(record, 'startTime'),
            'duration_seconds': self._safe_get(record, 'duration', 0),

            # Call Classification
            'direction': self._safe_get(record, 'direction'),
            'call_type': self._safe_get(record, 'type'),
            'call_action': self._safe_get(record, 'action'),
            'call_result': self._safe_get(record, 'result'),

            # Caller (Customer) Information
            'from_phone_number': self._safe_get(from_party, 'phoneNumber'),
            'from_name': self._safe_get(from_party, 'name'),
            'from_location': self._safe_get(from_party, 'location'),
            'from_extension_number': self._safe_get(from_party, 'extensionNumber'),

            # Called Party (Employee) Information
            'to_phone_number': self._safe_get(to_party, 'phoneNumber'),
            'to_name': self._safe_get(to_party, 'name'),
            'to_location': self._safe_get(to_party, 'location'),
            'to_extension_number': self._safe_get(to_party, 'extensionNumber'),

            # Recording Information
            'has_recording': bool(recording),
            'recording_id': self._safe_get(recording, 'id') if recording else None,
            'recording_uri': self._safe_get(recording, 'uri') if recording else None,
            'recording_type': self._safe_get(recording, 'type') if recording else None,

            # Call Routing (legs for transfers)
            'call_legs': self._to_dict(legs) if legs else None,

            # Full metadata backup (convert to dict for JSON storage)
            'raw_metadata': self._to_dict(record)
        }

    def fetch_all_calls(self, hours_back: int = 14) -> List[Dict]:
        """
        Fetch ALL calls from RingCentral (with or without recordings).

        Args:
            hours_back: Hours to look back (default 14 for 12hr schedule overlap)

        Returns:
            List of call data dictionaries
        """
        last_check = datetime.fromisoformat(self.state['last_check'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)

        # Don't go back more than specified hours
        max_lookback = now - timedelta(hours=hours_back)
        date_from = max(last_check, max_lookback)

        logger.info(f"Fetching calls from {date_from.isoformat()} to {now.isoformat()}")

        all_calls = []
        page = 1
        per_page = 100

        try:
            while True:
                params = {
                    'dateFrom': date_from.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'dateTo': now.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'perPage': per_page,
                    'page': page,
                    'view': 'Detailed'  # Get all fields including legs, extensions
                }

                # Use account-level call log to get ALL extensions' calls
                response = self.platform.get('/account/~/call-log', params)
                data = response.json()

                # JsonObject uses attribute access, not dict access
                records = data.records if hasattr(data, 'records') else []
                if not records:
                    break

                for record in records:
                    call_data = self._extract_call_data(record)
                    all_calls.append(call_data)

                if len(records) < per_page:
                    break

                page += 1
                time.sleep(1)  # Rate limiting

        except Exception as e:
            logger.error(f"Error fetching calls: {e}")
            raise

        # Update state
        self.state['last_check'] = now.isoformat()
        self._save_state()

        logger.info(f"Found {len(all_calls)} total calls")
        return all_calls

    def save_call_to_db(self, call_data: Dict) -> bool:
        """
        Save a call record to the call_log table.

        Args:
            call_data: Extracted call data

        Returns:
            True if saved, False if duplicate
        """
        conn = self._get_db_connection()
        try:
            with conn.cursor() as cur:
                # Check for duplicate
                cur.execute(
                    "SELECT id FROM call_log WHERE ringcentral_id = %s",
                    (call_data['ringcentral_id'],)
                )
                if cur.fetchone():
                    return False  # Already exists

                # Parse start_time
                start_time = call_data['start_time']
                if isinstance(start_time, str):
                    start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))

                # Insert new record
                cur.execute("""
                    INSERT INTO call_log (
                        ringcentral_id, session_id, telephony_session_id,
                        start_time, duration_seconds,
                        direction, call_type, call_action, call_result,
                        from_phone_number, from_name, from_location, from_extension_number,
                        to_phone_number, to_name, to_location, to_extension_number,
                        has_recording, recording_id, recording_uri, recording_type,
                        call_legs, raw_metadata
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    call_data['ringcentral_id'],
                    call_data['session_id'],
                    call_data['telephony_session_id'],
                    start_time,
                    call_data['duration_seconds'],
                    call_data['direction'],
                    call_data['call_type'],
                    call_data['call_action'],
                    call_data['call_result'],
                    call_data['from_phone_number'],
                    call_data['from_name'],
                    call_data['from_location'],
                    call_data['from_extension_number'],
                    call_data['to_phone_number'],
                    call_data['to_name'],
                    call_data['to_location'],
                    call_data['to_extension_number'],
                    call_data['has_recording'],
                    call_data['recording_id'],
                    call_data['recording_uri'],
                    call_data['recording_type'],
                    json.dumps(call_data['call_legs']) if call_data['call_legs'] else None,
                    json.dumps(call_data['raw_metadata'])
                ))

                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Database error saving call {call_data['ringcentral_id']}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def download_recording(self, call_data: Dict) -> Optional[str]:
        """
        Download recording audio for a call that has a recording.

        Args:
            call_data: Call data with recording info

        Returns:
            Path to downloaded file or None
        """
        if not call_data['has_recording'] or not call_data['recording_uri']:
            return None

        recording_id = call_data['ringcentral_id']
        output_path = self.queue_dir / f"{recording_id}.mp3"

        # Check if already downloaded
        if output_path.exists():
            logger.debug(f"Recording {recording_id} already in queue")
            return str(output_path)

        try:
            logger.info(f"Downloading recording {recording_id}")
            response = self.platform.get(call_data['recording_uri'])

            with open(output_path, 'wb') as f:
                f.write(response.body())

            file_size = output_path.stat().st_size
            logger.info(f"Downloaded {recording_id} ({file_size:,} bytes)")

            # Update call_log with download status
            conn = self._get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE call_log
                        SET audio_downloaded = TRUE, audio_download_time = NOW()
                        WHERE ringcentral_id = %s
                    """, (recording_id,))
                    conn.commit()
            finally:
                conn.close()

            return str(output_path)

        except Exception as e:
            logger.error(f"Error downloading {recording_id}: {e}")
            if output_path.exists():
                output_path.unlink()
            return None

    def run_check(self, hours_back: int = 14, download_recordings: bool = True) -> Dict:
        """
        Run a complete check cycle.

        Args:
            hours_back: Hours to look back
            download_recordings: Whether to download audio files

        Returns:
            Summary statistics
        """
        start_time = time.time()

        summary = {
            'check_time': datetime.now(timezone.utc).isoformat(),
            'total_calls_found': 0,
            'new_calls_logged': 0,
            'calls_with_recordings': 0,
            'recordings_downloaded': 0,
            'missed_calls': 0,
            'voicemails': 0,
            'answered_calls': 0,
            'errors': []
        }

        try:
            # Fetch all calls
            all_calls = self.fetch_all_calls(hours_back=hours_back)
            summary['total_calls_found'] = len(all_calls)

            for call_data in all_calls:
                # Count by result
                result = call_data.get('call_result', '').lower()
                if result == 'missed':
                    summary['missed_calls'] += 1
                elif result == 'voicemail':
                    summary['voicemails'] += 1
                elif result in ('accepted', 'call connected'):
                    summary['answered_calls'] += 1

                # Save to database
                if self.save_call_to_db(call_data):
                    summary['new_calls_logged'] += 1

                # Download recording if exists
                if call_data['has_recording']:
                    summary['calls_with_recordings'] += 1

                    if download_recordings:
                        time.sleep(5)  # Rate limit downloads
                        if self.download_recording(call_data):
                            summary['recordings_downloaded'] += 1

            # Update state
            self.state['total_calls_logged'] += summary['new_calls_logged']
            self.state['total_recordings_downloaded'] += summary['recordings_downloaded']
            self._save_state()

        except Exception as e:
            logger.error(f"Check cycle error: {e}")
            summary['errors'].append(str(e))

        elapsed = time.time() - start_time
        summary['elapsed_seconds'] = round(elapsed, 1)

        logger.info(f"Check complete in {elapsed:.1f}s: {summary}")

        # Save summary
        summary_file = Path('/var/www/call-recording-system/data/scheduler/check_summary_v2.json')
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        return summary

    def get_call_stats(self) -> Dict:
        """Get statistics from call_log table"""
        conn = self._get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_calls,
                        COUNT(*) FILTER (WHERE has_recording = TRUE) as with_recordings,
                        COUNT(*) FILTER (WHERE call_result = 'Missed') as missed,
                        COUNT(*) FILTER (WHERE call_result = 'Voicemail') as voicemails,
                        COUNT(*) FILTER (WHERE call_result IN ('Accepted', 'Call connected')) as answered,
                        COUNT(*) FILTER (WHERE call_result = 'No Answer') as no_answer,
                        COUNT(*) FILTER (WHERE call_result = 'Busy') as busy,
                        COUNT(*) FILTER (WHERE direction = 'Inbound') as inbound,
                        COUNT(*) FILTER (WHERE direction = 'Outbound') as outbound
                    FROM call_log
                """)
                return dict(cur.fetchone())
        finally:
            conn.close()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='RingCentral Call Log Checker v2')
    parser.add_argument('--hours-back', type=int, default=14,
                       help='Hours to look back (default 14)')
    parser.add_argument('--no-download', action='store_true',
                       help='Skip downloading recordings')
    parser.add_argument('--stats', action='store_true',
                       help='Show call statistics only')

    args = parser.parse_args()

    checker = RingCentralCheckerV2()

    if args.stats:
        stats = checker.get_call_stats()
        print("\n=== Call Log Statistics ===")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print()
    else:
        summary = checker.run_check(
            hours_back=args.hours_back,
            download_recordings=not args.no_download
        )
        print(f"\nCheck complete:")
        print(f"  Total calls found: {summary['total_calls_found']}")
        print(f"  New calls logged: {summary['new_calls_logged']}")
        print(f"  Missed calls: {summary['missed_calls']}")
        print(f"  Voicemails: {summary['voicemails']}")
        print(f"  Recordings downloaded: {summary['recordings_downloaded']}")


if __name__ == '__main__':
    main()

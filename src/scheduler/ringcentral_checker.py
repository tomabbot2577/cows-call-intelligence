#!/usr/bin/env python3
"""
RingCentral Scheduled Checker
Runs 5-8 times per day to check for new recordings
"""

import os
import sys
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directory to path
sys.path.insert(0, '/var/www/call-recording-system')

from ringcentral import SDK
from src.database.models import Recording, ProcessingStatus
from src.database.session import SessionLocal
from sqlalchemy import func

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RingCentralChecker:
    """
    Periodically checks RingCentral for new call recordings
    and downloads them to the queue
    """

    def __init__(self):
        """Initialize the RingCentral checker"""

        # Load environment variables
        self.client_id = os.getenv('RC_CLIENT_ID')
        self.client_secret = os.getenv('RC_CLIENT_SECRET')
        self.jwt_token = os.getenv('RC_JWT_TOKEN')
        self.server_url = os.getenv('RC_SERVER_URL', 'https://platform.ringcentral.com')

        if not all([self.client_id, self.client_secret, self.jwt_token]):
            raise ValueError("Missing required RingCentral credentials in environment")

        # Initialize SDK
        self.sdk = SDK(
            client_id=self.client_id,
            client_secret=self.client_secret,
            server_url=self.server_url
        )

        # Authenticate
        self._authenticate()

        # Set up paths
        self.queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        self.queue_dir.mkdir(parents=True, exist_ok=True)

        # Load state
        self.state_file = Path('/var/www/call-recording-system/data/scheduler/last_check.json')
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

        # Cache for known recordings (to avoid repeated DB checks)
        self.known_recordings = set()
        self._load_known_recordings()

        logger.info("RingCentralChecker initialized")

    def _authenticate(self):
        """Authenticate with RingCentral using JWT"""
        try:
            self.platform = self.sdk.platform()
            self.platform.login(jwt=self.jwt_token)
            logger.info("Successfully authenticated with RingCentral")
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise

    def _load_state(self) -> Dict:
        """Load the last check timestamp and state"""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                return json.load(f)

        # Default state - check last 7 days on first run
        return {
            'last_check': (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
            'last_recording_date': None,
            'total_downloaded': 0,
            'total_checked': 0
        }

    def _save_state(self):
        """Save the current state"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def _load_known_recordings(self):
        """Load known recording IDs into memory for fast duplicate checking"""
        db = SessionLocal()
        try:
            # Load all recording IDs from the last 30 days
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            recordings = db.query(Recording.ringcentral_id).filter(
                Recording.created_at >= cutoff_date
            ).all()

            self.known_recordings = {r.ringcentral_id for r in recordings}
            logger.info(f"Loaded {len(self.known_recordings)} known recording IDs")
        finally:
            db.close()

    def _is_known_recording(self, recording_id: str) -> bool:
        """Quick check if recording ID is already known"""
        return recording_id in self.known_recordings

    def check_for_new_recordings(self, hours_back: int = 24) -> List[Dict]:
        """
        Check for new recordings since last check

        Args:
            hours_back: Maximum hours to look back (default 24)

        Returns:
            List of new recording metadata
        """
        # Calculate date range
        last_check = datetime.fromisoformat(self.state['last_check'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)

        # Don't go back more than specified hours
        max_lookback = now - timedelta(hours=hours_back)
        date_from = max(last_check, max_lookback)

        logger.info(f"Checking for recordings from {date_from.isoformat()} to {now.isoformat()}")

        new_recordings = []
        page = 1
        per_page = 100

        try:
            while True:
                # API request parameters
                params = {
                    'dateFrom': date_from.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'dateTo': now.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'perPage': per_page,
                    'page': page,
                    'view': 'Detailed'
                }

                # Make API request
                response = self.platform.get('/account/~/extension/~/call-log', params)
                data = response.json()

                records = data.get('records', [])
                if not records:
                    break

                # Process each call record
                for record in records:
                    # Check if recording exists
                    if record.get('recording'):
                        recording_id = record.get('id')

                        # Quick duplicate check before adding to list
                        if self._is_known_recording(recording_id):
                            logger.debug(f"Skipping known recording {recording_id}")
                            continue

                        recording_info = {
                            'id': recording_id,
                            'uri': record.get('recording', {}).get('uri'),
                            'sessionId': record.get('sessionId'),
                            'startTime': record.get('startTime'),
                            'duration': record.get('duration', 0),
                            'direction': record.get('direction'),
                            'from': record.get('from', {}),
                            'to': record.get('to', {}),
                            'type': record.get('type')
                        }
                        new_recordings.append(recording_info)

                # Check if more pages
                if len(records) < per_page:
                    break

                page += 1

                # Rate limiting
                time.sleep(2)

        except Exception as e:
            logger.error(f"Error checking for recordings: {e}")
            raise

        # Update state
        self.state['last_check'] = now.isoformat()
        self.state['total_checked'] += len(new_recordings)
        self._save_state()

        logger.info(f"Found {len(new_recordings)} new recordings")
        return new_recordings

    def download_recording(self, recording_info: Dict) -> Optional[str]:
        """
        Download a single recording to the queue with duplicate checking

        Args:
            recording_info: Recording metadata

        Returns:
            Path to downloaded file or None if failed/duplicate
        """
        recording_id = recording_info['id']
        session_id = recording_info.get('sessionId')

        # DUPLICATE CHECK 1: Check if file already exists in queue
        output_path = self.queue_dir / f"{recording_id}.mp3"
        if output_path.exists():
            logger.info(f"Recording {recording_id} already in queue (file exists)")
            return str(output_path)

        # DUPLICATE CHECK 2: Check database by RingCentral ID
        db = SessionLocal()
        try:
            existing = db.query(Recording).filter_by(
                ringcentral_id=recording_id
            ).first()

            if existing:
                logger.info(f"Recording {recording_id} already in database (status: {existing.status})")
                return None

            # DUPLICATE CHECK 3: Check by session ID (same call, different ID)
            if session_id:
                session_duplicate = db.query(Recording).filter_by(
                    session_id=session_id
                ).first()

                if session_duplicate:
                    logger.info(f"Recording {recording_id} is duplicate of {session_duplicate.ringcentral_id} (same session)")
                    return None

            # DUPLICATE CHECK 4: Check by call details (time, numbers, duration)
            start_time = datetime.fromisoformat(
                recording_info['startTime'].replace('Z', '+00:00')
            )
            from_number = recording_info['from'].get('phoneNumber')
            to_number = recording_info['to'].get('phoneNumber')
            duration = recording_info['duration']

            # Check for calls within 5 seconds with same numbers and duration
            time_window_start = start_time - timedelta(seconds=5)
            time_window_end = start_time + timedelta(seconds=5)

            detail_duplicate = db.query(Recording).filter(
                Recording.start_time >= time_window_start,
                Recording.start_time <= time_window_end,
                Recording.from_number == from_number,
                Recording.to_number == to_number,
                Recording.duration == duration
            ).first()

            if detail_duplicate:
                logger.info(f"Recording {recording_id} matches existing call {detail_duplicate.ringcentral_id} (same time/numbers/duration)")
                return None

        finally:
            db.close()

        # Download the recording
        try:
            logger.info(f"Downloading recording {recording_id}")

            # Get recording content
            response = self.platform.get(recording_info['uri'])

            # Save to file
            with open(output_path, 'wb') as f:
                f.write(response.body())

            # Add to database
            self._add_to_database(recording_info, output_path)

            # Update state
            self.state['total_downloaded'] += 1

            logger.info(f"Downloaded {recording_id} ({output_path.stat().st_size:,} bytes)")
            return str(output_path)

        except Exception as e:
            logger.error(f"Error downloading {recording_id}: {e}")
            if output_path.exists():
                output_path.unlink()
            return None

    def _add_to_database(self, recording_info: Dict, file_path: Path):
        """Add recording to database"""
        db = SessionLocal()
        try:
            recording = Recording(
                ringcentral_id=recording_info['id'],
                session_id=recording_info.get('sessionId'),
                start_time=datetime.fromisoformat(
                    recording_info['startTime'].replace('Z', '+00:00')
                ),
                duration=recording_info['duration'],
                direction=recording_info['direction'],
                from_number=recording_info['from'].get('phoneNumber'),
                from_name=recording_info['from'].get('name'),
                to_number=recording_info['to'].get('phoneNumber'),
                to_name=recording_info['to'].get('name'),
                call_type=recording_info['type'],
                audio_path=str(file_path),
                status=ProcessingStatus.DOWNLOADED,
                metadata=json.dumps(recording_info)
            )

            db.add(recording)
            db.commit()

            logger.info(f"Added recording {recording_info['id']} to database")

        except Exception as e:
            logger.error(f"Database error: {e}")
            db.rollback()
        finally:
            db.close()

    def run_check(self, download_limit: int = 50) -> Dict:
        """
        Run a single check cycle

        Args:
            download_limit: Maximum recordings to download in this run

        Returns:
            Summary of the check
        """
        start_time = time.time()
        summary = {
            'check_time': datetime.now(timezone.utc).isoformat(),
            'recordings_found': 0,
            'recordings_downloaded': 0,
            'errors': []
        }

        try:
            # Check for new recordings
            new_recordings = self.check_for_new_recordings()
            summary['recordings_found'] = len(new_recordings)

            # Download recordings (with limit)
            downloaded = 0
            for recording in new_recordings[:download_limit]:
                # Rate limiting
                time.sleep(20)  # 20 seconds between downloads

                result = self.download_recording(recording)
                if result:
                    downloaded += 1

                if downloaded >= download_limit:
                    logger.info(f"Reached download limit of {download_limit}")
                    break

            summary['recordings_downloaded'] = downloaded

            # Save state
            self._save_state()

        except Exception as e:
            logger.error(f"Check cycle error: {e}")
            summary['errors'].append(str(e))

        # Log summary
        elapsed = time.time() - start_time
        logger.info(f"Check complete in {elapsed:.1f}s: {summary}")

        # Save summary
        summary_file = Path('/var/www/call-recording-system/data/scheduler/check_summary.json')
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        return summary

    def get_queue_status(self) -> Dict:
        """Get status of the recording queue"""
        db = SessionLocal()
        try:
            status = {
                'queue_size': len(list(self.queue_dir.glob('*.mp3'))),
                'downloaded': db.query(Recording).filter_by(
                    status=ProcessingStatus.DOWNLOADED
                ).count(),
                'transcribing': db.query(Recording).filter_by(
                    status=ProcessingStatus.TRANSCRIBING
                ).count(),
                'completed': db.query(Recording).filter_by(
                    status=ProcessingStatus.COMPLETED
                ).count(),
                'failed': db.query(Recording).filter_by(
                    status=ProcessingStatus.FAILED
                ).count()
            }
            return status
        finally:
            db.close()


def main():
    """Main entry point for manual execution"""
    import argparse

    parser = argparse.ArgumentParser(description='Check RingCentral for new recordings')
    parser.add_argument('--limit', type=int, default=50,
                       help='Maximum recordings to download')
    parser.add_argument('--hours-back', type=int, default=24,
                       help='Maximum hours to look back')
    parser.add_argument('--status', action='store_true',
                       help='Show queue status only')

    args = parser.parse_args()

    # Initialize checker
    checker = RingCentralChecker()

    if args.status:
        # Show status
        status = checker.get_queue_status()
        print("\n=== Recording Queue Status ===")
        for key, value in status.items():
            print(f"  {key}: {value}")
        print()
    else:
        # Run check
        summary = checker.run_check(download_limit=args.limit)
        print(f"\nCheck complete: {summary['recordings_downloaded']} downloaded")


if __name__ == '__main__':
    main()
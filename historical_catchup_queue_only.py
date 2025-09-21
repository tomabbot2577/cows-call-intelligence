#!/usr/bin/env python3
"""
Historical Catchup: Queue Only Version
This version queues recordings for processing without downloading
Submits recordings to Salad in batches with proper rate limiting
"""

import os
import sys
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
import time
from collections import defaultdict

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
from ringcentral import SDK

from src.database.session import SessionManager
from src.database.models import CallRecording

# Load environment
load_dotenv('/var/www/call-recording-system/.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('historical_queue.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class HistoricalQueueProcessor:
    """Queue historical recordings for later processing"""

    def __init__(self):
        """Initialize the processor"""
        self.stats = defaultdict(int)
        self.stats['start_time'] = datetime.now()

        # Initialize database
        self.session_mgr = SessionManager(os.getenv('DATABASE_URL'))
        logger.info("✅ Database initialized")

    def get_processed_recording_ids(self) -> Set[str]:
        """Get set of already processed recording IDs from database"""
        logger.info("Checking database for existing recordings...")

        processed_ids = set()
        try:
            with self.session_mgr.get_session() as session:
                # Get all recordings already in database
                existing = session.query(CallRecording.recording_id).all()
                processed_ids = {r.recording_id for r in existing if r.recording_id}
                logger.info(f"Found {len(processed_ids)} recordings already in database")
        except Exception as e:
            logger.warning(f"Could not check database: {e}")

        return processed_ids

    def fetch_ringcentral_recordings(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Fetch recordings from RingCentral for date range"""
        logger.info(f"\n📅 Fetching recordings from {start_date.date()} to {end_date.date()}")

        # Initialize RingCentral SDK
        rcsdk = SDK(
            os.getenv('RINGCENTRAL_CLIENT_ID'),
            os.getenv('RINGCENTRAL_CLIENT_SECRET'),
            os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')
        )

        platform = rcsdk.platform()

        try:
            # Authenticate with JWT
            platform.login(jwt=os.getenv('RINGCENTRAL_JWT_TOKEN'))
            logger.info("✅ Authenticated with RingCentral")

            # Format dates for API
            date_from = start_date.strftime('%Y-%m-%dT00:00:00.000Z')
            date_to = end_date.strftime('%Y-%m-%dT23:59:59.999Z')

            # Fetch call logs with recordings
            all_recordings = []
            page = 1
            per_page = 1000

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
                        'perPage': per_page,
                        'page': page
                    }
                )

                data = response.json()

                # Handle SDK response format
                if hasattr(data, '__dict__'):
                    records = data.records if hasattr(data, 'records') else []
                    navigation = data.navigation if hasattr(data, 'navigation') else {}
                else:
                    records = data.get('records', [])
                    navigation = data.get('navigation', {})

                # Process records with recordings
                for record in records:
                    # Handle SDK object format
                    if hasattr(record, 'recording'):
                        recording_info = record.recording
                        if recording_info:
                            all_recordings.append(self._extract_recording_info(record, recording_info))
                    elif isinstance(record, dict) and record.get('recording'):
                        recording_info = record['recording']
                        if recording_info:
                            all_recordings.append(self._extract_recording_info_dict(record, recording_info))

                # Check if there are more pages
                has_next = False
                if hasattr(navigation, 'nextPage'):
                    has_next = bool(navigation.nextPage)
                elif isinstance(navigation, dict):
                    has_next = bool(navigation.get('nextPage'))

                if not has_next:
                    break

                page += 1
                time.sleep(0.5)  # Rate limiting between pages

            logger.info(f"✅ Found {len(all_recordings)} total recordings with audio")
            return all_recordings

        except Exception as e:
            logger.error(f"Error fetching recordings: {e}")
            raise
        finally:
            try:
                platform.logout()
            except:
                pass

    def _extract_recording_info(self, record, recording_info) -> Dict[str, Any]:
        """Extract recording info from SDK object"""
        # Handle 'from' field (reserved word in Python)
        from_obj = getattr(record, 'from_', None) or getattr(record, 'from', None)
        from_phone = getattr(from_obj, 'phoneNumber', 'Unknown') if from_obj else 'Unknown'
        from_name = getattr(from_obj, 'name', '') if from_obj else ''
        from_ext = getattr(from_obj, 'extensionNumber', '') if from_obj else ''

        # Handle 'to' field
        to_obj = getattr(record, 'to', None)
        to_phone = getattr(to_obj, 'phoneNumber', 'Unknown') if to_obj else 'Unknown'
        to_name = getattr(to_obj, 'name', '') if to_obj else ''
        to_ext = getattr(to_obj, 'extensionNumber', '') if to_obj else ''

        return {
            'id': getattr(record, 'id', None),
            'session_id': getattr(record, 'sessionId', None),
            'start_time': getattr(record, 'startTime', None),
            'duration': getattr(record, 'duration', 0),
            'direction': getattr(record, 'direction', None),
            'from': from_phone,
            'from_name': from_name,
            'from_extension': from_ext,
            'to': to_phone,
            'to_name': to_name,
            'to_extension': to_ext,
            'recording_id': getattr(recording_info, 'id', None),
            'recording_uri': getattr(recording_info, 'contentUri', None),
            'recording_type': getattr(recording_info, 'type', 'Unknown')
        }

    def _extract_recording_info_dict(self, record: dict, recording_info: dict) -> Dict[str, Any]:
        """Extract recording info from dictionary"""
        return {
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
        }

    def queue_recording(self, recording: Dict[str, Any]) -> bool:
        """Add recording to database queue for later processing"""
        recording_id = recording['recording_id']

        try:
            with self.session_mgr.get_session() as session:
                # Check if already exists
                existing = session.query(CallRecording).filter_by(
                    recording_id=recording_id
                ).first()

                if existing:
                    self.stats['already_exists'] += 1
                    return False

                # Create new record with minimal fields
                db_record = CallRecording(
                    call_id=recording['id'],
                    recording_id=recording_id,
                    session_id=recording['session_id'],
                    start_time=datetime.fromisoformat(
                        recording['start_time'].replace('Z', '+00:00')
                    ) if recording['start_time'] else datetime.now(timezone.utc),
                    duration=recording['duration'],
                    from_number=recording['from'],
                    from_name=recording['from_name'],
                    to_number=recording['to'],
                    to_name=recording['to_name'],
                    direction=recording['direction'],
                    recording_type=recording['recording_type'],
                    download_status='pending',
                    transcription_status='pending',
                    upload_status='pending'
                )
                session.add(db_record)
                session.commit()

                self.stats['queued'] += 1
                return True

        except Exception as e:
            logger.error(f"Failed to queue {recording_id}: {e}")
            self.stats['failed'] += 1
            return False

    def run(self):
        """Run the queue-only historical catchup process"""
        print("\n" + "="*80)
        print("🚀 HISTORICAL CATCHUP - QUEUE ONLY")
        print("   This will add recordings to database for later processing")
        print("="*80)

        # Set date range
        start_date = datetime(2025, 6, 1, tzinfo=timezone.utc)
        end_date = datetime(2025, 9, 18, 23, 59, 59, tzinfo=timezone.utc)

        print(f"\n📅 Date Range:")
        print(f"  From: {start_date.strftime('%Y-%m-%d')}")
        print(f"  To: {end_date.strftime('%Y-%m-%d')}")

        try:
            # 1. Get already processed recordings
            existing_ids = self.get_processed_recording_ids()

            # 2. Fetch all recordings from RingCentral
            all_recordings = self.fetch_ringcentral_recordings(start_date, end_date)
            self.stats['total_found'] = len(all_recordings)

            # 3. Filter out already processed
            new_recordings = [r for r in all_recordings if r['recording_id'] not in existing_ids]
            self.stats['already_in_db'] = len(all_recordings) - len(new_recordings)

            print(f"\n📊 Queue Summary:")
            print(f"  Total recordings found: {len(all_recordings)}")
            print(f"  Already in database: {self.stats['already_in_db']}")
            print(f"  📌 New recordings to queue: {len(new_recordings)}")

            if not new_recordings:
                print("\n✅ All recordings already in database!")
                return

            # Calculate total duration
            total_duration = sum(r['duration'] for r in new_recordings)
            print(f"\n⏱️ Total Duration:")
            print(f"  Audio: {total_duration // 3600}h {(total_duration % 3600) // 60}m")
            print(f"  Estimated processing: {(total_duration // 3) // 3600}h {((total_duration // 3) % 3600) // 60}m")

            print(f"\n🔄 Adding {len(new_recordings)} recordings to queue...")

            # 4. Queue each recording
            for i, recording in enumerate(new_recordings, 1):
                success = self.queue_recording(recording)

                # Show progress every 100 recordings
                if i % 100 == 0 or i == len(new_recordings):
                    print(f"  Progress: {i}/{len(new_recordings)} ({i/len(new_recordings)*100:.1f}%)")
                    print(f"    Queued: {self.stats['queued']}, Already exists: {self.stats['already_exists']}, Failed: {self.stats['failed']}")

            # 5. Final summary
            elapsed = (datetime.now() - self.stats['start_time']).total_seconds()

            print("\n" + "="*80)
            print("📊 QUEUE OPERATION COMPLETE")
            print("="*80)
            print(f"  Total Found: {self.stats['total_found']}")
            print(f"  Already in DB: {self.stats['already_in_db']}")
            print(f"  ✅ Newly Queued: {self.stats['queued']}")
            print(f"  ⚠️ Already Existed: {self.stats['already_exists']}")
            print(f"  ❌ Failed: {self.stats['failed']}")
            print(f"  ⏱️ Time Taken: {elapsed:.1f} seconds")

            # Save summary
            summary_file = '/var/www/call-recording-system/queue_summary.json'

            # Convert stats to JSON-serializable format
            stats_json = {}
            for k, v in self.stats.items():
                if isinstance(v, datetime):
                    stats_json[k] = v.isoformat()
                else:
                    stats_json[k] = v

            with open(summary_file, 'w') as f:
                json.dump({
                    'run_date': datetime.now().isoformat(),
                    'date_range': {
                        'from': start_date.isoformat(),
                        'to': end_date.isoformat()
                    },
                    'stats': stats_json,
                    'elapsed_seconds': elapsed,
                    'recordings_queued': self.stats['queued']
                }, f, indent=2)

            print(f"\n💾 Summary saved to: {summary_file}")
            print("\n✨ Queue operation complete!")
            print(f"📋 {self.stats['queued']} recordings ready for processing")
            print("\n📌 Next step: Run process_queue.py to download and transcribe")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            import traceback
            traceback.print_exc()
            raise


def main():
    """Main entry point"""
    processor = HistoricalQueueProcessor()
    processor.run()


if __name__ == "__main__":
    main()
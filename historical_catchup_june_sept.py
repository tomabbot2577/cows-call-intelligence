#!/usr/bin/env python3
"""
Historical Catchup: June 1 - September 18, 2025
Loads all recordings into Salad transcription queue
Checks for already processed recordings to avoid duplicates
"""

import os
import sys
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
import time
import tempfile

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
from ringcentral import SDK

from src.database.session import SessionManager
from src.database.models import CallRecording
from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
from src.storage.structured_data_organizer import StructuredDataOrganizer
from src.storage.google_drive import GoogleDriveManager

# Load environment
load_dotenv('/var/www/call-recording-system/.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HistoricalCatchupProcessor:
    """Process historical recordings from June-Sept 2025"""

    def __init__(self):
        """Initialize the processor"""
        self.stats = {
            'total_found': 0,
            'already_processed': 0,
            'new_recordings': 0,
            'downloaded': 0,
            'transcribed': 0,
            'uploaded': 0,
            'failed': 0,
            'start_time': datetime.now()
        }

        # Initialize components
        self._initialize_components()

    def _initialize_components(self):
        """Initialize all required components"""
        logger.info("Initializing components...")

        # Database
        self.session_mgr = SessionManager(os.getenv('DATABASE_URL'))

        # Salad Transcriber
        self.transcriber = SaladTranscriberEnhanced(
            organization_name='mst',
            enable_diarization=True,
            enable_summarization=True
        )

        # Data organizer
        self.organizer = StructuredDataOrganizer()

        # Google Drive handler
        self.drive_handler = GoogleDriveManager(
            credentials_path=os.getenv('GOOGLE_CREDENTIALS_PATH'),
            impersonate_email=os.getenv('GOOGLE_IMPERSONATE_EMAIL')
        )

        logger.info("✅ All components initialized")

    def get_processed_recording_ids(self) -> Set[str]:
        """Get set of already processed recording IDs from database"""
        logger.info("Checking database for already processed recordings...")

        processed_ids = set()
        try:
            with self.session_mgr.get_session() as session:
                # Get recordings that are already processed or in progress
                processed = session.query(CallRecording.recording_id).filter(
                    CallRecording.transcription_status.in_([
                        'completed',
                        'processing',
                        'uploaded'
                    ])
                ).all()

                processed_ids = {r.recording_id for r in processed if r.recording_id}
                logger.info(f"Found {len(processed_ids)} already processed recordings")
        except Exception as e:
            logger.warning(f"Could not check database: {e}")

        return processed_ids

    def fetch_ringcentral_recordings(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Fetch recordings from RingCentral for date range"""
        logger.info(f"Fetching recordings from {start_date.date()} to {end_date.date()}")

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
                logger.info(f"Fetching page {page}...")

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
                time.sleep(0.5)  # Rate limiting

            logger.info(f"✅ Found {len(all_recordings)} total recordings")
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

    def download_recording(self, recording_uri: str, recording_id: str) -> Optional[bytes]:
        """Download recording audio from RingCentral"""
        logger.info(f"  ⬇️ Downloading recording {recording_id}...")

        # Initialize RingCentral SDK for download
        rcsdk = SDK(
            os.getenv('RINGCENTRAL_CLIENT_ID'),
            os.getenv('RINGCENTRAL_CLIENT_SECRET'),
            os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')
        )

        platform = rcsdk.platform()

        try:
            # Authenticate
            platform.login(jwt=os.getenv('RINGCENTRAL_JWT_TOKEN'))

            # Download recording
            response = platform.get(recording_uri)

            if response.status_code == 200:
                audio_data = response.content
                logger.info(f"  ✅ Downloaded {len(audio_data):,} bytes")
                return audio_data
            else:
                logger.error(f"  ❌ Download failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"  ❌ Download error: {e}")
            return None
        finally:
            try:
                platform.logout()
            except:
                pass

    def process_recording(self, recording: Dict[str, Any], index: int, total: int) -> bool:
        """Process a single recording through the complete pipeline"""
        recording_id = recording['recording_id']

        logger.info(f"\n{'='*60}")
        logger.info(f"📞 [{index}/{total}] Processing {recording_id}")
        logger.info(f"  From: {recording['from_name'] or recording['from']}")
        logger.info(f"  To: {recording['to_name'] or recording['to']}")
        logger.info(f"  Duration: {recording['duration']}s")
        logger.info(f"  Date: {recording['start_time'][:10] if recording['start_time'] else 'Unknown'}")

        try:
            # 1. Download recording
            audio_data = self.download_recording(recording['recording_uri'], recording_id)
            if not audio_data:
                logger.error("  ❌ Failed to download")
                self.stats['failed'] += 1
                return False

            self.stats['downloaded'] += 1

            # 2. Save to database
            with self.session_mgr.get_session() as session:
                # Check if already exists
                existing = session.query(CallRecording).filter_by(
                    recording_id=recording_id
                ).first()

                if existing:
                    db_record = existing
                    logger.info("  📄 Updating existing database record")
                else:
                    # Create new record
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
                        download_status='completed',
                        download_completed_at=datetime.now(timezone.utc),
                        file_size_bytes=len(audio_data),
                        transcription_status='processing'
                    )
                    session.add(db_record)
                    logger.info("  📄 Created new database record")

                session.commit()
                db_record_id = db_record.id

            # 3. Submit to Salad for transcription
            logger.info("  🎤 Submitting to Salad for transcription...")

            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                tmp_file.write(audio_data)
                tmp_file_path = tmp_file.name

            try:
                # Submit transcription job
                job_result = self.transcriber.transcribe(
                    audio_file=tmp_file_path,
                    job_name=f"recording_{recording_id}"
                )

                if job_result and job_result.get('transcription'):
                    logger.info(f"  ✅ Transcription complete: {len(job_result['transcription'])} chars")
                    self.stats['transcribed'] += 1

                    # 4. Organize and enrich data
                    logger.info("  📊 Organizing data...")

                    # Create document for organization
                    document = {
                        'recording_id': recording_id,
                        'call_id': recording['id'],
                        'session_id': recording['session_id'],
                        'start_time': recording['start_time'],
                        'duration': recording['duration'],
                        'caller': {
                            'name': recording['from_name'] or 'Unknown',
                            'number': recording['from'],
                            'extension': recording['from_extension']
                        },
                        'recipient': {
                            'name': recording['to_name'] or 'Unknown',
                            'number': recording['to'],
                            'extension': recording['to_extension']
                        },
                        'direction': recording['direction'],
                        'transcription': job_result['transcription'],
                        'summary': job_result.get('summary'),
                        'diarization': job_result.get('diarization'),
                        'sentiment': job_result.get('sentiment'),
                        'entities': job_result.get('entities', []),
                        'topics': job_result.get('topics', []),
                        'action_items': job_result.get('action_items', []),
                        'processed_at': datetime.now(timezone.utc).isoformat()
                    }

                    # Organize files
                    organized_files = self.organizer.organize_document(document, audio_data)

                    # 5. Upload to Google Drive
                    logger.info("  ☁️ Uploading to Google Drive...")

                    upload_count = 0
                    for file_info in organized_files:
                        try:
                            # Create temp file for upload
                            with tempfile.NamedTemporaryFile(suffix=file_info.get('extension', ''), delete=False) as tmp:
                                tmp.write(file_info['data'])
                                tmp_path = tmp.name

                            # Ensure folder exists
                            folder_id = self.drive_handler.get_or_create_folder(
                                file_info.get('folder_path', ''),
                                os.getenv('GOOGLE_DRIVE_FOLDER_ID')
                            )

                            # Upload file
                            file_id = self.drive_handler.upload_file(
                                file_path=tmp_path,
                                file_name=file_info['name'],
                                folder_id=folder_id
                            )

                            # Clean up temp file
                            try:
                                os.unlink(tmp_path)
                            except:
                                pass

                            if file_id:
                                upload_count += 1
                        except Exception as e:
                            logger.warning(f"  ⚠️ Failed to upload {file_info['name']}: {e}")

                    logger.info(f"  ✅ Uploaded {upload_count}/{len(organized_files)} files")
                    self.stats['uploaded'] += 1

                    # 6. Update database
                    with self.session_mgr.get_session() as session:
                        db_record = session.get(CallRecording, db_record_id)
                        db_record.transcription_status = 'completed'
                        db_record.transcription_text = job_result['transcription']
                        db_record.transcription_completed_at = datetime.now(timezone.utc)
                        db_record.upload_status = 'completed'
                        db_record.upload_completed_at = datetime.now(timezone.utc)
                        session.commit()

                    logger.info("  ✅ Successfully processed!")
                    self.stats['new_recordings'] += 1
                    return True

                else:
                    logger.error("  ❌ Transcription failed")
                    self.stats['failed'] += 1
                    return False

            finally:
                # Clean up temp file
                try:
                    os.unlink(tmp_file_path)
                except:
                    pass

        except Exception as e:
            logger.error(f"  ❌ Processing failed: {e}")
            self.stats['failed'] += 1

            # Update database with failure
            try:
                with self.session_mgr.get_session() as session:
                    db_record = session.get(CallRecording, db_record_id)
                    if db_record:
                        db_record.transcription_status = 'failed'
                        db_record.error_message = str(e)
                        session.commit()
            except:
                pass

            return False

    def run(self):
        """Run the historical catchup process"""
        print("\n" + "="*80)
        print("🚀 HISTORICAL CATCHUP - JUNE 1 TO SEPTEMBER 18, 2025")
        print("="*80)

        # Set date range
        start_date = datetime(2025, 6, 1, tzinfo=timezone.utc)
        end_date = datetime(2025, 9, 18, 23, 59, 59, tzinfo=timezone.utc)

        print(f"\n📅 Date Range:")
        print(f"  From: {start_date.strftime('%Y-%m-%d')}")
        print(f"  To: {end_date.strftime('%Y-%m-%d')}")

        try:
            # 1. Get already processed recordings
            processed_ids = self.get_processed_recording_ids()

            # 2. Fetch all recordings from RingCentral
            all_recordings = self.fetch_ringcentral_recordings(start_date, end_date)
            self.stats['total_found'] = len(all_recordings)

            # 3. Filter out already processed
            new_recordings = [r for r in all_recordings if r['recording_id'] not in processed_ids]
            self.stats['already_processed'] = len(all_recordings) - len(new_recordings)

            print(f"\n📊 Queue Summary:")
            print(f"  Total recordings found: {len(all_recordings)}")
            print(f"  Already processed: {self.stats['already_processed']}")
            print(f"  📌 New recordings to process: {len(new_recordings)}")

            if not new_recordings:
                print("\n✅ All recordings already processed!")
                return

            # Calculate estimated time
            total_duration = sum(r['duration'] for r in new_recordings)
            est_processing_time = total_duration // 3  # Salad is fast

            print(f"\n⏱️ Estimated Processing Time:")
            print(f"  Total audio duration: {total_duration // 3600}h {(total_duration % 3600) // 60}m")
            print(f"  Estimated processing: {est_processing_time // 3600}h {(est_processing_time % 3600) // 60}m")

            # Auto-confirm processing
            print(f"\n🔄 Starting to process {len(new_recordings)} recordings...")

            print("\n🚀 Starting processing...\n")

            # 4. Process each recording
            for i, recording in enumerate(new_recordings, 1):
                success = self.process_recording(recording, i, len(new_recordings))

                # Show progress
                if i % 10 == 0 or i == len(new_recordings):
                    elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
                    rate = self.stats['new_recordings'] / elapsed if elapsed > 0 else 0
                    remaining = (len(new_recordings) - i) / rate if rate > 0 else 0

                    print(f"\n📊 Progress: {i}/{len(new_recordings)} ({i/len(new_recordings)*100:.1f}%)")
                    print(f"  Success rate: {self.stats['new_recordings']/i*100:.1f}%")
                    print(f"  Rate: {rate*60:.1f} recordings/min")
                    print(f"  ETA: {remaining/3600:.1f} hours")

                # Small delay between recordings
                if i < len(new_recordings):
                    time.sleep(15)  # Increased delay for RingCentral rate limits

            # 5. Final summary
            elapsed_total = (datetime.now() - self.stats['start_time']).total_seconds()

            print("\n" + "="*80)
            print("📊 HISTORICAL CATCHUP COMPLETE")
            print("="*80)
            print(f"  Total Found: {self.stats['total_found']}")
            print(f"  Already Processed: {self.stats['already_processed']}")
            print(f"  New Recordings: {self.stats['new_recordings']}")
            print(f"  ⬇️ Downloaded: {self.stats['downloaded']}")
            print(f"  🎤 Transcribed: {self.stats['transcribed']}")
            print(f"  ☁️ Uploaded: {self.stats['uploaded']}")
            print(f"  ❌ Failed: {self.stats['failed']}")
            print(f"  ⏱️ Total Time: {elapsed_total/3600:.1f} hours")

            if self.stats['new_recordings'] > 0:
                print(f"  Success Rate: {self.stats['new_recordings']/(self.stats['new_recordings']+self.stats['failed'])*100:.1f}%")

            # Save summary
            summary_file = '/var/www/call-recording-system/historical_catchup_summary.json'
            with open(summary_file, 'w') as f:
                json.dump({
                    'run_date': datetime.now().isoformat(),
                    'date_range': {
                        'from': start_date.isoformat(),
                        'to': end_date.isoformat()
                    },
                    'stats': self.stats,
                    'elapsed_seconds': elapsed_total
                }, f, indent=2)

            print(f"\n💾 Summary saved to: {summary_file}")
            print("\n✨ Historical catchup complete!")
            print(f"📁 Check Google Drive folder ID: {os.getenv('GOOGLE_DRIVE_FOLDER_ID')}")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            import traceback
            traceback.print_exc()
            raise


def main():
    """Main entry point"""
    processor = HistoricalCatchupProcessor()
    processor.run()


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Final Historical Catchup Script
Processes all recordings from July 1, 2025 to Sept 17, 2025
Uses domain-wide delegation for Google Drive uploads
Includes transcription with Whisper
"""

import os
import logging
import tempfile
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from queue import Queue

from src.config.settings import Settings
from src.database.session import SessionManager
from src.database.config import DatabaseConfig
from src.database.models import CallRecording, ProcessingStatus
from src.ringcentral.auth import RingCentralAuth
from src.ringcentral.client import RingCentralClient
from src.storage.google_drive import GoogleDriveManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HistoricalBackupProcessor:
    """Process historical recordings with complete pipeline"""

    def __init__(self, batch_size: int = 10):
        """Initialize the processor"""
        self.settings = Settings()
        self.batch_size = batch_size
        self.stats = {
            'total': 0,
            'processed': 0,
            'downloaded': 0,
            'transcribed': 0,
            'uploaded': 0,
            'failed': 0,
            'start_time': datetime.now()
        }
        self._initialize_components()

    def _initialize_components(self):
        """Initialize all required components"""
        logger.info("Initializing components for historical backup...")

        # Database
        db_config = DatabaseConfig(self.settings.database_url)
        self.session_manager = SessionManager(db_config)

        # RingCentral
        self.ringcentral_auth = RingCentralAuth(
            jwt_token=self.settings.ringcentral_jwt_token,
            client_id=self.settings.ringcentral_client_id,
            client_secret=self.settings.ringcentral_client_secret,
            sandbox=getattr(self.settings, 'ringcentral_sandbox', False)
        )
        self.ringcentral_client = RingCentralClient(auth=self.ringcentral_auth)

        # Google Drive with domain-wide delegation
        self.drive_manager = GoogleDriveManager(
            credentials_path=self.settings.google_credentials_path,
            impersonate_email=os.getenv('GOOGLE_IMPERSONATE_EMAIL')
        )

        # Transcription (optional)
        self.transcription_available = False
        try:
            from src.transcription.pipeline import TranscriptionPipeline
            self.transcription_pipeline = TranscriptionPipeline()
            self.transcription_available = True
            logger.info("✅ Transcription available")
        except Exception as e:
            logger.warning(f"⚠️  Transcription not available: {e}")

        logger.info("✅ All components initialized")

    def fetch_all_recordings(self) -> List[Dict[str, Any]]:
        """Fetch all recordings from July 1 to Sept 17, 2025"""
        start_date = datetime(2025, 7, 1, tzinfo=timezone.utc)
        end_date = datetime(2025, 9, 17, 23, 59, 59, tzinfo=timezone.utc)

        logger.info(f"📅 Fetching recordings from {start_date.date()} to {end_date.date()}")

        recordings = []
        try:
            for record in self.ringcentral_client.get_all_call_logs(
                date_from=start_date,
                date_to=end_date,
                recording_type='All'
            ):
                recording_info = record.get('recording', {})
                if recording_info:
                    recordings.append({
                        'call_id': record.get('id'),
                        'session_id': record.get('sessionId'),
                        'start_time': record.get('startTime'),
                        'duration': record.get('duration', 0),
                        'from_name': record.get('from', {}).get('name'),
                        'from_number': record.get('from', {}).get('phoneNumber'),
                        'to_name': record.get('to', {}).get('name'),
                        'to_number': record.get('to', {}).get('phoneNumber'),
                        'direction': record.get('direction'),
                        'recording_id': recording_info.get('id'),
                        'recording_type': recording_info.get('type'),
                    })

        except Exception as e:
            logger.error(f"Error fetching recordings: {e}")
            raise

        logger.info(f"✅ Fetched {len(recordings)} recordings")
        return recordings

    def process_recording(self, recording: Dict[str, Any], index: int, total: int) -> bool:
        """Process a single recording"""
        recording_id = recording['recording_id']

        logger.info(f"\n{'='*60}")
        logger.info(f"📞 [{index}/{total}] Processing {recording_id}")
        logger.info(f"  From: {recording['from_name']} ({recording['from_number']})")
        logger.info(f"  Duration: {recording['duration']}s")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # 1. Download
                logger.info(f"  ⬇️  Downloading...")
                audio_path = temp_path / f"{recording_id}.mp3"

                self.ringcentral_client.download_recording(
                    recording_id=recording_id,
                    output_path=str(audio_path)
                )

                file_size = audio_path.stat().st_size
                logger.info(f"  ✅ Downloaded: {file_size:,} bytes")
                self.stats['downloaded'] += 1

                # Save to database
                with self.session_manager.get_session() as session:
                    existing = session.query(CallRecording).filter_by(
                        recording_id=recording_id
                    ).first()

                    if not existing:
                        db_record = CallRecording(
                            call_id=recording['call_id'],
                            recording_id=recording_id,
                            session_id=recording['session_id'],
                            start_time=datetime.fromisoformat(
                                recording['start_time'].replace('Z', '+00:00')
                            ),
                            duration=recording['duration'],
                            from_number=recording['from_number'],
                            from_name=recording['from_name'],
                            to_number=recording['to_number'],
                            to_name=recording['to_name'],
                            direction=recording['direction'],
                            recording_type=recording.get('recording_type', 'Unknown'),
                            download_status=ProcessingStatus.COMPLETED,
                            download_completed_at=datetime.now(timezone.utc),
                            file_size_bytes=file_size,
                            transcription_status=ProcessingStatus.PENDING,
                            upload_status=ProcessingStatus.PENDING
                        )
                        session.add(db_record)
                    else:
                        db_record = existing

                    session.commit()
                    db_record_id = db_record.id

                # 2. Transcribe (optional)
                transcription_text = None
                if self.transcription_available:
                    logger.info(f"  🎤 Transcribing...")
                    try:
                        result = self.transcription_pipeline.process(
                            audio_path=str(audio_path)
                        )
                        if result and 'text' in result:
                            transcription_text = result['text']
                            logger.info(f"  ✅ Transcribed: {len(transcription_text)} chars")
                            self.stats['transcribed'] += 1
                    except Exception as e:
                        logger.warning(f"  ⚠️  Transcription failed: {e}")

                # 3. Create metadata
                call_datetime = datetime.fromisoformat(
                    recording['start_time'].replace('Z', '+00:00')
                )

                metadata = {
                    'recording_id': recording_id,
                    'call_id': recording['call_id'],
                    'start_time': recording['start_time'],
                    'date': call_datetime.strftime('%Y-%m-%d'),
                    'duration_seconds': recording['duration'],
                    'from': {
                        'name': recording['from_name'] or 'Unknown',
                        'number': recording['from_number'] or 'Unknown',
                    },
                    'to': {
                        'name': recording['to_name'] or 'Unknown',
                        'number': recording['to_number'] or 'Unknown',
                    },
                    'direction': recording['direction'],
                    'transcription_available': transcription_text is not None,
                    'processed_date': datetime.now(timezone.utc).isoformat()
                }

                metadata_path = temp_path / f"{recording_id}_metadata.json"
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2, default=str)

                # 4. Upload to Google Drive
                logger.info(f"  ☁️  Uploading to Google Drive...")

                # Create folder structure
                year = call_datetime.strftime('%Y')
                month_folder = call_datetime.strftime('%m-%B')

                recordings_folder = self.drive_manager.get_or_create_folder("Call Recordings")
                year_folder = self.drive_manager.get_or_create_folder(year, recordings_folder)
                month_folder_id = self.drive_manager.get_or_create_folder(month_folder, year_folder)

                # Create subfolders
                audio_folder_id = self.drive_manager.get_or_create_folder("Audio", month_folder_id)
                metadata_folder_id = self.drive_manager.get_or_create_folder("Metadata", month_folder_id)

                # Upload audio
                audio_filename = f"{call_datetime.strftime('%Y%m%d_%H%M')}_{recording_id}.mp3"
                audio_file_id = self.drive_manager.upload_file(
                    file_path=str(audio_path),
                    file_name=audio_filename,
                    folder_id=audio_folder_id
                )

                # Upload metadata
                json_filename = f"{call_datetime.strftime('%Y%m%d_%H%M')}_{recording_id}_metadata.json"
                self.drive_manager.upload_file(
                    file_path=str(metadata_path),
                    file_name=json_filename,
                    folder_id=metadata_folder_id
                )

                # Upload transcript if available
                if transcription_text:
                    transcript_path = temp_path / f"{recording_id}_transcript.txt"
                    with open(transcript_path, 'w') as f:
                        f.write(f"TRANSCRIPT - Recording {recording_id}\n")
                        f.write(f"{'='*50}\n\n")
                        f.write(transcription_text)

                    transcripts_folder_id = self.drive_manager.get_or_create_folder("Transcripts", month_folder_id)
                    transcript_filename = f"{call_datetime.strftime('%Y%m%d_%H%M')}_{recording_id}_transcript.txt"
                    self.drive_manager.upload_file(
                        file_path=str(transcript_path),
                        file_name=transcript_filename,
                        folder_id=transcripts_folder_id
                    )

                # Update database
                with self.session_manager.get_session() as session:
                    db_record = session.get(CallRecording, db_record_id)
                    db_record.upload_status = ProcessingStatus.COMPLETED
                    db_record.upload_completed_at = datetime.now(timezone.utc)
                    db_record.google_drive_file_id = audio_file_id
                    if transcription_text:
                        db_record.transcription_status = ProcessingStatus.COMPLETED
                        db_record.transcription_text = transcription_text
                    session.commit()

                logger.info(f"  ✅ Successfully processed!")
                self.stats['uploaded'] += 1
                self.stats['processed'] += 1
                return True

        except Exception as e:
            logger.error(f"  ❌ Failed: {e}")
            self.stats['failed'] += 1
            return False

    def process_batch(self, recordings: List[Dict[str, Any]], start_idx: int):
        """Process a batch of recordings in parallel"""
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            for i, recording in enumerate(recordings):
                idx = start_idx + i + 1
                future = executor.submit(
                    self.process_recording,
                    recording,
                    idx,
                    self.stats['total']
                )
                futures.append((future, recording))
                time.sleep(0.5)  # Slight delay between submissions

            for future, recording in futures:
                try:
                    future.result(timeout=600)  # 10 min timeout
                except Exception as e:
                    logger.error(f"Failed to process {recording['recording_id']}: {e}")

    def run(self):
        """Run the historical backup"""
        print("\n" + "="*70)
        print("🚀 HISTORICAL BACKUP - FULL PROCESSING")
        print(f"   Period: July 1 - Sept 17, 2025")
        print(f"   Using: {os.getenv('GOOGLE_IMPERSONATE_EMAIL')}")
        print("="*70)

        try:
            # Fetch all recordings
            recordings = self.fetch_all_recordings()
            self.stats['total'] = len(recordings)

            if not recordings:
                print("❌ No recordings found")
                return

            print(f"\n📊 Found {len(recordings)} recordings to process")
            print(f"   Batch size: {self.batch_size}")
            print(f"   Estimated time: {len(recordings) * 3 / 60:.1f} hours")
            print("\nStarting processing...\n")

            # Process in batches
            for i in range(0, len(recordings), self.batch_size):
                batch = recordings[i:i+self.batch_size]
                print(f"\n📦 Processing batch {i//self.batch_size + 1}/{(len(recordings)-1)//self.batch_size + 1}")
                self.process_batch(batch, i)

                # Show progress
                elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
                rate = self.stats['processed'] / elapsed if elapsed > 0 else 0
                remaining = (self.stats['total'] - self.stats['processed']) / rate if rate > 0 else 0

                print(f"\n📊 Progress: {self.stats['processed']}/{self.stats['total']} "
                      f"({self.stats['processed']/self.stats['total']*100:.1f}%)")
                print(f"   Rate: {rate*60:.1f} recordings/min")
                print(f"   ETA: {remaining/3600:.1f} hours")

                # Small delay between batches
                if i + self.batch_size < len(recordings):
                    time.sleep(5)

            # Final summary
            elapsed_total = (datetime.now() - self.stats['start_time']).total_seconds()

            print("\n" + "="*70)
            print("📊 HISTORICAL BACKUP COMPLETE")
            print("="*70)
            print(f"  Total Recordings: {self.stats['total']}")
            print(f"  ✅ Processed: {self.stats['processed']}")
            print(f"  ⬇️  Downloaded: {self.stats['downloaded']}")
            if self.transcription_available:
                print(f"  🎤 Transcribed: {self.stats['transcribed']}")
            print(f"  ☁️  Uploaded: {self.stats['uploaded']}")
            print(f"  ❌ Failed: {self.stats['failed']}")
            print(f"  ⏱️  Total Time: {elapsed_total/3600:.1f} hours")
            print(f"  Success Rate: {self.stats['processed']/self.stats['total']*100:.1f}%")

            print("\n✨ Backup complete!")
            print(f"📁 Check Google Drive: {os.getenv('GOOGLE_IMPERSONATE_EMAIL')}")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            raise
        finally:
            if hasattr(self, 'ringcentral_auth'):
                self.ringcentral_auth.close()
            if hasattr(self, 'session_manager'):
                self.session_manager.close()


def main():
    """Main entry point"""
    processor = HistoricalBackupProcessor(batch_size=10)
    processor.run()


if __name__ == "__main__":
    main()
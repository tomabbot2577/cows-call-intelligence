#!/usr/bin/env python3
"""
Test script to upload audio files directly to Google Drive
Bypasses transcription to verify upload functionality
"""

import os
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from pathlib import Path

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


class UploadTestProcessor:
    """Test processor that uploads recordings directly without transcription"""

    def __init__(self):
        """Initialize the processor"""
        self.settings = Settings()
        self.processed_count = 0
        self.download_count = 0
        self.upload_count = 0
        self.failed_count = 0
        self._initialize_components()

    def _initialize_components(self):
        """Initialize all required components"""
        logger.info("Initializing components...")

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

        # Google Drive
        self.drive_manager = GoogleDriveManager(
            credentials_path=self.settings.google_credentials_path
        )

        logger.info("✅ Components initialized successfully")

    def fetch_recent_recordings(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent recordings"""
        # Get recordings from the last 7 days
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=7)

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
                    call_data = {
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
                        'recording_uri': recording_info.get('uri'),
                        'recording_type': recording_info.get('type'),
                    }
                    recordings.append(call_data)

                    if len(recordings) >= limit:
                        break

        except Exception as e:
            logger.error(f"Error fetching recordings: {e}")
            raise

        logger.info(f"✅ Fetched {len(recordings)} recordings")
        return recordings[:limit]

    def process_recording(self, recording: Dict[str, Any]) -> bool:
        """Process a single recording - download and upload only"""
        recording_id = recording['recording_id']
        self.processed_count += 1

        logger.info(f"\n{'='*60}")
        logger.info(f"📞 [{self.processed_count}/10] Processing recording {recording_id}")
        logger.info(f"  From: {recording['from_name']} ({recording['from_number']})")
        logger.info(f"  To: {recording['to_name']} ({recording['to_number']})")
        logger.info(f"  Duration: {recording['duration']} seconds")
        logger.info(f"  Date: {recording['start_time']}")

        # Create temp directory for this recording
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # 1. DOWNLOAD RECORDING
            logger.info(f"  ⬇️  Downloading audio...")
            audio_path = temp_path / f"{recording_id}.mp3"

            try:
                self.ringcentral_client.download_recording(
                    recording_id=recording_id,
                    output_path=str(audio_path)
                )

                file_size = audio_path.stat().st_size
                logger.info(f"  ✅ Downloaded: {file_size:,} bytes")
                self.download_count += 1

                # Update database
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
                            local_file_path=str(audio_path),
                            file_size_bytes=file_size,
                            transcription_status=ProcessingStatus.PENDING,
                            upload_status=ProcessingStatus.PENDING
                        )
                        session.add(db_record)
                    else:
                        db_record = existing
                        db_record.download_status = ProcessingStatus.COMPLETED
                        db_record.download_completed_at = datetime.now(timezone.utc)
                        db_record.local_file_path = str(audio_path)
                        db_record.file_size_bytes = file_size

                    session.commit()
                    db_record_id = db_record.id

            except Exception as e:
                logger.error(f"  ❌ Download failed: {e}")
                self.failed_count += 1
                return False

            # 2. CREATE METADATA FILE (without transcription)
            logger.info(f"  📝 Creating metadata...")
            call_datetime = datetime.fromisoformat(
                recording['start_time'].replace('Z', '+00:00')
            )

            metadata = {
                'recording_id': recording_id,
                'call_id': recording['call_id'],
                'session_id': recording['session_id'],
                'start_time': recording['start_time'],
                'date': call_datetime.strftime('%Y-%m-%d'),
                'time': call_datetime.strftime('%H:%M:%S UTC'),
                'day_of_week': call_datetime.strftime('%A'),
                'duration_seconds': recording['duration'],
                'duration_formatted': f"{recording['duration']//60}m {recording['duration']%60}s",
                'from': {
                    'name': recording['from_name'] or 'Unknown',
                    'number': recording['from_number'] or 'Unknown',
                },
                'to': {
                    'name': recording['to_name'] or 'Unknown',
                    'number': recording['to_number'] or 'Unknown',
                },
                'direction': recording['direction'],
                'recording_type': recording.get('recording_type', 'Unknown'),
                'note': 'Audio file only - transcription pending',
                'processing': {
                    'processed_date': datetime.now(timezone.utc).isoformat(),
                }
            }

            # Save metadata JSON
            import json
            metadata_path = temp_path / f"{recording_id}_metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2, default=str)

            # 3. UPLOAD TO GOOGLE DRIVE
            logger.info(f"  ☁️  Uploading to Google Drive...")
            try:
                # Create folder structure
                year = call_datetime.strftime('%Y')
                month_folder = call_datetime.strftime('%m-%B')

                # Upload audio file
                audio_file_id = self.drive_manager.upload_file(
                    file_path=str(audio_path),
                    folder_path=f"Call Recordings/{year}/{month_folder}/Audio",
                    description=f"Call recording from {recording['start_time']}"
                )
                logger.info(f"     ✅ Audio uploaded (ID: {audio_file_id})")

                # Upload metadata JSON
                metadata_file_id = self.drive_manager.upload_file(
                    file_path=str(metadata_path),
                    folder_path=f"Call Recordings/{year}/{month_folder}/Metadata",
                    description=f"Metadata for call {recording_id}"
                )
                logger.info(f"     ✅ Metadata uploaded (ID: {metadata_file_id})")

                # Update database
                with self.session_manager.get_session() as session:
                    db_record = session.get(CallRecording, db_record_id)
                    db_record.upload_status = ProcessingStatus.COMPLETED
                    db_record.upload_completed_at = datetime.now(timezone.utc)
                    db_record.google_drive_file_id = audio_file_id
                    session.commit()

                logger.info(f"  🎉 Successfully uploaded recording {recording_id}")
                self.upload_count += 1
                return True

            except Exception as e:
                logger.error(f"  ❌ Upload failed: {e}")
                self.failed_count += 1

                # Update database
                with self.session_manager.get_session() as session:
                    db_record = session.get(CallRecording, db_record_id)
                    db_record.upload_status = ProcessingStatus.FAILED
                    db_record.upload_error = str(e)
                    session.commit()

                return False

    def run(self):
        """Run the test processing"""
        print("\n" + "="*70)
        print("🧪 TEST: UPLOAD RECORDINGS TO GOOGLE DRIVE")
        print("   (Bypassing transcription to verify uploads)")
        print("="*70)

        try:
            # Fetch 10 recent recordings
            recordings = self.fetch_recent_recordings(10)

            if not recordings:
                print("❌ No recordings found in the last 7 days")
                return

            print(f"\n📋 Found {len(recordings)} recordings to process")
            print("Starting processing...\n")

            # Process each recording
            for recording in recordings:
                success = self.process_recording(recording)

                # Add small delay to avoid rate limiting
                import time
                time.sleep(2)

            # Print summary
            print("\n" + "="*70)
            print("📊 PROCESSING SUMMARY")
            print("="*70)
            print(f"  Total Processed: {self.processed_count}")
            print(f"  ✅ Downloaded: {self.download_count}")
            print(f"  ✅ Uploaded: {self.upload_count}")
            print(f"  ❌ Failed: {self.failed_count}")
            print(f"  Success Rate: {(self.upload_count/self.processed_count*100 if self.processed_count else 0):.1f}%")
            print("\n✨ Test complete!")
            print("📁 Check your Google Drive for the uploaded files:")
            print("   Path: Call Recordings/2025/09-September/")
            print("   - Audio/ folder contains MP3 files")
            print("   - Metadata/ folder contains JSON files with call details")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            raise
        finally:
            # Cleanup
            if hasattr(self, 'ringcentral_auth'):
                self.ringcentral_auth.close()
            if hasattr(self, 'session_manager'):
                self.session_manager.close()


def main():
    """Main entry point"""
    processor = UploadTestProcessor()
    processor.run()


if __name__ == "__main__":
    main()
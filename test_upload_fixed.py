#!/usr/bin/env python3
"""
Fixed test script to upload audio files to Google Drive
Creates proper folder structure and uses correct folder_id parameter
"""

import os
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
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


class FixedUploadProcessor:
    """Fixed processor that properly uploads recordings to Google Drive"""

    def __init__(self):
        """Initialize the processor"""
        self.settings = Settings()
        self.processed_count = 0
        self.download_count = 0
        self.upload_count = 0
        self.failed_count = 0
        self.folder_cache = {}  # Cache folder IDs
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

    def get_or_create_folder_path(self, path: str) -> str:
        """
        Get or create a folder path in Google Drive

        Args:
            path: Path like "Call Recordings/2025/09-September/Audio"

        Returns:
            Folder ID of the final folder
        """
        # Check cache first
        if path in self.folder_cache:
            return self.folder_cache[path]

        # Split path into components
        parts = path.split('/')
        parent_id = None

        # Create each folder level
        for i, part in enumerate(parts):
            # Build cache key for this level
            partial_path = '/'.join(parts[:i+1])

            if partial_path in self.folder_cache:
                parent_id = self.folder_cache[partial_path]
            else:
                # Create or get folder
                parent_id = self.drive_manager.get_or_create_folder(
                    folder_name=part,
                    parent_id=parent_id
                )
                self.folder_cache[partial_path] = parent_id
                logger.info(f"  📁 Created/found folder: {partial_path} (ID: {parent_id})")

        return parent_id

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
        """Process a single recording - download and upload"""
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

            # 2. CREATE METADATA FILE
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

            # Create info text file
            info_path = temp_path / f"{recording_id}_info.txt"
            with open(info_path, 'w') as f:
                f.write(f"CALL RECORDING INFORMATION\n")
                f.write(f"{'='*50}\n\n")
                f.write(f"Recording ID: {recording_id}\n")
                f.write(f"Date: {metadata['date']} ({metadata['day_of_week']})\n")
                f.write(f"Time: {metadata['time']}\n")
                f.write(f"Duration: {metadata['duration_formatted']}\n\n")
                f.write(f"From: {recording['from_name'] or 'Unknown'}\n")
                f.write(f"      {recording['from_number'] or 'Unknown'}\n\n")
                f.write(f"To:   {recording['to_name'] or 'Unknown'}\n")
                f.write(f"      {recording['to_number'] or 'Unknown'}\n\n")
                f.write(f"Direction: {metadata['direction']}\n")
                f.write(f"Type: {metadata['recording_type']}\n\n")
                f.write(f"Note: Transcription pending - audio file only\n")

            # 3. UPLOAD TO GOOGLE DRIVE
            logger.info(f"  ☁️  Uploading to Google Drive...")
            try:
                # Create folder structure
                year = call_datetime.strftime('%Y')
                month_folder = call_datetime.strftime('%m-%B')

                # Get or create Audio folder
                audio_folder_path = f"Call Recordings/{year}/{month_folder}/Audio"
                audio_folder_id = self.get_or_create_folder_path(audio_folder_path)

                # Upload audio file
                audio_filename = f"{call_datetime.strftime('%Y%m%d_%H%M')}_{recording['from_name'] or 'Unknown'}_{recording_id}.mp3"
                audio_file_id = self.drive_manager.upload_file(
                    file_path=str(audio_path),
                    file_name=audio_filename,
                    folder_id=audio_folder_id
                )
                logger.info(f"     ✅ Audio uploaded: {audio_filename}")

                # Get or create Metadata folder
                metadata_folder_path = f"Call Recordings/{year}/{month_folder}/Metadata"
                metadata_folder_id = self.get_or_create_folder_path(metadata_folder_path)

                # Upload metadata JSON
                json_filename = f"{call_datetime.strftime('%Y%m%d_%H%M')}_{recording_id}_metadata.json"
                metadata_file_id = self.drive_manager.upload_file(
                    file_path=str(metadata_path),
                    file_name=json_filename,
                    folder_id=metadata_folder_id
                )
                logger.info(f"     ✅ Metadata uploaded: {json_filename}")

                # Upload info text
                text_filename = f"{call_datetime.strftime('%Y%m%d_%H%M')}_{recording_id}_info.txt"
                text_file_id = self.drive_manager.upload_file(
                    file_path=str(info_path),
                    file_name=text_filename,
                    folder_id=metadata_folder_id
                )
                logger.info(f"     ✅ Info uploaded: {text_filename}")

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
        print("🧪 FIXED TEST: UPLOAD RECORDINGS TO GOOGLE DRIVE")
        print("   Creating proper folder structure")
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

                # Add delay to avoid rate limiting
                import time
                time.sleep(2)

            # Print summary
            print("\n" + "="*70)
            print("📊 PROCESSING SUMMARY")
            print("="*70)
            print(f"  Total Processed: {self.processed_count}")
            print(f"  ✅ Downloaded: {self.download_count}")
            print(f"  ✅ Uploaded to Drive: {self.upload_count}")
            print(f"  ❌ Failed: {self.failed_count}")
            print(f"  Success Rate: {(self.upload_count/self.processed_count*100 if self.processed_count else 0):.1f}%")
            print("\n✨ Test complete!")
            print("📁 Check your Google Drive for the uploaded files:")
            print("   Path: Call Recordings/2025/09-September/")
            print("   - Audio/ folder: MP3 recordings with descriptive names")
            print("   - Metadata/ folder: JSON and TXT files with call details")

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
    processor = FixedUploadProcessor()
    processor.run()


if __name__ == "__main__":
    main()
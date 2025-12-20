#!/usr/bin/env python3
"""
Test script to process exactly 15 call recordings end-to-end
Downloads, transcribes, and uploads to Google Drive
"""

import os
import logging
import json
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple
from pathlib import Path

from src.config.settings import Settings
from src.database.session import SessionManager
from src.database.config import DatabaseConfig
from src.database.models import CallRecording, ProcessingStatus
from src.ringcentral.auth import RingCentralAuth
from src.ringcentral.client import RingCentralClient
from src.transcription.pipeline import TranscriptionPipeline
from src.storage.google_drive import GoogleDriveManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestProcessor:
    """Process 15 test recordings"""

    def __init__(self):
        """Initialize the processor"""
        self.settings = Settings()
        self.processed_count = 0
        self.success_count = 0
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

        # Transcription
        self.transcription_pipeline = TranscriptionPipeline(
            model_name=getattr(self.settings, 'whisper_model', 'base'),
            device=getattr(self.settings, 'whisper_device', 'cpu')
        )

        # Google Drive
        self.drive_manager = GoogleDriveManager(
            credentials_path=self.settings.google_credentials_path
        )

        logger.info("✅ Components initialized successfully")

    def fetch_recent_recordings(self, limit: int = 15) -> List[Dict[str, Any]]:
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

    def process_recording(self, recording: Dict[str, Any]) -> Tuple[bool, str]:
        """Process a single recording completely"""
        recording_id = recording['recording_id']
        self.processed_count += 1

        logger.info(f"\n{'='*60}")
        logger.info(f"📞 [{self.processed_count}/15] Processing recording {recording_id}")
        logger.info(f"  From: {recording['from_name']} ({recording['from_number']})")
        logger.info(f"  To: {recording['to_name']} ({recording['to_number']})")
        logger.info(f"  Duration: {recording['duration']} seconds")
        logger.info(f"  Date: {recording['start_time']}")

        try:
            # Check if already processed
            with self.session_manager.get_session() as session:
                existing = session.query(CallRecording).filter_by(
                    recording_id=recording_id
                ).first()

                if existing and existing.upload_status == ProcessingStatus.COMPLETED:
                    logger.info(f"✅ Recording {recording_id} already fully processed")
                    self.success_count += 1
                    return True, "Already processed"

                # Create or update database record
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
                        download_status=ProcessingStatus.PENDING,
                        transcription_status=ProcessingStatus.PENDING,
                        upload_status=ProcessingStatus.PENDING
                    )
                    session.add(db_record)
                else:
                    db_record = existing

                session.commit()
                db_record_id = db_record.id

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

                    # Update database
                    with self.session_manager.get_session() as session:
                        db_record = session.get(CallRecording, db_record_id)
                        db_record.download_status = ProcessingStatus.COMPLETED
                        db_record.download_completed_at = datetime.now(timezone.utc)
                        db_record.local_file_path = str(audio_path)
                        db_record.file_size_bytes = file_size
                        session.commit()

                except Exception as e:
                    logger.error(f"  ❌ Download failed: {e}")
                    self._update_status(db_record_id, 'download', ProcessingStatus.FAILED, str(e))
                    self.failed_count += 1
                    return False, f"Download failed: {e}"

                # 2. TRANSCRIBE RECORDING
                logger.info(f"  🎙️  Transcribing audio...")
                try:
                    transcription_result = self.transcription_pipeline.process(
                        audio_path=str(audio_path)
                    )

                    # Parse datetime for formatting
                    call_datetime = datetime.fromisoformat(
                        recording['start_time'].replace('Z', '+00:00')
                    )

                    # Create metadata
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
                        'transcription': {
                            'full_text': transcription_result.get('text', ''),
                            'language': transcription_result.get('language', 'en'),
                            'segments': transcription_result.get('segments', []),
                            'word_count': len(transcription_result.get('text', '').split())
                        },
                        'processing': {
                            'processed_date': datetime.now(timezone.utc).isoformat(),
                            'whisper_model': getattr(self.settings, 'whisper_model', 'base'),
                        }
                    }

                    # Save transcription JSON
                    transcription_path = temp_path / f"{recording_id}_transcription.json"
                    with open(transcription_path, 'w') as f:
                        json.dump(metadata, f, indent=2, default=str)

                    # Create text version
                    text_path = temp_path / f"{recording_id}_transcription.txt"
                    with open(text_path, 'w') as f:
                        f.write(f"CALL TRANSCRIPTION\n")
                        f.write(f"{'='*60}\n")
                        f.write(f"Recording ID: {recording_id}\n")
                        f.write(f"Date: {metadata['date']} ({metadata['day_of_week']})\n")
                        f.write(f"Time: {metadata['time']}\n")
                        f.write(f"Duration: {metadata['duration_formatted']}\n")
                        f.write(f"From: {recording['from_name']} ({recording['from_number']})\n")
                        f.write(f"To: {recording['to_name']} ({recording['to_number']})\n")
                        f.write(f"Direction: {metadata['direction']}\n\n")
                        f.write(f"TRANSCRIPTION:\n")
                        f.write(f"{'-'*60}\n")
                        f.write(metadata['transcription']['full_text'] or "[No transcription available]")

                    word_count = metadata['transcription']['word_count']
                    logger.info(f"  ✅ Transcribed: {word_count} words")

                    # Update database
                    with self.session_manager.get_session() as session:
                        db_record = session.get(CallRecording, db_record_id)
                        db_record.transcription_status = ProcessingStatus.COMPLETED
                        db_record.transcription_completed_at = datetime.now(timezone.utc)
                        db_record.transcript_word_count = word_count
                        db_record.language_detected = metadata['transcription']['language']
                        session.commit()

                except Exception as e:
                    logger.error(f"  ❌ Transcription failed: {e}")
                    self._update_status(db_record_id, 'transcription', ProcessingStatus.FAILED, str(e))
                    self.failed_count += 1
                    return False, f"Transcription failed: {e}"

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
                    logger.info(f"     ✅ Audio uploaded")

                    # Upload JSON transcription
                    transcript_json_id = self.drive_manager.upload_file(
                        file_path=str(transcription_path),
                        folder_path=f"Call Recordings/{year}/{month_folder}/Transcripts/JSON",
                        description=f"Transcription JSON for call {recording_id}"
                    )
                    logger.info(f"     ✅ JSON transcript uploaded")

                    # Upload text transcription
                    transcript_text_id = self.drive_manager.upload_file(
                        file_path=str(text_path),
                        folder_path=f"Call Recordings/{year}/{month_folder}/Transcripts/Text",
                        description=f"Transcription text for call {recording_id}"
                    )
                    logger.info(f"     ✅ Text transcript uploaded")

                    # Update database
                    with self.session_manager.get_session() as session:
                        db_record = session.get(CallRecording, db_record_id)
                        db_record.upload_status = ProcessingStatus.COMPLETED
                        db_record.upload_completed_at = datetime.now(timezone.utc)
                        db_record.google_drive_file_id = audio_file_id
                        session.commit()

                    logger.info(f"  🎉 Successfully processed recording {recording_id}")
                    self.success_count += 1
                    return True, "Success"

                except Exception as e:
                    logger.error(f"  ❌ Upload failed: {e}")
                    self._update_status(db_record_id, 'upload', ProcessingStatus.FAILED, str(e))
                    self.failed_count += 1
                    return False, f"Upload failed: {e}"

        except Exception as e:
            logger.error(f"  💥 Unexpected error: {e}")
            self.failed_count += 1
            return False, f"Unexpected error: {e}"

    def _update_status(self, record_id: int, stage: str, status: ProcessingStatus, error: str = None):
        """Update processing status in database"""
        with self.session_manager.get_session() as session:
            record = session.get(CallRecording, record_id)
            if record:
                if stage == 'download':
                    record.download_status = status
                    record.download_error = error
                    record.download_attempts = (record.download_attempts or 0) + 1
                elif stage == 'transcription':
                    record.transcription_status = status
                    record.transcription_error = error
                    record.transcription_attempts = (record.transcription_attempts or 0) + 1
                elif stage == 'upload':
                    record.upload_status = status
                    record.upload_error = error
                    record.upload_attempts = (record.upload_attempts or 0) + 1
                session.commit()

    def run(self):
        """Run the test processing"""
        print("\n" + "="*70)
        print("🧪 TEST: PROCESSING 15 CALL RECORDINGS END-TO-END")
        print("="*70)

        try:
            # Fetch 15 recent recordings
            recordings = self.fetch_recent_recordings(15)

            if not recordings:
                print("❌ No recordings found in the last 7 days")
                return

            print(f"\n📋 Found {len(recordings)} recordings to process")
            print("Starting processing...\n")

            # Process each recording
            for recording in recordings:
                success, message = self.process_recording(recording)

            # Print summary
            print("\n" + "="*70)
            print("📊 PROCESSING SUMMARY")
            print("="*70)
            print(f"  Total Processed: {self.processed_count}")
            print(f"  ✅ Successful: {self.success_count}")
            print(f"  ❌ Failed: {self.failed_count}")
            print(f"  Success Rate: {(self.success_count/self.processed_count*100 if self.processed_count else 0):.1f}%")
            print("\n✨ Test complete! Check your Google Drive for the uploaded files.")
            print("📁 Path: Call Recordings/2025/[Month]/")

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
    processor = TestProcessor()
    processor.run()


if __name__ == "__main__":
    main()
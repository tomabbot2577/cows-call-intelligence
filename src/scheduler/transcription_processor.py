#!/usr/bin/env python3
"""
Transcription Processor
Processes recordings from the queue through Salad transcription
and uploads to Google Drive
"""

import os
import sys
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directory to path
sys.path.insert(0, '/var/www/call-recording-system')

from src.database.models import Recording, ProcessingStatus
from src.database.session import SessionLocal
from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
from src.storage.google_drive import GoogleDriveManager
from src.storage.enhanced_organizer import EnhancedStorageOrganizer
from sqlalchemy import and_

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TranscriptionProcessor:
    """
    Processes audio recordings through the complete pipeline:
    1. Queue -> 2. Transcription -> 3. Storage -> 4. Google Drive
    """

    def __init__(self):
        """Initialize the transcription processor"""

        # Initialize components
        self.transcriber = SaladTranscriberEnhanced(
            api_key=os.getenv('SALAD_API_KEY'),
            organization_name=os.getenv('SALAD_ORG_NAME', 'mst'),
            enable_diarization=True,
            enable_summarization=True
        )

        self.drive_manager = GoogleDriveManager()
        self.storage_organizer = EnhancedStorageOrganizer()

        # Set up paths
        self.queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        self.processed_dir = Path('/var/www/call-recording-system/data/processed')
        self.failed_dir = Path('/var/www/call-recording-system/data/failed')

        # Create directories
        for dir_path in [self.queue_dir, self.processed_dir, self.failed_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # Processing stats
        self.stats = {
            'processed': 0,
            'failed': 0,
            'skipped': 0,
            'duplicates': 0
        }

        logger.info("TranscriptionProcessor initialized")

    def get_pending_recordings(self, limit: int = 10) -> List[Recording]:
        """
        Get pending recordings from the database

        Args:
            limit: Maximum number of recordings to process

        Returns:
            List of Recording objects
        """
        db = SessionLocal()
        try:
            # Get recordings that are downloaded but not yet transcribed
            recordings = db.query(Recording).filter(
                Recording.status == ProcessingStatus.DOWNLOADED
            ).limit(limit).all()

            # Detach from session to use in different context
            db.expunge_all()
            return recordings

        finally:
            db.close()

    def check_duplicate_transcription(self, recording: Recording) -> bool:
        """
        Check if this recording has already been transcribed

        Args:
            recording: Recording object

        Returns:
            True if duplicate/already processed
        """
        db = SessionLocal()
        try:
            # Check if transcription already exists
            if recording.transcription_path:
                if Path(recording.transcription_path).exists():
                    logger.info(f"Recording {recording.ringcentral_id} already has transcription")
                    self.stats['duplicates'] += 1
                    return True

            # Check if marked as completed
            if recording.status == ProcessingStatus.COMPLETED:
                logger.info(f"Recording {recording.ringcentral_id} already completed")
                self.stats['duplicates'] += 1
                return True

            # Check for duplicate by session ID if exists
            if recording.session_id:
                duplicate = db.query(Recording).filter(
                    and_(
                        Recording.session_id == recording.session_id,
                        Recording.id != recording.id,
                        Recording.status == ProcessingStatus.COMPLETED
                    )
                ).first()

                if duplicate:
                    logger.info(f"Recording {recording.ringcentral_id} is duplicate of {duplicate.ringcentral_id}")
                    self.stats['duplicates'] += 1
                    return True

            return False

        finally:
            db.close()

    def process_recording(self, recording: Recording) -> bool:
        """
        Process a single recording through the complete pipeline

        Args:
            recording: Recording object from database

        Returns:
            True if successful, False otherwise
        """
        recording_id = recording.ringcentral_id
        logger.info(f"Processing recording {recording_id}")

        # Check for duplicates first
        if self.check_duplicate_transcription(recording):
            logger.info(f"Skipping duplicate {recording_id}")
            self.stats['skipped'] += 1
            return True

        db = SessionLocal()
        try:
            # Update status to transcribing
            db_recording = db.query(Recording).filter_by(id=recording.id).first()
            db_recording.status = ProcessingStatus.TRANSCRIBING
            db.commit()

            # Check if audio file exists
            audio_path = Path(recording.audio_path)
            if not audio_path.exists():
                logger.error(f"Audio file not found: {audio_path}")
                db_recording.status = ProcessingStatus.FAILED
                db_recording.error_message = "Audio file not found"
                db.commit()
                self.stats['failed'] += 1
                return False

            # Upload audio to temporary web location for Salad
            audio_url = self._get_audio_url(audio_path)
            if not audio_url:
                logger.error(f"Failed to get audio URL for {recording_id}")
                db_recording.status = ProcessingStatus.FAILED
                db_recording.error_message = "Failed to create audio URL"
                db.commit()
                self.stats['failed'] += 1
                return False

            # Transcribe with Salad
            logger.info(f"Transcribing {recording_id} with Salad Cloud")
            transcription_result = self.transcriber.transcribe_file(audio_url)

            if not transcription_result or not transcription_result.text:
                logger.error(f"Transcription failed for {recording_id}")
                db_recording.status = ProcessingStatus.FAILED
                db_recording.error_message = "Transcription returned no text"
                db.commit()
                self.stats['failed'] += 1
                return False

            # Prepare call metadata
            call_metadata = {
                'date': recording.start_time.strftime('%Y-%m-%d'),
                'time': recording.start_time.strftime('%H:%M:%S'),
                'duration': recording.duration,
                'direction': recording.direction,
                'from': {
                    'number': recording.from_number,
                    'name': recording.from_name or ''
                },
                'to': {
                    'number': recording.to_number,
                    'name': recording.to_name or ''
                },
                'file_size': audio_path.stat().st_size if audio_path.exists() else 0
            }

            # Convert transcription result to dict
            transcription_dict = {
                'text': transcription_result.text,
                'confidence': transcription_result.confidence,
                'language': transcription_result.language,
                'language_probability': transcription_result.language_probability,
                'word_count': transcription_result.word_count,
                'duration_seconds': transcription_result.duration_seconds,
                'processing_time_seconds': transcription_result.processing_time_seconds,
                'segments': transcription_result.segments,
                'metadata': transcription_result.metadata,
                'timestamps': transcription_result.timestamps,
                'job_id': transcription_result.job_id
            }

            # Upload to Google Drive
            logger.info(f"Uploading {recording_id} to Google Drive")
            drive_file_id = self.drive_manager.upload_transcription(
                transcription_result,
                recording.ringcentral_id,
                recording.start_time
            )

            if not drive_file_id:
                logger.warning(f"Failed to upload to Google Drive for {recording_id}")
                # Continue anyway - local storage is more important

            # Save with enhanced organizer (creates JSON and MD files)
            logger.info(f"Saving {recording_id} in dual format")
            saved_paths = self.storage_organizer.save_transcription(
                recording_id=recording.ringcentral_id,
                transcription_result=transcription_dict,
                call_metadata=call_metadata,
                google_drive_id=drive_file_id
            )

            # Update database
            db_recording.status = ProcessingStatus.COMPLETED
            db_recording.transcription_path = saved_paths['json']
            db_recording.transcription_text = transcription_result.text[:1000]  # First 1000 chars
            db_recording.transcription_confidence = transcription_result.confidence
            db_recording.word_count = transcription_result.word_count
            db_recording.google_drive_id = drive_file_id
            db_recording.transcribed_at = datetime.now(timezone.utc)
            db_recording.error_message = None
            db.commit()

            # Move audio to processed directory
            processed_path = self.processed_dir / audio_path.name
            if audio_path.exists():
                audio_path.rename(processed_path)
                db_recording.audio_path = str(processed_path)
                db.commit()

            logger.info(f"Successfully processed {recording_id}")
            self.stats['processed'] += 1
            return True

        except Exception as e:
            logger.error(f"Error processing {recording_id}: {e}")
            db.rollback()

            # Update status
            db_recording = db.query(Recording).filter_by(id=recording.id).first()
            db_recording.status = ProcessingStatus.FAILED
            db_recording.error_message = str(e)[:500]
            db.commit()

            # Move to failed directory
            audio_path = Path(recording.audio_path)
            if audio_path.exists():
                failed_path = self.failed_dir / audio_path.name
                audio_path.rename(failed_path)

            self.stats['failed'] += 1
            return False

        finally:
            db.close()

    def _get_audio_url(self, audio_path: Path) -> Optional[str]:
        """
        Get a URL for the audio file (upload to temporary storage)

        For now, using Google Drive temporary upload
        In production, could use S3, GCS, or other cloud storage
        """
        try:
            # Upload to Google Drive temporarily
            file_id = self.drive_manager.upload_audio(
                str(audio_path),
                f"temp_{audio_path.stem}"
            )

            if file_id:
                # Return direct download URL
                return f"https://drive.google.com/uc?export=download&id={file_id}"

            return None

        except Exception as e:
            logger.error(f"Failed to create audio URL: {e}")
            return None

    def process_queue(self, limit: int = 10) -> Dict:
        """
        Process recordings from the queue

        Args:
            limit: Maximum number to process

        Returns:
            Processing summary
        """
        start_time = time.time()
        logger.info(f"Starting queue processing (limit: {limit})")

        # Reset stats
        self.stats = {
            'processed': 0,
            'failed': 0,
            'skipped': 0,
            'duplicates': 0
        }

        # Get pending recordings
        recordings = self.get_pending_recordings(limit)
        logger.info(f"Found {len(recordings)} recordings to process")

        # Process each recording
        for recording in recordings:
            try:
                self.process_recording(recording)

                # Rate limiting for Salad API
                time.sleep(5)  # 5 seconds between recordings

            except Exception as e:
                logger.error(f"Unexpected error processing {recording.ringcentral_id}: {e}")
                self.stats['failed'] += 1

        # Calculate summary
        elapsed = time.time() - start_time
        summary = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds': round(elapsed, 2),
            'recordings_found': len(recordings),
            **self.stats
        }

        logger.info(f"Queue processing complete: {summary}")

        # Save summary
        summary_file = Path('/var/www/call-recording-system/data/scheduler/processing_summary.json')
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        return summary

    def get_queue_status(self) -> Dict:
        """Get current queue status"""
        db = SessionLocal()
        try:
            return {
                'audio_queue': len(list(self.queue_dir.glob('*.mp3'))),
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
                ).count(),
                'total': db.query(Recording).count()
            }
        finally:
            db.close()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Process transcription queue')
    parser.add_argument('--limit', type=int, default=10,
                       help='Maximum recordings to process')
    parser.add_argument('--status', action='store_true',
                       help='Show queue status only')

    args = parser.parse_args()

    # Initialize processor
    processor = TranscriptionProcessor()

    if args.status:
        # Show status
        status = processor.get_queue_status()
        print("\n=== Transcription Queue Status ===")
        for key, value in status.items():
            print(f"  {key}: {value}")
        print()
    else:
        # Process queue
        summary = processor.process_queue(limit=args.limit)
        print(f"\nProcessing complete:")
        print(f"  Processed: {summary['processed']}")
        print(f"  Failed: {summary['failed']}")
        print(f"  Duplicates: {summary['duplicates']}")
        print(f"  Time: {summary['elapsed_seconds']}s")


if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""
One-time historical catch-up script to process call recordings from July 1 - Sept 17, 2025
Downloads, transcribes, and uploads recordings to Google Drive
"""

import os
import logging
import json
import time
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
from pathlib import Path
import concurrent.futures

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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('historical_catchup.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class HistoricalProcessor:
    """Process historical call recordings"""

    def __init__(self, max_workers: int = 4):
        """Initialize the processor"""
        self.settings = Settings()
        self.max_workers = max_workers
        self.statistics = defaultdict(lambda: {
            'total': 0,
            'downloaded': 0,
            'transcribed': 0,
            'uploaded': 0,
            'failed': 0,
            'duration_seconds': 0,
            'recordings': []
        })

        # Initialize components
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

        logger.info("Components initialized successfully")

    def fetch_recordings(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Fetch all recordings in date range"""
        logger.info(f"Fetching recordings from {start_date} to {end_date}")

        recordings = []
        try:
            for record in self.ringcentral_client.get_all_call_logs(
                date_from=start_date,
                date_to=end_date,
                recording_type='All'
            ):
                recording_info = record.get('recording', {})
                if recording_info:
                    # Extract month for statistics
                    call_date = datetime.fromisoformat(
                        record.get('startTime', '').replace('Z', '+00:00')
                    )
                    month_key = call_date.strftime('%Y-%m')

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
                        'month': month_key
                    }

                    recordings.append(call_data)
                    self.statistics[month_key]['total'] += 1
                    self.statistics[month_key]['duration_seconds'] += call_data['duration']

        except Exception as e:
            logger.error(f"Error fetching recordings: {e}")
            raise

        logger.info(f"Fetched {len(recordings)} recordings")
        return recordings

    def process_recording(self, recording: Dict[str, Any]) -> Tuple[bool, str]:
        """Process a single recording: download, transcribe, upload"""
        recording_id = recording['recording_id']
        month = recording['month']

        logger.info(f"Processing recording {recording_id} from {recording['start_time']}")

        try:
            # Check if already processed
            with self.session_manager.get_session() as session:
                existing = session.query(CallRecording).filter_by(
                    recording_id=recording_id
                ).first()

                if existing and existing.processing_state == ProcessingStatus.COMPLETED:
                    logger.info(f"Recording {recording_id} already processed, skipping")
                    self.statistics[month]['uploaded'] += 1
                    return True, "Already processed"

                # Create or update database record
                if not existing:
                    db_record = CallRecording(
                        recording_id=recording_id,
                        call_id=recording['call_id'],
                        session_id=recording['session_id'],
                        start_time=datetime.fromisoformat(
                            recording['start_time'].replace('Z', '+00:00')
                        ),
                        duration=recording['duration'],
                        from_number=recording['from_number'],
                        to_number=recording['to_number'],
                        direction=recording['direction'],
                        processing_state=ProcessingStatus.PENDING
                    )
                    session.add(db_record)
                else:
                    db_record = existing
                    db_record.processing_state = ProcessingStatus.DOWNLOADING

                session.commit()

            # Create temp directory for this recording
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # 1. Download recording
                logger.info(f"Downloading recording {recording_id}")
                audio_path = temp_path / f"{recording_id}.mp3"

                try:
                    self.ringcentral_client.download_recording(
                        recording_id=recording_id,
                        output_path=str(audio_path)
                    )
                    self.statistics[month]['downloaded'] += 1

                    # Update database
                    with self.session_manager.get_session() as session:
                        db_record = session.query(CallRecording).filter_by(
                            recording_id=recording_id
                        ).first()
                        db_record.processing_state = ProcessingStatus.TRANSCRIBING
                        db_record.download_path = str(audio_path)
                        session.commit()

                except Exception as e:
                    logger.error(f"Failed to download recording {recording_id}: {e}")
                    self._mark_failed(recording_id, ProcessingStatus.DOWNLOAD_FAILED, str(e))
                    self.statistics[month]['failed'] += 1
                    return False, f"Download failed: {e}"

                # 2. Transcribe recording
                logger.info(f"Transcribing recording {recording_id}")
                try:
                    transcription_result = self.transcription_pipeline.transcribe(
                        audio_path=str(audio_path)
                    )

                    # Parse datetime for better formatting
                    call_datetime = datetime.fromisoformat(
                        recording['start_time'].replace('Z', '+00:00')
                    )

                    # Create comprehensive metadata
                    metadata = {
                        # Call Identification
                        'recording_id': recording_id,
                        'call_id': recording['call_id'],
                        'session_id': recording['session_id'],

                        # Time Information
                        'start_time': recording['start_time'],
                        'date': call_datetime.strftime('%Y-%m-%d'),
                        'time': call_datetime.strftime('%H:%M:%S UTC'),
                        'day_of_week': call_datetime.strftime('%A'),
                        'duration_seconds': recording['duration'],
                        'duration_formatted': f"{recording['duration']//60}m {recording['duration']%60}s",

                        # Participants
                        'from': {
                            'name': recording['from_name'] or 'Unknown',
                            'number': recording['from_number'] or 'Unknown',
                            'formatted': f"{recording['from_name'] or 'Unknown'} ({recording['from_number'] or 'N/A'})"
                        },
                        'to': {
                            'name': recording['to_name'] or 'Unknown',
                            'number': recording['to_number'] or 'Unknown',
                            'formatted': f"{recording['to_name'] or 'Unknown'} ({recording['to_number'] or 'N/A'})"
                        },

                        # Call Details
                        'direction': recording['direction'],
                        'recording_type': recording.get('recording_type', 'Unknown'),

                        # Transcription Data
                        'transcription': {
                            'full_text': transcription_result.get('text', ''),
                            'language': transcription_result.get('language', 'en'),
                            'segments': transcription_result.get('segments', []),
                            'word_count': len(transcription_result.get('text', '').split()),
                            'confidence_score': transcription_result.get('confidence', None)
                        },

                        # Processing Information
                        'processing': {
                            'processed_date': datetime.now(timezone.utc).isoformat(),
                            'processor_version': '1.0',
                            'whisper_model': getattr(self.settings, 'whisper_model', 'base'),
                            'processing_device': getattr(self.settings, 'whisper_device', 'cpu')
                        },

                        # Additional Context
                        'metadata_version': '2.0',
                        'organization': 'Call Recording System',
                        'tags': [],  # Can be expanded for categorization
                        'notes': ''  # Can be used for additional notes
                    }

                    # Save transcription with full metadata
                    transcription_path = temp_path / f"{recording_id}_transcription.json"
                    with open(transcription_path, 'w') as f:
                        json.dump(metadata, f, indent=2, default=str)

                    # Also create a human-readable text version
                    text_path = temp_path / f"{recording_id}_transcription.txt"
                    with open(text_path, 'w') as f:
                        f.write("=" * 80 + "\n")
                        f.write("CALL TRANSCRIPTION REPORT\n")
                        f.write("=" * 80 + "\n\n")

                        f.write("CALL INFORMATION:\n")
                        f.write("-" * 40 + "\n")
                        f.write(f"Recording ID: {recording_id}\n")
                        f.write(f"Date: {metadata['date']} ({metadata['day_of_week']})\n")
                        f.write(f"Time: {metadata['time']}\n")
                        f.write(f"Duration: {metadata['duration_formatted']}\n")
                        f.write(f"Direction: {metadata['direction']}\n")
                        f.write(f"Type: {metadata['recording_type']}\n\n")

                        f.write("PARTICIPANTS:\n")
                        f.write("-" * 40 + "\n")
                        f.write(f"From: {metadata['from']['formatted']}\n")
                        f.write(f"To: {metadata['to']['formatted']}\n\n")

                        f.write("TRANSCRIPTION:\n")
                        f.write("-" * 40 + "\n")
                        f.write(f"Language: {metadata['transcription']['language']}\n")
                        f.write(f"Word Count: {metadata['transcription']['word_count']}\n\n")
                        f.write("Full Text:\n")
                        f.write("-" * 40 + "\n")
                        f.write(metadata['transcription']['full_text'] or "[No transcription available]")
                        f.write("\n\n")

                        # Add segments with timestamps if available
                        if metadata['transcription']['segments']:
                            f.write("DETAILED SEGMENTS:\n")
                            f.write("-" * 40 + "\n")
                            for segment in metadata['transcription']['segments']:
                                start_time = segment.get('start', 0)
                                end_time = segment.get('end', 0)
                                text = segment.get('text', '')
                                f.write(f"[{start_time:.2f}s - {end_time:.2f}s]: {text}\n")

                        f.write("\n" + "=" * 80 + "\n")
                        f.write(f"Processed: {metadata['processing']['processed_date']}\n")
                        f.write("=" * 80 + "\n")

                    self.statistics[month]['transcribed'] += 1

                    # Update database
                    with self.session_manager.get_session() as session:
                        db_record = session.query(CallRecording).filter_by(
                            recording_id=recording_id
                        ).first()
                        db_record.processing_state = ProcessingStatus.UPLOADING
                        db_record.transcription = transcription_result.get('text', '')
                        session.commit()

                except Exception as e:
                    logger.error(f"Failed to transcribe recording {recording_id}: {e}")
                    self._mark_failed(recording_id, ProcessingStatus.TRANSCRIPTION_FAILED, str(e))
                    self.statistics[month]['failed'] += 1
                    return False, f"Transcription failed: {e}"

                # 3. Upload to Google Drive
                logger.info(f"Uploading recording {recording_id} to Google Drive")
                try:
                    # Create folder structure: /Call Recordings/2025/07-July/
                    call_date = datetime.fromisoformat(
                        recording['start_time'].replace('Z', '+00:00')
                    )
                    year = call_date.strftime('%Y')
                    month_folder = call_date.strftime('%m-%B')

                    # Upload audio file
                    audio_file_id = self.drive_manager.upload_file(
                        file_path=str(audio_path),
                        folder_path=f"Call Recordings/{year}/{month_folder}/Audio",
                        description=f"Call recording from {recording['start_time']}"
                    )

                    # Upload JSON transcription (with full metadata)
                    transcript_json_id = self.drive_manager.upload_file(
                        file_path=str(transcription_path),
                        folder_path=f"Call Recordings/{year}/{month_folder}/Transcripts/JSON",
                        description=f"Transcription JSON with metadata for call {recording_id}"
                    )

                    # Upload text transcription (human-readable)
                    transcript_text_id = self.drive_manager.upload_file(
                        file_path=str(text_path),
                        folder_path=f"Call Recordings/{year}/{month_folder}/Transcripts/Text",
                        description=f"Transcription text for call {recording_id}"
                    )

                    self.statistics[month]['uploaded'] += 1

                    # Update database
                    with self.session_manager.get_session() as session:
                        db_record = session.query(CallRecording).filter_by(
                            recording_id=recording_id
                        ).first()
                        db_record.processing_state = ProcessingStatus.COMPLETED
                        db_record.drive_audio_id = audio_file_id
                        db_record.drive_transcript_id = transcript_json_id  # Store JSON transcript ID
                        db_record.completed_at = datetime.now(timezone.utc)
                        session.commit()

                    logger.info(f"Successfully processed recording {recording_id}")
                    return True, "Success"

                except Exception as e:
                    logger.error(f"Failed to upload recording {recording_id}: {e}")
                    self._mark_failed(recording_id, ProcessingStatus.UPLOAD_FAILED, str(e))
                    self.statistics[month]['failed'] += 1
                    return False, f"Upload failed: {e}"

        except Exception as e:
            logger.error(f"Unexpected error processing recording {recording_id}: {e}")
            self.statistics[month]['failed'] += 1
            return False, f"Unexpected error: {e}"

    def _mark_failed(self, recording_id: str, state: ProcessingStatus, error: str):
        """Mark a recording as failed in the database"""
        with self.session_manager.get_session() as session:
            record = session.query(CallRecording).filter_by(
                recording_id=recording_id
            ).first()
            if record:
                record.processing_state = state
                record.error_message = error
                record.retry_count = record.retry_count + 1 if record.retry_count else 1
                session.commit()

    def process_batch(self, recordings: List[Dict[str, Any]], batch_size: int = 10):
        """Process recordings in batches with parallel processing"""
        total = len(recordings)
        processed = 0

        logger.info(f"Processing {total} recordings in batches of {batch_size}")

        # Process in batches
        for i in range(0, total, batch_size):
            batch = recordings[i:i+batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches}")

            # Process batch in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self.process_recording, rec): rec
                    for rec in batch
                }

                for future in concurrent.futures.as_completed(futures):
                    recording = futures[future]
                    try:
                        success, message = future.result(timeout=300)  # 5 minute timeout
                        processed += 1

                        if success:
                            logger.info(f"✅ [{processed}/{total}] Recording {recording['recording_id']}: {message}")
                        else:
                            logger.warning(f"❌ [{processed}/{total}] Recording {recording['recording_id']}: {message}")

                    except concurrent.futures.TimeoutError:
                        logger.error(f"⏰ [{processed}/{total}] Recording {recording['recording_id']}: Timeout")
                        self.statistics[recording['month']]['failed'] += 1
                    except Exception as e:
                        logger.error(f"💥 [{processed}/{total}] Recording {recording['recording_id']}: {e}")
                        self.statistics[recording['month']]['failed'] += 1

            # Small delay between batches to avoid overwhelming the system
            if i + batch_size < total:
                logger.info("Pausing between batches...")
                time.sleep(2)

        logger.info(f"Batch processing complete: {processed}/{total} recordings")

    def generate_summary(self, start_date: datetime, end_date: datetime) -> str:
        """Generate a summary report of processed recordings"""
        report = []
        report.append("=" * 100)
        report.append("📊 HISTORICAL CALL RECORDING PROCESSING SUMMARY")
        report.append("=" * 100)
        report.append(f"\n📅 Period: {start_date.date()} to {end_date.date()}")
        report.append(f"⏰ Processing completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Overall statistics
        total_recordings = sum(stats['total'] for stats in self.statistics.values())
        total_downloaded = sum(stats['downloaded'] for stats in self.statistics.values())
        total_transcribed = sum(stats['transcribed'] for stats in self.statistics.values())
        total_uploaded = sum(stats['uploaded'] for stats in self.statistics.values())
        total_failed = sum(stats['failed'] for stats in self.statistics.values())
        total_duration = sum(stats['duration_seconds'] for stats in self.statistics.values())

        report.append(f"\n📈 OVERALL STATISTICS:")
        report.append(f"  Total Recordings Found: {total_recordings}")
        report.append(f"  Successfully Downloaded: {total_downloaded}")
        report.append(f"  Successfully Transcribed: {total_transcribed}")
        report.append(f"  Successfully Uploaded: {total_uploaded}")
        report.append(f"  Failed: {total_failed}")
        report.append(f"  Success Rate: {(total_uploaded/total_recordings*100 if total_recordings else 0):.1f}%")
        report.append(f"  Total Duration: {total_duration/3600:.2f} hours")

        # Monthly breakdown
        report.append(f"\n📅 MONTHLY BREAKDOWN:")
        report.append("-" * 80)

        for month in sorted(self.statistics.keys()):
            stats = self.statistics[month]
            month_date = datetime.strptime(month, '%Y-%m')
            month_name = month_date.strftime('%B %Y')

            report.append(f"\n📆 {month_name}:")
            report.append(f"  Total Recordings: {stats['total']}")
            report.append(f"  Downloaded: {stats['downloaded']}")
            report.append(f"  Transcribed: {stats['transcribed']}")
            report.append(f"  Uploaded: {stats['uploaded']}")
            report.append(f"  Failed: {stats['failed']}")
            report.append(f"  Duration: {stats['duration_seconds']/3600:.2f} hours")

            if stats['total'] > 0:
                success_rate = (stats['uploaded'] / stats['total']) * 100
                report.append(f"  Success Rate: {success_rate:.1f}%")

        # Database summary
        with self.session_manager.get_session() as session:
            db_stats = session.query(
                CallRecording.processing_state,
                session.query(CallRecording).filter_by(
                    processing_state=CallRecording.processing_state
                ).count()
            ).group_by(CallRecording.processing_state).all()

            if db_stats:
                report.append(f"\n💾 DATABASE STATUS:")
                for state, count in db_stats:
                    if count > 0:
                        report.append(f"  {state.value}: {count}")

        report.append("\n" + "=" * 100)
        report.append("✅ Historical processing complete!")
        report.append("=" * 100)

        return "\n".join(report)

    def run(self, start_date: datetime, end_date: datetime, batch_size: int = 10):
        """Run the complete historical processing"""
        logger.info("Starting historical call recording processing")
        logger.info(f"Date range: {start_date} to {end_date}")

        try:
            # Fetch all recordings
            recordings = self.fetch_recordings(start_date, end_date)

            if not recordings:
                logger.warning("No recordings found in the specified date range")
                return

            # Process recordings in batches
            self.process_batch(recordings, batch_size)

            # Generate and save summary
            summary = self.generate_summary(start_date, end_date)

            # Print summary
            print(summary)

            # Save summary to file
            summary_file = f"historical_processing_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(summary_file, 'w') as f:
                f.write(summary)

            logger.info(f"Summary saved to {summary_file}")

            # Also save detailed statistics as JSON
            stats_file = f"historical_processing_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(stats_file, 'w') as f:
                json.dump(dict(self.statistics), f, indent=2, default=str)

            logger.info(f"Detailed statistics saved to {stats_file}")

        except Exception as e:
            logger.error(f"Fatal error during processing: {e}")
            raise
        finally:
            # Cleanup
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        try:
            if hasattr(self, 'ringcentral_auth'):
                self.ringcentral_auth.close()
            if hasattr(self, 'session_manager'):
                self.session_manager.close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


def main():
    """Main entry point"""
    print("\n" + "=" * 100)
    print("🚀 HISTORICAL CALL RECORDING CATCH-UP PROCESSOR")
    print("=" * 100)

    # Define date range
    start_date = datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    end_date = datetime(2025, 9, 17, 23, 59, 59, tzinfo=timezone.utc)

    print(f"\n📅 Processing Period: {start_date.date()} to {end_date.date()}")
    print(f"⚙️  Max Workers: 4")
    print(f"📦 Batch Size: 10 recordings")

    response = input("\n⚠️  This will process all recordings in the specified period. Continue? (yes/no): ")

    if response.lower() != 'yes':
        print("❌ Processing cancelled")
        return

    print("\n🔄 Starting processing...\n")

    try:
        # Create processor and run
        processor = HistoricalProcessor(max_workers=4)
        processor.run(
            start_date=start_date,
            end_date=end_date,
            batch_size=10
        )

        print("\n✅ Historical processing completed successfully!")

    except KeyboardInterrupt:
        print("\n\n⚠️  Processing interrupted by user")
        logger.warning("Processing interrupted by user")
    except Exception as e:
        print(f"\n❌ Processing failed: {e}")
        logger.error(f"Processing failed: {e}")
        raise


if __name__ == "__main__":
    main()
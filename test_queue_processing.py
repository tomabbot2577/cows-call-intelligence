#!/usr/bin/env python3
"""
Queue-based processing system for call recordings
Downloads -> Transcription Queue -> Upload Queue
"""

import os
import logging
import json
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, Lock, Event
from dataclasses import dataclass, asdict

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


@dataclass
class RecordingTask:
    """Container for a recording processing task"""
    recording_data: Dict[str, Any]
    audio_path: Optional[str] = None
    transcription: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    db_record_id: Optional[int] = None
    temp_dir: Optional[str] = None
    status: str = "pending"
    error: Optional[str] = None


class QueueProcessor:
    """Process recordings through download -> transcribe -> upload queues"""

    def __init__(self, max_concurrent_downloads: int = 3,
                 max_concurrent_transcriptions: int = 2,
                 max_concurrent_uploads: int = 3):
        """Initialize the queue processor"""
        self.settings = Settings()

        # Processing queues
        self.download_queue = Queue()
        self.transcription_queue = Queue()
        self.upload_queue = Queue()
        self.completed_tasks = []

        # Thread control
        self.stop_event = Event()
        self.threads = []
        self.max_concurrent_downloads = max_concurrent_downloads
        self.max_concurrent_transcriptions = max_concurrent_transcriptions
        self.max_concurrent_uploads = max_concurrent_uploads

        # Statistics
        self.stats_lock = Lock()
        self.stats = {
            'total': 0,
            'downloaded': 0,
            'transcribed': 0,
            'uploaded': 0,
            'failed': 0,
            'download_bytes': 0,
            'processing_time': 0
        }

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

        logger.info("✅ Components initialized successfully")

    def start_workers(self):
        """Start all worker threads"""
        logger.info("Starting worker threads...")

        # Download workers
        for i in range(self.max_concurrent_downloads):
            thread = Thread(target=self._download_worker, args=(i,))
            thread.daemon = True
            thread.start()
            self.threads.append(thread)
            logger.info(f"  Started download worker {i+1}")

        # Transcription workers
        for i in range(self.max_concurrent_transcriptions):
            thread = Thread(target=self._transcription_worker, args=(i,))
            thread.daemon = True
            thread.start()
            self.threads.append(thread)
            logger.info(f"  Started transcription worker {i+1}")

        # Upload workers
        for i in range(self.max_concurrent_uploads):
            thread = Thread(target=self._upload_worker, args=(i,))
            thread.daemon = True
            thread.start()
            self.threads.append(thread)
            logger.info(f"  Started upload worker {i+1}")

        # Statistics reporter
        thread = Thread(target=self._stats_reporter)
        thread.daemon = True
        thread.start()
        self.threads.append(thread)

    def _download_worker(self, worker_id: int):
        """Worker thread for downloading recordings"""
        logger.info(f"Download worker {worker_id} started")

        while not self.stop_event.is_set():
            try:
                # Get task from queue (timeout allows checking stop_event)
                task = self.download_queue.get(timeout=1)

                logger.info(f"[DL-{worker_id}] Downloading recording {task.recording_data['recording_id']}")

                # Create temp directory for this recording
                task.temp_dir = tempfile.mkdtemp()
                audio_path = Path(task.temp_dir) / f"{task.recording_data['recording_id']}.mp3"

                try:
                    # Download the recording
                    self.ringcentral_client.download_recording(
                        recording_id=task.recording_data['recording_id'],
                        output_path=str(audio_path)
                    )

                    file_size = audio_path.stat().st_size
                    task.audio_path = str(audio_path)
                    task.status = "downloaded"

                    # Update stats
                    with self.stats_lock:
                        self.stats['downloaded'] += 1
                        self.stats['download_bytes'] += file_size

                    # Update database
                    self._update_db_status(task, 'download', ProcessingStatus.COMPLETED)

                    logger.info(f"[DL-{worker_id}] ✅ Downloaded {file_size:,} bytes")

                    # Move to transcription queue
                    self.transcription_queue.put(task)

                except Exception as e:
                    logger.error(f"[DL-{worker_id}] ❌ Download failed: {e}")
                    task.error = str(e)
                    task.status = "download_failed"
                    with self.stats_lock:
                        self.stats['failed'] += 1
                    self._update_db_status(task, 'download', ProcessingStatus.FAILED, str(e))

            except Empty:
                continue
            except Exception as e:
                logger.error(f"[DL-{worker_id}] Worker error: {e}")

    def _transcription_worker(self, worker_id: int):
        """Worker thread for transcribing recordings"""
        logger.info(f"Transcription worker {worker_id} started")

        while not self.stop_event.is_set():
            try:
                # Get task from queue
                task = self.transcription_queue.get(timeout=1)

                logger.info(f"[TX-{worker_id}] Transcribing recording {task.recording_data['recording_id']}")

                try:
                    start_time = time.time()

                    # Transcribe the audio
                    transcription_result = self.transcription_pipeline.process(
                        audio_path=task.audio_path
                    )

                    # Parse datetime for metadata
                    call_datetime = datetime.fromisoformat(
                        task.recording_data['start_time'].replace('Z', '+00:00')
                    )

                    # Create comprehensive metadata
                    task.metadata = {
                        'recording_id': task.recording_data['recording_id'],
                        'call_id': task.recording_data['call_id'],
                        'session_id': task.recording_data['session_id'],
                        'start_time': task.recording_data['start_time'],
                        'date': call_datetime.strftime('%Y-%m-%d'),
                        'time': call_datetime.strftime('%H:%M:%S UTC'),
                        'day_of_week': call_datetime.strftime('%A'),
                        'duration_seconds': task.recording_data['duration'],
                        'duration_formatted': f"{task.recording_data['duration']//60}m {task.recording_data['duration']%60}s",
                        'from': {
                            'name': task.recording_data['from_name'] or 'Unknown',
                            'number': task.recording_data['from_number'] or 'Unknown',
                        },
                        'to': {
                            'name': task.recording_data['to_name'] or 'Unknown',
                            'number': task.recording_data['to_number'] or 'Unknown',
                        },
                        'direction': task.recording_data['direction'],
                        'transcription': {
                            'full_text': transcription_result.get('text', ''),
                            'language': transcription_result.get('language', 'en'),
                            'segments': transcription_result.get('segments', []),
                            'word_count': len(transcription_result.get('text', '').split())
                        },
                        'processing': {
                            'processed_date': datetime.now(timezone.utc).isoformat(),
                            'whisper_model': getattr(self.settings, 'whisper_model', 'base'),
                            'processing_time': time.time() - start_time
                        }
                    }

                    task.transcription = transcription_result
                    task.status = "transcribed"

                    # Save transcription files
                    self._save_transcription_files(task)

                    # Update stats
                    with self.stats_lock:
                        self.stats['transcribed'] += 1
                        self.stats['processing_time'] += (time.time() - start_time)

                    # Update database
                    self._update_db_status(task, 'transcription', ProcessingStatus.COMPLETED)

                    word_count = task.metadata['transcription']['word_count']
                    logger.info(f"[TX-{worker_id}] ✅ Transcribed: {word_count} words")

                    # Move to upload queue
                    self.upload_queue.put(task)

                except Exception as e:
                    logger.error(f"[TX-{worker_id}] ❌ Transcription failed: {e}")
                    task.error = str(e)
                    task.status = "transcription_failed"
                    with self.stats_lock:
                        self.stats['failed'] += 1
                    self._update_db_status(task, 'transcription', ProcessingStatus.FAILED, str(e))

            except Empty:
                continue
            except Exception as e:
                logger.error(f"[TX-{worker_id}] Worker error: {e}")

    def _upload_worker(self, worker_id: int):
        """Worker thread for uploading to Google Drive"""
        logger.info(f"Upload worker {worker_id} started")

        while not self.stop_event.is_set():
            try:
                # Get task from queue
                task = self.upload_queue.get(timeout=1)

                logger.info(f"[UP-{worker_id}] Uploading recording {task.recording_data['recording_id']}")

                try:
                    # Get file paths
                    audio_path = Path(task.audio_path)
                    json_path = Path(task.temp_dir) / f"{task.recording_data['recording_id']}_transcription.json"
                    text_path = Path(task.temp_dir) / f"{task.recording_data['recording_id']}_transcription.txt"

                    # Create folder structure
                    call_datetime = datetime.fromisoformat(
                        task.recording_data['start_time'].replace('Z', '+00:00')
                    )
                    year = call_datetime.strftime('%Y')
                    month_folder = call_datetime.strftime('%m-%B')

                    # Upload audio file
                    audio_file_id = self.drive_manager.upload_file(
                        file_path=str(audio_path),
                        folder_path=f"Call Recordings/{year}/{month_folder}/Audio",
                        description=f"Call recording from {task.recording_data['start_time']}"
                    )

                    # Upload JSON transcription
                    json_file_id = self.drive_manager.upload_file(
                        file_path=str(json_path),
                        folder_path=f"Call Recordings/{year}/{month_folder}/Transcripts/JSON",
                        description=f"Transcription JSON for call {task.recording_data['recording_id']}"
                    )

                    # Upload text transcription
                    text_file_id = self.drive_manager.upload_file(
                        file_path=str(text_path),
                        folder_path=f"Call Recordings/{year}/{month_folder}/Transcripts/Text",
                        description=f"Transcription text for call {task.recording_data['recording_id']}"
                    )

                    task.status = "completed"

                    # Update stats
                    with self.stats_lock:
                        self.stats['uploaded'] += 1

                    # Update database
                    self._update_db_status(task, 'upload', ProcessingStatus.COMPLETED,
                                          google_drive_id=audio_file_id)

                    logger.info(f"[UP-{worker_id}] ✅ Uploaded to Google Drive")

                    # Add to completed tasks
                    self.completed_tasks.append(task)

                    # Clean up temp directory
                    self._cleanup_temp_files(task)

                except Exception as e:
                    logger.error(f"[UP-{worker_id}] ❌ Upload failed: {e}")
                    task.error = str(e)
                    task.status = "upload_failed"
                    with self.stats_lock:
                        self.stats['failed'] += 1
                    self._update_db_status(task, 'upload', ProcessingStatus.FAILED, str(e))

            except Empty:
                continue
            except Exception as e:
                logger.error(f"[UP-{worker_id}] Worker error: {e}")

    def _stats_reporter(self):
        """Periodically report processing statistics"""
        last_report = time.time()
        report_interval = 10  # seconds

        while not self.stop_event.is_set():
            time.sleep(1)

            if time.time() - last_report >= report_interval:
                with self.stats_lock:
                    if self.stats['total'] > 0:
                        logger.info(f"\n📊 PROGRESS REPORT:")
                        logger.info(f"  Total: {self.stats['total']}")
                        logger.info(f"  Downloaded: {self.stats['downloaded']} ({self.stats['download_bytes']:,} bytes)")
                        logger.info(f"  Transcribed: {self.stats['transcribed']}")
                        logger.info(f"  Uploaded: {self.stats['uploaded']}")
                        logger.info(f"  Failed: {self.stats['failed']}")
                        logger.info(f"  Queue sizes - DL: {self.download_queue.qsize()}, TX: {self.transcription_queue.qsize()}, UP: {self.upload_queue.qsize()}")

                last_report = time.time()

    def _save_transcription_files(self, task: RecordingTask):
        """Save transcription to JSON and text files"""
        temp_path = Path(task.temp_dir)

        # Save JSON
        json_path = temp_path / f"{task.recording_data['recording_id']}_transcription.json"
        with open(json_path, 'w') as f:
            json.dump(task.metadata, f, indent=2, default=str)

        # Save text
        text_path = temp_path / f"{task.recording_data['recording_id']}_transcription.txt"
        with open(text_path, 'w') as f:
            f.write(f"CALL TRANSCRIPTION\n")
            f.write(f"{'='*60}\n")
            f.write(f"Recording ID: {task.recording_data['recording_id']}\n")
            f.write(f"Date: {task.metadata['date']} ({task.metadata['day_of_week']})\n")
            f.write(f"Time: {task.metadata['time']}\n")
            f.write(f"Duration: {task.metadata['duration_formatted']}\n")
            f.write(f"From: {task.metadata['from']['name']} ({task.metadata['from']['number']})\n")
            f.write(f"To: {task.metadata['to']['name']} ({task.metadata['to']['number']})\n")
            f.write(f"Direction: {task.metadata['direction']}\n\n")
            f.write(f"TRANSCRIPTION:\n")
            f.write(f"{'-'*60}\n")
            f.write(task.metadata['transcription']['full_text'] or "[No transcription available]")

    def _update_db_status(self, task: RecordingTask, stage: str, status: ProcessingStatus,
                         error: str = None, google_drive_id: str = None):
        """Update processing status in database"""
        if not task.db_record_id:
            # Create DB record if not exists
            with self.session_manager.get_session() as session:
                existing = session.query(CallRecording).filter_by(
                    recording_id=task.recording_data['recording_id']
                ).first()

                if not existing:
                    db_record = CallRecording(
                        call_id=task.recording_data['call_id'],
                        recording_id=task.recording_data['recording_id'],
                        session_id=task.recording_data['session_id'],
                        start_time=datetime.fromisoformat(
                            task.recording_data['start_time'].replace('Z', '+00:00')
                        ),
                        duration=task.recording_data['duration'],
                        from_number=task.recording_data['from_number'],
                        from_name=task.recording_data['from_name'],
                        to_number=task.recording_data['to_number'],
                        to_name=task.recording_data['to_name'],
                        direction=task.recording_data['direction'],
                        recording_type=task.recording_data.get('recording_type', 'Unknown'),
                        download_status=ProcessingStatus.PENDING,
                        transcription_status=ProcessingStatus.PENDING,
                        upload_status=ProcessingStatus.PENDING
                    )
                    session.add(db_record)
                    session.commit()
                    task.db_record_id = db_record.id
                else:
                    task.db_record_id = existing.id

        # Update status
        with self.session_manager.get_session() as session:
            record = session.get(CallRecording, task.db_record_id)
            if record:
                if stage == 'download':
                    record.download_status = status
                    if status == ProcessingStatus.COMPLETED:
                        record.download_completed_at = datetime.now(timezone.utc)
                        record.local_file_path = task.audio_path
                        record.file_size_bytes = Path(task.audio_path).stat().st_size
                    else:
                        record.download_error = error

                elif stage == 'transcription':
                    record.transcription_status = status
                    if status == ProcessingStatus.COMPLETED:
                        record.transcription_completed_at = datetime.now(timezone.utc)
                        if task.metadata:
                            record.transcript_word_count = task.metadata['transcription']['word_count']
                            record.language_detected = task.metadata['transcription']['language']
                    else:
                        record.transcription_error = error

                elif stage == 'upload':
                    record.upload_status = status
                    if status == ProcessingStatus.COMPLETED:
                        record.upload_completed_at = datetime.now(timezone.utc)
                        record.google_drive_file_id = google_drive_id
                    else:
                        record.upload_error = error

                session.commit()

    def _cleanup_temp_files(self, task: RecordingTask):
        """Clean up temporary files after processing"""
        try:
            if task.temp_dir and os.path.exists(task.temp_dir):
                import shutil
                shutil.rmtree(task.temp_dir)
        except Exception as e:
            logger.warning(f"Failed to clean up temp files: {e}")

    def process_recordings(self, limit: int = 15):
        """Main processing function"""
        print("\n" + "="*70)
        print("🚀 QUEUE-BASED RECORDING PROCESSOR")
        print("="*70)
        print(f"  Max concurrent downloads: {self.max_concurrent_downloads}")
        print(f"  Max concurrent transcriptions: {self.max_concurrent_transcriptions}")
        print(f"  Max concurrent uploads: {self.max_concurrent_uploads}")
        print("="*70)

        try:
            # Start worker threads
            self.start_workers()

            # Fetch recordings
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=7)

            logger.info(f"\n📅 Fetching recordings from {start_date.date()} to {end_date.date()}")

            recordings = []
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

            logger.info(f"✅ Found {len(recordings)} recordings")

            # Add recordings to download queue
            with self.stats_lock:
                self.stats['total'] = len(recordings)

            for recording in recordings:
                task = RecordingTask(recording_data=recording)
                self.download_queue.put(task)

            logger.info(f"📥 Added {len(recordings)} recordings to download queue")

            # Wait for all processing to complete
            print("\n⏳ Processing recordings...")
            print("This will download, transcribe, and upload all recordings.")
            print("Progress updates will be shown every 10 seconds.\n")

            # Wait for completion
            while True:
                with self.stats_lock:
                    if self.stats['uploaded'] + self.stats['failed'] >= self.stats['total']:
                        break
                time.sleep(1)

            # Final report
            print("\n" + "="*70)
            print("📊 FINAL PROCESSING SUMMARY")
            print("="*70)
            with self.stats_lock:
                print(f"  Total Processed: {self.stats['total']}")
                print(f"  ✅ Successfully Uploaded: {self.stats['uploaded']}")
                print(f"  ❌ Failed: {self.stats['failed']}")
                print(f"  Total Downloaded: {self.stats['download_bytes']:,} bytes")
                print(f"  Average Processing Time: {self.stats['processing_time']/max(1, self.stats['transcribed']):.2f}s")
                success_rate = (self.stats['uploaded'] / max(1, self.stats['total'])) * 100
                print(f"  Success Rate: {success_rate:.1f}%")

            print("\n✨ Processing complete!")
            print("📁 Check your Google Drive: Call Recordings/2025/[Month]/")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            raise
        finally:
            # Stop all workers
            self.stop_event.set()

            # Wait for threads to finish
            for thread in self.threads:
                thread.join(timeout=5)

            # Cleanup
            if hasattr(self, 'ringcentral_auth'):
                self.ringcentral_auth.close()
            if hasattr(self, 'session_manager'):
                self.session_manager.close()


def main():
    """Main entry point"""
    processor = QueueProcessor(
        max_concurrent_downloads=3,
        max_concurrent_transcriptions=2,
        max_concurrent_uploads=3
    )
    processor.process_recordings(limit=15)


if __name__ == "__main__":
    main()
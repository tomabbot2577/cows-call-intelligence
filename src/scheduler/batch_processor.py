"""
Batch processing for historical data
"""

import logging
import time
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid

from src.database.session import SessionManager
from src.database.models import CallRecording
from src.scheduler.state_manager import StateManager, BatchState
from src.ringcentral.client import RingCentralClient
from src.transcription.pipeline import TranscriptionPipeline
from src.storage.google_drive import GoogleDriveManager
from src.monitoring.metrics import MetricsCollector

logger = logging.getLogger(__name__)


class BatchProcessor:
    """
    Processes recordings in batches with resume capability
    """

    def __init__(
        self,
        session_manager: SessionManager,
        state_manager: StateManager,
        ringcentral_client: RingCentralClient,
        transcription_pipeline: TranscriptionPipeline,
        drive_manager: GoogleDriveManager,
        metrics_collector: MetricsCollector,
        max_workers: int = 4,
        batch_size: int = 50
    ):
        """
        Initialize batch processor

        Args:
            session_manager: Database session manager
            state_manager: State manager
            ringcentral_client: RingCentral client
            transcription_pipeline: Transcription pipeline
            drive_manager: Google Drive manager
            metrics_collector: Metrics collector
            max_workers: Maximum concurrent workers
            batch_size: Size of processing batches
        """
        self.session_manager = session_manager
        self.state_manager = state_manager
        self.ringcentral_client = ringcentral_client
        self.transcription_pipeline = transcription_pipeline
        self.drive_manager = drive_manager
        self.metrics = metrics_collector
        self.max_workers = max_workers
        self.batch_size = batch_size

        # Processing control
        self.is_running = False
        self.progress_callback = None

        logger.info(f"BatchProcessor initialized with {max_workers} workers")

    def process_date_range(
        self,
        start_date: datetime.date,
        end_date: datetime.date,
        resume_batch_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Process recordings for a date range

        Args:
            start_date: Start date
            end_date: End date
            resume_batch_id: Batch ID to resume from
            progress_callback: Progress callback function

        Returns:
            Processing results
        """
        self.progress_callback = progress_callback
        self.is_running = True

        # Create or load batch
        if resume_batch_id:
            batch = self.state_manager.load_batch(resume_batch_id)
            if not batch:
                logger.error(f"Batch {resume_batch_id} not found")
                return {'error': 'Batch not found'}

            logger.info(f"Resuming batch {resume_batch_id} from {batch.current_date}")
        else:
            batch_id = str(uuid.uuid4())
            batch = self.state_manager.create_batch(batch_id, start_date, end_date)
            logger.info(f"Created new batch {batch_id}")

        results = {
            'batch_id': batch.batch_id,
            'start_date': batch.start_date,
            'end_date': batch.end_date,
            'total_processed': 0,
            'total_succeeded': 0,
            'total_failed': 0,
            'errors': []
        }

        try:
            current_date = datetime.fromisoformat(batch.current_date).date()
            end_dt = datetime.fromisoformat(batch.end_date).date()

            while current_date <= end_dt and self.is_running:
                logger.info(f"Processing date {current_date}")

                try:
                    # Process recordings for this date
                    date_results = self._process_date(current_date)

                    # Update batch state
                    batch.total_processed += date_results['processed']
                    batch.total_failed += date_results['failed']
                    batch.current_date = (current_date + timedelta(days=1)).isoformat()

                    # Update results
                    results['total_processed'] += date_results['processed']
                    results['total_succeeded'] += date_results['succeeded']
                    results['total_failed'] += date_results['failed']

                    # Save state
                    self.state_manager.update_batch(batch)

                    # Report progress
                    if self.progress_callback:
                        progress = {
                            'current_date': current_date.isoformat(),
                            'processed': results['total_processed'],
                            'succeeded': results['total_succeeded'],
                            'failed': results['total_failed']
                        }
                        self.progress_callback(progress)

                except Exception as e:
                    logger.error(f"Error processing {current_date}: {e}")
                    batch.error_count += 1
                    batch.last_error = str(e)
                    results['errors'].append(f"{current_date}: {str(e)}")

                    if batch.error_count > 5:
                        logger.error("Too many errors, stopping batch")
                        break

                current_date += timedelta(days=1)

            # Complete batch if finished
            if current_date > end_dt:
                batch.completed = True
                self.state_manager.complete_batch(batch)
                logger.info(f"Batch {batch.batch_id} completed")

        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            results['errors'].append(str(e))

        finally:
            self.is_running = False

        return results

    def _process_date(self, date: datetime.date) -> Dict[str, int]:
        """
        Process all recordings for a specific date

        Args:
            date: Date to process

        Returns:
            Processing statistics
        """
        stats = {
            'processed': 0,
            'succeeded': 0,
            'failed': 0
        }

        # Fetch recordings from RingCentral
        recordings = self.ringcentral_client.fetch_recordings(
            date_from=date,
            date_to=date
        )

        if not recordings:
            logger.info(f"No recordings found for {date}")
            return stats

        logger.info(f"Found {len(recordings)} recordings for {date}")

        # Process in batches with thread pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for i in range(0, len(recordings), self.batch_size):
                batch = recordings[i:i + self.batch_size]

                # Submit batch for processing
                futures = {
                    executor.submit(self._process_recording, rec): rec
                    for rec in batch
                }

                # Wait for batch completion
                for future in as_completed(futures):
                    recording = futures[future]
                    stats['processed'] += 1

                    try:
                        result = future.result(timeout=300)  # 5 minute timeout
                        if result:
                            stats['succeeded'] += 1
                        else:
                            stats['failed'] += 1

                    except Exception as e:
                        logger.error(f"Processing failed for {recording['id']}: {e}")
                        stats['failed'] += 1

                # Brief pause between batches
                time.sleep(1)

        return stats

    def _process_recording(self, recording_data: Dict[str, Any]) -> bool:
        """
        Process a single recording

        Args:
            recording_data: Recording metadata

        Returns:
            True if successful
        """
        recording_id = recording_data['id']

        try:
            with self.metrics.time_operation('batch_recording_processing'):
                # Check if already processed
                with self.session_manager.get_session() as session:
                    existing = session.query(CallRecording).filter_by(
                        recording_id=recording_id
                    ).first()

                    if existing and existing.upload_status == 'completed':
                        logger.debug(f"Recording {recording_id} already processed")
                        return True

                # Download
                logger.debug(f"Downloading {recording_id}")
                audio_path = self.ringcentral_client.download_recording(
                    recording_id=recording_id,
                    recording_data=recording_data
                )

                if not audio_path:
                    self.state_manager.save_recording_checkpoint(
                        recording_id, 'download', False, "Download failed"
                    )
                    return False

                self.state_manager.save_recording_checkpoint(
                    recording_id, 'download', True
                )

                # Transcribe
                logger.debug(f"Transcribing {recording_id}")
                transcript = self.transcription_pipeline.transcribe_recording(
                    recording_id=recording_id
                )

                if not transcript:
                    self.state_manager.save_recording_checkpoint(
                        recording_id, 'transcription', False, "Transcription failed"
                    )
                    return False

                self.state_manager.save_recording_checkpoint(
                    recording_id, 'transcription', True
                )

                # Upload
                logger.debug(f"Uploading {recording_id}")
                with self.session_manager.get_session() as session:
                    recording = session.query(CallRecording).filter_by(
                        recording_id=recording_id
                    ).first()

                    if recording:
                        upload_result = self.drive_manager.upload_transcript(
                            recording=recording
                        )

                        if not upload_result:
                            self.state_manager.save_recording_checkpoint(
                                recording_id, 'upload', False, "Upload failed"
                            )
                            return False

                        self.state_manager.save_recording_checkpoint(
                            recording_id, 'upload', True
                        )

                logger.info(f"Successfully processed {recording_id}")
                self.metrics.record_counter('batch_recordings_succeeded', 1)
                return True

        except Exception as e:
            logger.error(f"Error processing {recording_id}: {e}")
            self.metrics.record_counter('batch_recordings_failed', 1)
            return False

    def process_failed_recordings(
        self,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Reprocess failed recordings

        Args:
            max_retries: Maximum retry attempts

        Returns:
            Processing results
        """
        logger.info("Starting failed recording reprocessing")

        results = {
            'total_processed': 0,
            'total_succeeded': 0,
            'total_failed': 0
        }

        # Reset eligible failed recordings
        reset_count = self.state_manager.reset_failed_recordings(
            max_age_hours=24,
            max_retries=max_retries
        )

        if reset_count == 0:
            logger.info("No failed recordings to reprocess")
            return results

        logger.info(f"Reset {reset_count} failed recordings for retry")

        # Process each stage separately
        stages = ['download', 'transcription', 'upload']

        for stage in stages:
            pending = self.state_manager.get_pending_recordings(stage, limit=100)

            if not pending:
                continue

            logger.info(f"Processing {len(pending)} recordings pending {stage}")

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []

                for recording_info in pending:
                    if stage == 'download':
                        future = executor.submit(
                            self._retry_download,
                            recording_info['recording_id']
                        )
                    elif stage == 'transcription':
                        future = executor.submit(
                            self._retry_transcription,
                            recording_info['recording_id']
                        )
                    else:  # upload
                        future = executor.submit(
                            self._retry_upload,
                            recording_info['recording_id']
                        )

                    futures.append(future)

                for future in as_completed(futures):
                    results['total_processed'] += 1

                    try:
                        success = future.result(timeout=300)
                        if success:
                            results['total_succeeded'] += 1
                        else:
                            results['total_failed'] += 1

                    except Exception as e:
                        logger.error(f"Retry processing failed: {e}")
                        results['total_failed'] += 1

        return results

    def _retry_download(self, recording_id: str) -> bool:
        """Retry download for a recording"""
        try:
            # Get recording data
            with self.session_manager.get_session() as session:
                recording = session.query(CallRecording).filter_by(
                    recording_id=recording_id
                ).first()

                if not recording:
                    return False

                # Download recording
                audio_path = self.ringcentral_client.download_recording(
                    recording_id=recording_id,
                    recording_data={'id': recording_id}
                )

                if audio_path:
                    self.state_manager.save_recording_checkpoint(
                        recording_id, 'download', True
                    )
                    return True

        except Exception as e:
            logger.error(f"Retry download failed for {recording_id}: {e}")

        self.state_manager.save_recording_checkpoint(
            recording_id, 'download', False, str(e)
        )
        return False

    def _retry_transcription(self, recording_id: str) -> bool:
        """Retry transcription for a recording"""
        try:
            transcript = self.transcription_pipeline.transcribe_recording(
                recording_id=recording_id
            )

            if transcript:
                self.state_manager.save_recording_checkpoint(
                    recording_id, 'transcription', True
                )
                return True

        except Exception as e:
            logger.error(f"Retry transcription failed for {recording_id}: {e}")

        self.state_manager.save_recording_checkpoint(
            recording_id, 'transcription', False, str(e)
        )
        return False

    def _retry_upload(self, recording_id: str) -> bool:
        """Retry upload for a recording"""
        try:
            with self.session_manager.get_session() as session:
                recording = session.query(CallRecording).filter_by(
                    recording_id=recording_id
                ).first()

                if recording:
                    upload_result = self.drive_manager.upload_transcript(
                        recording=recording
                    )

                    if upload_result:
                        self.state_manager.save_recording_checkpoint(
                            recording_id, 'upload', True
                        )
                        return True

        except Exception as e:
            logger.error(f"Retry upload failed for {recording_id}: {e}")

        self.state_manager.save_recording_checkpoint(
            recording_id, 'upload', False, str(e)
        )
        return False

    def stop(self):
        """Stop batch processing"""
        self.is_running = False
        logger.info("Batch processor stopping")
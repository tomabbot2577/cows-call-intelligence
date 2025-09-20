"""
Automated scheduling system for processing call recordings
"""

import os
import logging
import time
import threading
import schedule
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict
import json

from src.database.session import SessionManager
from src.database.models import ProcessingState, CallRecording
from src.ringcentral.client import RingCentralClient
from src.ringcentral.auth import RingCentralAuth
from src.transcription.pipeline import TranscriptionPipeline
from src.storage.google_drive import GoogleDriveManager
from src.storage.secure_storage_handler import SecureStorageHandler
from src.monitoring.metrics import MetricsCollector
from src.monitoring.health_check import HealthChecker
from src.monitoring.alerts import AlertManager, Alert, AlertPriority, AlertChannel

logger = logging.getLogger(__name__)


@dataclass
class ProcessingStats:
    """Statistics for processing run"""
    start_time: datetime
    end_time: Optional[datetime] = None
    total_recordings: int = 0
    successful_downloads: int = 0
    failed_downloads: int = 0
    successful_transcriptions: int = 0
    failed_transcriptions: int = 0
    successful_uploads: int = 0
    failed_uploads: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class ProcessingScheduler:
    """
    Manages automated scheduling of recording processing
    """

    def __init__(
        self,
        session_manager: SessionManager,
        ringcentral_auth: RingCentralAuth,
        transcription_pipeline: TranscriptionPipeline,
        drive_manager: GoogleDriveManager,
        metrics_collector: MetricsCollector,
        health_checker: HealthChecker,
        alert_manager: AlertManager,
        config: Dict[str, Any]
    ):
        """
        Initialize processing scheduler

        Args:
            session_manager: Database session manager
            ringcentral_auth: RingCentral auth handler
            transcription_pipeline: Transcription pipeline
            drive_manager: Google Drive manager
            metrics_collector: Metrics collector
            health_checker: Health checker
            alert_manager: Alert manager
            config: Configuration dictionary
        """
        self.session_manager = session_manager
        self.ringcentral_auth = ringcentral_auth
        self.transcription_pipeline = transcription_pipeline
        self.drive_manager = drive_manager
        # Initialize secure storage handler that deletes audio after transcription
        self.secure_storage = SecureStorageHandler(
            google_drive_manager=drive_manager,
            local_backup_dir=config.get('transcript_backup_dir'),
            enable_audit_log=True,
            verify_deletion=True
        )
        self.metrics = metrics_collector
        self.health_checker = health_checker
        self.alert_manager = alert_manager
        self.config = config

        # Processing configuration
        self.daily_schedule_time = config.get('daily_schedule_time', '02:00')
        self.batch_size = config.get('batch_size', 50)
        self.max_retries = config.get('max_retries', 3)
        self.historical_days = config.get('historical_days', 60)

        # State management
        self.is_running = False
        self.stop_event = threading.Event()
        self.processing_thread = None
        self.current_stats = None

        # Initialize RingCentral client
        self.ringcentral_client = None

        logger.info(f"ProcessingScheduler initialized with daily run at {self.daily_schedule_time}")

    def initialize_clients(self):
        """Initialize API clients"""
        try:
            # Verify RingCentral authentication by getting a token
            self.ringcentral_auth.get_access_token()

            # Create RingCentral client
            self.ringcentral_client = RingCentralClient(
                auth=self.ringcentral_auth
            )

            logger.info("API clients initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize clients: {e}")
            self.alert_manager.send_alert(Alert(
                title="Scheduler Initialization Failed",
                message=f"Failed to initialize API clients: {e}",
                priority=AlertPriority.HIGH,
                component="scheduler",
                channels=[AlertChannel.LOG, AlertChannel.EMAIL]
            ))
            raise

    def start(self):
        """Start the scheduler"""
        if self.is_running:
            logger.warning("Scheduler is already running")
            return

        logger.info("Starting processing scheduler")

        # Initialize clients
        self.initialize_clients()

        # Schedule daily processing
        schedule.every().day.at(self.daily_schedule_time).do(self.run_daily_processing)

        # Schedule hourly health checks
        schedule.every().hour.do(self.run_health_check)

        # Schedule metrics collection every 5 minutes
        schedule.every(5).minutes.do(self.collect_metrics)

        # Start scheduler thread
        self.is_running = True
        self.processing_thread = threading.Thread(target=self._scheduler_loop)
        self.processing_thread.daemon = True
        self.processing_thread.start()

        logger.info("Scheduler started successfully")

    def stop(self):
        """Stop the scheduler"""
        if not self.is_running:
            logger.warning("Scheduler is not running")
            return

        logger.info("Stopping processing scheduler")

        self.is_running = False
        self.stop_event.set()

        if self.processing_thread:
            self.processing_thread.join(timeout=10)

        logger.info("Scheduler stopped")

    def _scheduler_loop(self):
        """Main scheduler loop"""
        while self.is_running and not self.stop_event.is_set():
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                self.metrics.record_counter('scheduler_errors', 1)

    def run_daily_processing(self):
        """Run daily processing of recordings"""
        logger.info("Starting daily processing run")

        stats = ProcessingStats(start_time=datetime.utcnow())
        self.current_stats = stats

        try:
            # Check system health first
            health_report = self.health_checker.check_health()
            if health_report['status'] in ['critical', 'unhealthy']:
                logger.error("System unhealthy, skipping processing")
                self.alert_manager.send_health_alert(health_report)
                return

            # Get or create processing state
            state_data = self._get_or_create_state()

            # Determine date range
            last_run = state_data.get('last_successful_run')
            if last_run:
                # Process from last successful run
                start_date = datetime.fromisoformat(last_run).date()
            else:
                # Initial run - process historical data
                start_date = (datetime.utcnow() - timedelta(days=self.historical_days)).date()

            end_date = datetime.utcnow().date()

            logger.info(f"Processing recordings from {start_date} to {end_date}")

            # Fetch and process recordings
            current_date = start_date
            while current_date <= end_date and self.is_running:
                try:
                    self._process_day_recordings(current_date, stats)

                    # Update state checkpoint
                    state_data['last_checkpoint'] = datetime.utcnow().isoformat()
                    state_data['checkpoint_data'] = {
                        'current_date': current_date.isoformat(),
                        'stats': asdict(stats)
                    }
                    self._save_state_data(state_data)

                    current_date += timedelta(days=1)

                except Exception as e:
                    logger.error(f"Error processing {current_date}: {e}")
                    stats.errors.append(f"Date {current_date}: {str(e)}")

                    if len(stats.errors) > 5:
                        logger.error("Too many errors, stopping processing")
                        break

            # Update final state
            stats.end_time = datetime.utcnow()
            state_data['last_successful_run'] = datetime.utcnow().isoformat()
            state_data['total_processed'] = state_data.get('total_processed', 0) + stats.total_recordings
            state_data['total_succeeded'] = state_data.get('total_succeeded', 0) + stats.successful_uploads
            state_data['total_failed'] = state_data.get('total_failed', 0) + (stats.failed_downloads + stats.failed_transcriptions + stats.failed_uploads)
            self._save_state_data(state_data)

            # Send completion alert
            self._send_completion_alert(stats)

            # Record metrics
            self._record_processing_metrics(stats)

        except Exception as e:
            logger.error(f"Daily processing failed: {e}")
            stats.errors.append(str(e))
            self.alert_manager.send_error_alert(
                error=e,
                component="scheduler",
                operation="daily_processing"
            )

        finally:
            self.current_stats = None

    def _process_day_recordings(self, date: datetime.date, stats: ProcessingStats):
        """
        Process recordings for a specific day

        Args:
            date: Date to process
            stats: Processing statistics
        """
        logger.info(f"Processing recordings for {date}")

        with self.session_manager.get_session() as session:
            # Check for existing recordings for this date
            existing = session.query(CallRecording).filter(
                CallRecording.call_start_time >= datetime.combine(date, datetime.min.time()),
                CallRecording.call_start_time < datetime.combine(date + timedelta(days=1), datetime.min.time())
            ).all()

            existing_ids = {r.recording_id for r in existing}

        # Fetch recordings from RingCentral
        recordings = self.ringcentral_client.fetch_recordings(
            date_from=date,
            date_to=date
        )

        new_recordings = [r for r in recordings if r['id'] not in existing_ids]

        if not new_recordings:
            logger.info(f"No new recordings for {date}")
            return

        logger.info(f"Found {len(new_recordings)} new recordings for {date}")
        stats.total_recordings += len(new_recordings)

        # Process in batches
        for i in range(0, len(new_recordings), self.batch_size):
            batch = new_recordings[i:i + self.batch_size]

            for recording in batch:
                if not self.is_running:
                    logger.info("Processing stopped by user")
                    return

                try:
                    self._process_single_recording(recording, stats)

                except Exception as e:
                    logger.error(f"Failed to process recording {recording['id']}: {e}")
                    stats.errors.append(f"Recording {recording['id']}: {str(e)}")

            # Brief pause between batches
            time.sleep(2)

    def _process_single_recording(self, recording_data: Dict[str, Any], stats: ProcessingStats):
        """
        Process a single recording through the full pipeline

        Args:
            recording_data: Recording metadata from RingCentral
            stats: Processing statistics
        """
        recording_id = recording_data['id']

        with self.metrics.time_operation('recording_processing'):
            try:
                # Download recording
                logger.debug(f"Downloading recording {recording_id}")
                audio_path = self.ringcentral_client.download_recording(
                    recording_id=recording_id,
                    recording_data=recording_data
                )

                if audio_path:
                    stats.successful_downloads += 1
                else:
                    stats.failed_downloads += 1
                    return

                # Transcribe recording
                logger.debug(f"Transcribing recording {recording_id}")
                transcript = self.transcription_pipeline.transcribe_recording(
                    recording_id=recording_id
                )

                if transcript:
                    stats.successful_transcriptions += 1
                else:
                    stats.failed_transcriptions += 1
                    return

                # SECURE STORAGE: Save transcript and DELETE audio file
                logger.info(f"Processing transcript and deleting audio for {recording_id}")

                # Get recording metadata
                with self.session_manager.get_session() as session:
                    recording = session.query(CallRecording).filter_by(
                        recording_id=recording_id
                    ).first()

                    if recording and audio_path and transcript:
                        # Prepare call metadata
                        call_metadata = {
                            'recording_id': recording_id,
                            'call_start_time': str(recording.call_start_time),
                            'duration': recording.duration,
                            'from_number': recording.from_number,
                            'to_number': recording.to_number,
                            'direction': recording.direction
                        }

                        # Process with secure storage (saves transcript and DELETES audio)
                        storage_result = self.secure_storage.process_transcription(
                            audio_file_path=audio_path,
                            transcription_result=transcript,
                            call_metadata=call_metadata
                        )

                        if storage_result['success']:
                            stats.successful_uploads += 1

                            # Update database to reflect audio deletion
                            recording.audio_deleted = True
                            recording.audio_deletion_time = datetime.utcnow()
                            recording.drive_file_id = storage_result.get('drive_file_id')
                            session.commit()

                            # Log confirmation
                            if storage_result['audio_deleted']:
                                logger.info(f"✅ CONFIRMED: Audio file DELETED for recording {recording_id}")
                                logger.info(f"   Deletion verified: {storage_result['deletion_verified']}")
                            else:
                                logger.error(f"⚠️ WARNING: Audio deletion failed for {recording_id}")
                        else:
                            stats.failed_uploads += 1
                            logger.error(f"Failed to process recording {recording_id}: {storage_result.get('error')}")

            except Exception as e:
                logger.error(f"Error processing recording {recording_id}: {e}")
                raise

    def _get_or_create_state(self) -> dict:
        """Get or create processing state and return its data"""
        with self.session_manager.get_session() as session:
            state = session.query(ProcessingState).filter_by(
                state_key='main_processor'
            ).first()

            if not state:
                state = ProcessingState(
                    state_key='main_processor',
                    state_value={},
                    is_active=True
                )
                session.add(state)
                session.commit()
                return {}

            return state.state_value or {}

    def _save_state_data(self, state_data: dict):
        """Save processing state data to database"""
        with self.session_manager.get_session() as session:
            state = session.query(ProcessingState).filter_by(
                state_key='main_processor'
            ).first()
            if state:
                state.state_value = state_data
                session.commit()
            else:
                state = ProcessingState(
                    state_key='main_processor',
                    state_value=state_data,
                    is_active=True
                )
                session.add(state)
                session.commit()

    def run_health_check(self):
        """Run system health check"""
        try:
            report = self.health_checker.check_health()

            # Record health metrics
            self.metrics.record_gauge(
                'system_health_status',
                1 if report['status'] == 'healthy' else 0,
                "System health status"
            )

            # Send alert if unhealthy
            if report['status'] in ['unhealthy', 'critical']:
                self.alert_manager.send_health_alert(report)

        except Exception as e:
            logger.error(f"Health check failed: {e}")

    def collect_metrics(self):
        """Collect and record system metrics"""
        try:
            self.metrics.record_system_metrics()

            # Record scheduler-specific metrics
            with self.session_manager.get_session() as session:
                # Queue sizes
                pending_downloads = session.query(CallRecording).filter_by(
                    download_status='pending'
                ).count()

                pending_transcriptions = session.query(CallRecording).filter_by(
                    download_status='completed',
                    transcription_status='pending'
                ).count()

                pending_uploads = session.query(CallRecording).filter_by(
                    transcription_status='completed',
                    upload_status='pending'
                ).count()

                self.metrics.record_gauge('queue_size_downloads', pending_downloads)
                self.metrics.record_gauge('queue_size_transcriptions', pending_transcriptions)
                self.metrics.record_gauge('queue_size_uploads', pending_uploads)

        except Exception as e:
            logger.error(f"Metrics collection failed: {e}")

    def _send_completion_alert(self, stats: ProcessingStats):
        """Send processing completion alert"""
        duration = (stats.end_time - stats.start_time).total_seconds() if stats.end_time else 0

        message = f"""
Daily processing completed:
- Duration: {duration:.1f} seconds
- Total recordings: {stats.total_recordings}
- Downloads: {stats.successful_downloads} succeeded, {stats.failed_downloads} failed
- Transcriptions: {stats.successful_transcriptions} succeeded, {stats.failed_transcriptions} failed
- Uploads: {stats.successful_uploads} succeeded, {stats.failed_uploads} failed
"""

        if stats.errors:
            message += f"\n- Errors: {len(stats.errors)}"

        priority = AlertPriority.LOW
        if stats.failed_downloads > 0 or stats.failed_transcriptions > 0 or stats.failed_uploads > 0:
            priority = AlertPriority.MEDIUM
        if len(stats.errors) > 5:
            priority = AlertPriority.HIGH

        self.alert_manager.send_alert(Alert(
            title="Daily Processing Complete",
            message=message,
            priority=priority,
            component="scheduler",
            details=asdict(stats),
            channels=[AlertChannel.LOG, AlertChannel.EMAIL]
        ))

    def _record_processing_metrics(self, stats: ProcessingStats):
        """Record processing metrics"""
        self.metrics.record_counter('daily_runs_completed', 1)
        self.metrics.record_counter('recordings_processed_total', stats.total_recordings)
        self.metrics.record_counter('downloads_succeeded', stats.successful_downloads)
        self.metrics.record_counter('downloads_failed', stats.failed_downloads)
        self.metrics.record_counter('transcriptions_succeeded', stats.successful_transcriptions)
        self.metrics.record_counter('transcriptions_failed', stats.failed_transcriptions)
        self.metrics.record_counter('uploads_succeeded', stats.successful_uploads)
        self.metrics.record_counter('uploads_failed', stats.failed_uploads)

        if stats.end_time:
            duration = (stats.end_time - stats.start_time).total_seconds()
            self.metrics.record_histogram('daily_processing_duration', duration)

    def process_historical(self, start_date: datetime.date, end_date: datetime.date):
        """
        Process historical recordings for a date range

        Args:
            start_date: Start date
            end_date: End date
        """
        logger.info(f"Processing historical recordings from {start_date} to {end_date}")

        stats = ProcessingStats(start_time=datetime.utcnow())

        try:
            current_date = start_date
            while current_date <= end_date and self.is_running:
                self._process_day_recordings(current_date, stats)
                current_date += timedelta(days=1)

                # Save progress
                state = self._get_or_create_state()
                state.last_checkpoint = datetime.utcnow()
                state.checkpoint_data = {
                    'historical_processing': True,
                    'current_date': current_date.isoformat(),
                    'stats': asdict(stats)
                }
                self._save_state(state)

            stats.end_time = datetime.utcnow()
            self._send_completion_alert(stats)

        except Exception as e:
            logger.error(f"Historical processing failed: {e}")
            self.alert_manager.send_error_alert(
                error=e,
                component="scheduler",
                operation="historical_processing"
            )

    def get_status(self) -> Dict[str, Any]:
        """
        Get scheduler status

        Returns:
            Status dictionary
        """
        state_data = self._get_or_create_state()

        return {
            'is_running': self.is_running,
            'daily_schedule_time': self.daily_schedule_time,
            'last_successful_run': state_data.get('last_successful_run'),
            'total_processed': state_data.get('total_processed', 0),
            'total_succeeded': state_data.get('total_succeeded', 0),
            'total_failed': state_data.get('total_failed', 0),
            'current_stats': asdict(self.current_stats) if self.current_stats else None,
            'next_run': schedule.next_run().isoformat() if schedule.next_run() else None
        }
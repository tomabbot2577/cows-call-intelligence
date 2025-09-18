"""
State management for resumable processing
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, asdict

from src.database.session import SessionManager
from src.database.models import ProcessingState, CallRecording

logger = logging.getLogger(__name__)


@dataclass
class BatchState:
    """State for batch processing"""
    batch_id: str
    start_date: str
    end_date: str
    current_date: str
    total_processed: int = 0
    total_failed: int = 0
    completed: bool = False
    error_count: int = 0
    last_error: Optional[str] = None


class StateManager:
    """
    Manages processing state for resume capability
    """

    def __init__(self, session_manager: SessionManager):
        """
        Initialize state manager

        Args:
            session_manager: Database session manager
        """
        self.session_manager = session_manager
        self.current_batch = None

        logger.info("StateManager initialized")

    def create_batch(
        self,
        batch_id: str,
        start_date: datetime.date,
        end_date: datetime.date
    ) -> BatchState:
        """
        Create a new batch for processing

        Args:
            batch_id: Unique batch identifier
            start_date: Start date for batch
            end_date: End date for batch

        Returns:
            BatchState object
        """
        batch = BatchState(
            batch_id=batch_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            current_date=start_date.isoformat()
        )

        # Save to database
        with self.session_manager.get_session() as session:
            state = ProcessingState(
                state_key=f'batch_{batch_id}',
                is_active=True,
                checkpoint_data=asdict(batch)
            )
            session.add(state)
            session.commit()

        self.current_batch = batch
        logger.info(f"Created batch {batch_id} for {start_date} to {end_date}")

        return batch

    def load_batch(self, batch_id: str) -> Optional[BatchState]:
        """
        Load an existing batch state

        Args:
            batch_id: Batch identifier

        Returns:
            BatchState object if found, None otherwise
        """
        with self.session_manager.get_session() as session:
            state = session.query(ProcessingState).filter_by(
                state_key=f'batch_{batch_id}'
            ).first()

            if state and state.checkpoint_data:
                batch = BatchState(**state.checkpoint_data)
                self.current_batch = batch
                logger.info(f"Loaded batch {batch_id}")
                return batch

        logger.warning(f"Batch {batch_id} not found")
        return None

    def update_batch(self, batch: BatchState):
        """
        Update batch state in database

        Args:
            batch: BatchState to update
        """
        with self.session_manager.get_session() as session:
            state = session.query(ProcessingState).filter_by(
                state_key=f'batch_{batch.batch_id}'
            ).first()

            if state:
                state.checkpoint_data = asdict(batch)
                state.last_checkpoint = datetime.utcnow()
                session.commit()

                logger.debug(f"Updated batch {batch.batch_id}")

    def complete_batch(self, batch: BatchState):
        """
        Mark batch as completed

        Args:
            batch: BatchState to complete
        """
        batch.completed = True

        with self.session_manager.get_session() as session:
            state = session.query(ProcessingState).filter_by(
                state_key=f'batch_{batch.batch_id}'
            ).first()

            if state:
                state.is_active = False
                state.checkpoint_data = asdict(batch)
                state.last_checkpoint = datetime.utcnow()
                session.commit()

                logger.info(f"Completed batch {batch.batch_id}")

    def get_active_batches(self) -> List[BatchState]:
        """
        Get all active batches

        Returns:
            List of active BatchState objects
        """
        batches = []

        with self.session_manager.get_session() as session:
            states = session.query(ProcessingState).filter(
                ProcessingState.state_key.like('batch_%'),
                ProcessingState.is_active == True
            ).all()

            for state in states:
                if state.checkpoint_data:
                    batches.append(BatchState(**state.checkpoint_data))

        return batches

    def save_recording_checkpoint(
        self,
        recording_id: str,
        stage: str,
        success: bool,
        error: Optional[str] = None
    ):
        """
        Save checkpoint for individual recording

        Args:
            recording_id: Recording ID
            stage: Processing stage (download, transcription, upload)
            success: Whether stage succeeded
            error: Error message if failed
        """
        with self.session_manager.get_session() as session:
            recording = session.query(CallRecording).filter_by(
                recording_id=recording_id
            ).first()

            if recording:
                # Update status based on stage
                if stage == 'download':
                    recording.download_status = 'completed' if success else 'failed'
                    if error:
                        recording.download_error = error
                elif stage == 'transcription':
                    recording.transcription_status = 'completed' if success else 'failed'
                    if error:
                        recording.transcription_error = error
                elif stage == 'upload':
                    recording.upload_status = 'completed' if success else 'failed'
                    if error:
                        recording.upload_error = error

                recording.last_updated = datetime.utcnow()
                session.commit()

                logger.debug(f"Saved checkpoint for {recording_id} stage {stage}")

    def get_pending_recordings(
        self,
        stage: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get recordings pending for a specific stage

        Args:
            stage: Processing stage
            limit: Maximum number to return

        Returns:
            List of recording dictionaries
        """
        with self.session_manager.get_session() as session:
            query = session.query(CallRecording)

            if stage == 'download':
                query = query.filter_by(download_status='pending')
            elif stage == 'transcription':
                query = query.filter_by(
                    download_status='completed',
                    transcription_status='pending'
                )
            elif stage == 'upload':
                query = query.filter_by(
                    transcription_status='completed',
                    upload_status='pending'
                )

            recordings = query.limit(limit).all()

            return [
                {
                    'recording_id': r.recording_id,
                    'call_id': r.call_id,
                    'retry_count': r.retry_count,
                    'last_updated': r.last_updated.isoformat() if r.last_updated else None
                }
                for r in recordings
            ]

    def reset_failed_recordings(
        self,
        max_age_hours: int = 24,
        max_retries: int = 3
    ) -> int:
        """
        Reset failed recordings for retry

        Args:
            max_age_hours: Maximum age of failure in hours
            max_retries: Maximum retry count

        Returns:
            Number of recordings reset
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        reset_count = 0

        with self.session_manager.get_session() as session:
            # Find failed recordings eligible for retry
            failed_recordings = session.query(CallRecording).filter(
                CallRecording.retry_count < max_retries,
                CallRecording.last_updated < cutoff_time
            ).filter(
                (CallRecording.download_status == 'failed') |
                (CallRecording.transcription_status == 'failed') |
                (CallRecording.upload_status == 'failed')
            ).all()

            for recording in failed_recordings:
                # Reset appropriate status
                if recording.download_status == 'failed':
                    recording.download_status = 'pending'
                    recording.download_error = None
                elif recording.transcription_status == 'failed':
                    recording.transcription_status = 'pending'
                    recording.transcription_error = None
                elif recording.upload_status == 'failed':
                    recording.upload_status = 'pending'
                    recording.upload_error = None

                recording.retry_count += 1
                recording.last_updated = datetime.utcnow()
                reset_count += 1

            session.commit()

        logger.info(f"Reset {reset_count} failed recordings for retry")
        return reset_count

    def get_processing_summary(self) -> Dict[str, Any]:
        """
        Get summary of processing state

        Returns:
            Summary dictionary
        """
        with self.session_manager.get_session() as session:
            total = session.query(CallRecording).count()

            pending_download = session.query(CallRecording).filter_by(
                download_status='pending'
            ).count()

            pending_transcription = session.query(CallRecording).filter_by(
                download_status='completed',
                transcription_status='pending'
            ).count()

            pending_upload = session.query(CallRecording).filter_by(
                transcription_status='completed',
                upload_status='pending'
            ).count()

            completed = session.query(CallRecording).filter_by(
                upload_status='completed'
            ).count()

            failed_download = session.query(CallRecording).filter_by(
                download_status='failed'
            ).count()

            failed_transcription = session.query(CallRecording).filter_by(
                transcription_status='failed'
            ).count()

            failed_upload = session.query(CallRecording).filter_by(
                upload_status='failed'
            ).count()

        return {
            'total_recordings': total,
            'completed': completed,
            'pending': {
                'download': pending_download,
                'transcription': pending_transcription,
                'upload': pending_upload
            },
            'failed': {
                'download': failed_download,
                'transcription': failed_transcription,
                'upload': failed_upload
            },
            'active_batches': len(self.get_active_batches())
        }

    def cleanup_old_states(self, days: int = 30):
        """
        Clean up old processing states

        Args:
            days: Age threshold in days
        """
        cutoff = datetime.utcnow() - timedelta(days=days)

        with self.session_manager.get_session() as session:
            old_states = session.query(ProcessingState).filter(
                ProcessingState.is_active == False,
                ProcessingState.last_checkpoint < cutoff
            ).all()

            for state in old_states:
                session.delete(state)

            session.commit()

            logger.info(f"Cleaned up {len(old_states)} old processing states")
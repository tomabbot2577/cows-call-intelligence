"""
Database manager for high-level operations
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from .models import (
    CallRecording, ProcessingHistory, SystemMetric,
    ProcessingState, FailedDownload, ProcessingStatus
)
from .connection import get_db_session

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    High-level database operations manager
    """

    @staticmethod
    def get_pending_recordings(
        session: Session,
        limit: int = 100,
        retry_threshold: int = 3
    ) -> List[CallRecording]:
        """
        Get recordings that need processing

        Args:
            session: Database session
            limit: Maximum number of recordings to return
            retry_threshold: Maximum attempts before skipping

        Returns:
            List of CallRecording objects
        """
        return session.query(CallRecording).filter(
            and_(
                or_(
                    CallRecording.download_status == ProcessingStatus.PENDING,
                    and_(
                        CallRecording.download_status == ProcessingStatus.FAILED,
                        CallRecording.download_attempts < retry_threshold
                    )
                ),
                CallRecording.recording_id.notin_(
                    session.query(FailedDownload.recording_id)
                )
            )
        ).order_by(
            CallRecording.start_time.desc()
        ).limit(limit).all()

    @staticmethod
    def get_recordings_for_transcription(
        session: Session,
        limit: int = 50
    ) -> List[CallRecording]:
        """
        Get recordings ready for transcription

        Args:
            session: Database session
            limit: Maximum number of recordings to return

        Returns:
            List of CallRecording objects
        """
        return session.query(CallRecording).filter(
            and_(
                CallRecording.download_status == ProcessingStatus.COMPLETED,
                CallRecording.transcription_status == ProcessingStatus.PENDING
            )
        ).order_by(
            CallRecording.created_at
        ).limit(limit).all()

    @staticmethod
    def get_recordings_for_upload(
        session: Session,
        limit: int = 50
    ) -> List[CallRecording]:
        """
        Get recordings ready for upload

        Args:
            session: Database session
            limit: Maximum number of recordings to return

        Returns:
            List of CallRecording objects
        """
        return session.query(CallRecording).filter(
            and_(
                CallRecording.transcription_status == ProcessingStatus.COMPLETED,
                CallRecording.upload_status == ProcessingStatus.PENDING
            )
        ).order_by(
            CallRecording.created_at
        ).limit(limit).all()

    @staticmethod
    def add_processing_history(
        session: Session,
        recording_id: str,
        action: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None
    ):
        """
        Add processing history entry

        Args:
            session: Database session
            recording_id: Recording ID
            action: Action performed
            status: Result status
            details: Additional details
            error_message: Error message if failed
            duration_ms: Duration in milliseconds
        """
        history = ProcessingHistory(
            recording_id=recording_id,
            action=action,
            status=status,
            details=details,
            error_message=error_message,
            duration_ms=duration_ms,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        session.add(history)
        session.commit()

    @staticmethod
    def record_metric(
        session: Session,
        metric_name: str,
        metric_value: float,
        metric_unit: Optional[str] = None,
        component: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None
    ):
        """
        Record a system metric

        Args:
            session: Database session
            metric_name: Name of the metric
            metric_value: Value of the metric
            metric_unit: Unit of measurement
            component: Component generating the metric
            tags: Additional tags
        """
        metric = SystemMetric(
            metric_name=metric_name,
            metric_value=metric_value,
            metric_unit=metric_unit,
            component=component,
            tags=tags
        )
        session.add(metric)
        session.commit()

    @staticmethod
    def get_or_create_state(
        session: Session,
        state_key: str,
        default_value: Optional[Dict[str, Any]] = None
    ) -> ProcessingState:
        """
        Get or create a processing state

        Args:
            session: Database session
            state_key: State key
            default_value: Default value if creating

        Returns:
            ProcessingState object
        """
        state = session.query(ProcessingState).filter_by(
            state_key=state_key
        ).first()

        if not state:
            state = ProcessingState(
                state_key=state_key,
                state_value=default_value or {}
            )
            session.add(state)
            session.commit()

        return state

    @staticmethod
    def update_state(
        session: Session,
        state_key: str,
        state_value: Dict[str, Any]
    ):
        """
        Update a processing state

        Args:
            session: Database session
            state_key: State key
            state_value: New state value
        """
        state = session.query(ProcessingState).filter_by(
            state_key=state_key
        ).first()

        if state:
            state.state_value = state_value
            state.updated_at = datetime.utcnow()
        else:
            state = ProcessingState(
                state_key=state_key,
                state_value=state_value
            )
            session.add(state)

        session.commit()

    @staticmethod
    def mark_recording_failed(
        session: Session,
        recording: CallRecording,
        failure_reason: str,
        permanent: bool = False
    ):
        """
        Mark a recording as failed

        Args:
            session: Database session
            recording: CallRecording object
            failure_reason: Reason for failure
            permanent: Whether this is a permanent failure
        """
        if permanent:
            # Add to failed downloads table
            failed = FailedDownload(
                call_id=recording.call_id,
                recording_id=recording.recording_id,
                failure_reason=failure_reason,
                last_error=failure_reason,
                attempt_count=recording.download_attempts,
                first_attempted_at=datetime.utcnow(),
                last_attempted_at=datetime.utcnow()
            )
            session.add(failed)

            # Update recording status
            recording.download_status = ProcessingStatus.FAILED
            recording.error_message = failure_reason

        else:
            # Increment retry count
            recording.download_attempts += 1
            recording.download_status = ProcessingStatus.FAILED
            recording.download_error = failure_reason

        session.commit()

    @staticmethod
    def get_statistics(session: Session) -> Dict[str, Any]:
        """
        Get processing statistics

        Args:
            session: Database session

        Returns:
            Dictionary of statistics
        """
        total_recordings = session.query(func.count(CallRecording.id)).scalar()

        downloads_completed = session.query(func.count(CallRecording.id)).filter(
            CallRecording.download_status == ProcessingStatus.COMPLETED
        ).scalar()

        transcriptions_completed = session.query(func.count(CallRecording.id)).filter(
            CallRecording.transcription_status == ProcessingStatus.COMPLETED
        ).scalar()

        uploads_completed = session.query(func.count(CallRecording.id)).filter(
            CallRecording.upload_status == ProcessingStatus.COMPLETED
        ).scalar()

        failed_permanently = session.query(func.count(FailedDownload.id)).scalar()

        avg_duration = session.query(func.avg(CallRecording.duration)).scalar()

        return {
            'total_recordings': total_recordings,
            'downloads_completed': downloads_completed,
            'transcriptions_completed': transcriptions_completed,
            'uploads_completed': uploads_completed,
            'failed_permanently': failed_permanently,
            'average_call_duration': float(avg_duration) if avg_duration else 0,
            'success_rate': (downloads_completed / total_recordings * 100) if total_recordings > 0 else 0
        }

    @staticmethod
    def cleanup_old_metrics(
        session: Session,
        days_to_keep: int = 30
    ) -> int:
        """
        Clean up old metrics

        Args:
            session: Database session
            days_to_keep: Number of days to keep

        Returns:
            Number of deleted records
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

        deleted = session.query(SystemMetric).filter(
            SystemMetric.recorded_at < cutoff_date
        ).delete()

        session.commit()
        return deleted
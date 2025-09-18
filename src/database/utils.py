"""
Database utilities and helper functions
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from .models import CallRecording, ProcessingStatus
from .connection import get_db_session

logger = logging.getLogger(__name__)


class DatabaseUtils:
    """
    Database utility functions
    """

    @staticmethod
    def check_database_health() -> Dict[str, Any]:
        """
        Check database health and connectivity

        Returns:
            Dictionary with health status
        """
        try:
            with get_db_session() as session:
                # Test basic query
                result = session.execute(text("SELECT 1")).scalar()

                # Get database size
                db_size = session.execute(
                    text("SELECT pg_database_size(current_database())")
                ).scalar()

                # Get active connections
                active_connections = session.execute(
                    text("""
                        SELECT count(*)
                        FROM pg_stat_activity
                        WHERE state = 'active'
                    """)
                ).scalar()

                # Get table counts
                recordings_count = session.query(CallRecording).count()

                return {
                    'status': 'healthy',
                    'database_size_bytes': db_size,
                    'active_connections': active_connections,
                    'total_recordings': recordings_count,
                    'timestamp': datetime.utcnow().isoformat()
                }

        except SQLAlchemyError as e:
            logger.error(f"Database health check failed: {e}")
            return {
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }

    @staticmethod
    def reset_stuck_recordings(
        session: Session,
        stuck_threshold_hours: int = 6
    ) -> int:
        """
        Reset recordings stuck in IN_PROGRESS status

        Args:
            session: Database session
            stuck_threshold_hours: Hours before considering stuck

        Returns:
            Number of reset recordings
        """
        threshold = datetime.utcnow() - timedelta(hours=stuck_threshold_hours)

        # Find stuck downloads
        stuck_downloads = session.query(CallRecording).filter(
            CallRecording.download_status == ProcessingStatus.IN_PROGRESS,
            CallRecording.updated_at < threshold
        ).all()

        for recording in stuck_downloads:
            recording.download_status = ProcessingStatus.PENDING
            recording.download_attempts += 1
            logger.info(f"Reset stuck download: {recording.recording_id}")

        # Find stuck transcriptions
        stuck_transcriptions = session.query(CallRecording).filter(
            CallRecording.transcription_status == ProcessingStatus.IN_PROGRESS,
            CallRecording.updated_at < threshold
        ).all()

        for recording in stuck_transcriptions:
            recording.transcription_status = ProcessingStatus.PENDING
            recording.transcription_attempts += 1
            logger.info(f"Reset stuck transcription: {recording.recording_id}")

        # Find stuck uploads
        stuck_uploads = session.query(CallRecording).filter(
            CallRecording.upload_status == ProcessingStatus.IN_PROGRESS,
            CallRecording.updated_at < threshold
        ).all()

        for recording in stuck_uploads:
            recording.upload_status = ProcessingStatus.PENDING
            recording.upload_attempts += 1
            logger.info(f"Reset stuck upload: {recording.recording_id}")

        total_reset = len(stuck_downloads) + len(stuck_transcriptions) + len(stuck_uploads)

        session.commit()
        return total_reset

    @staticmethod
    def batch_insert_recordings(
        session: Session,
        recordings_data: List[Dict[str, Any]]
    ) -> int:
        """
        Batch insert call recordings

        Args:
            session: Database session
            recordings_data: List of recording data dictionaries

        Returns:
            Number of inserted recordings
        """
        inserted_count = 0

        for data in recordings_data:
            # Check if recording already exists
            existing = session.query(CallRecording).filter_by(
                recording_id=data.get('recording_id')
            ).first()

            if not existing:
                recording = CallRecording(**data)
                session.add(recording)
                inserted_count += 1
            else:
                logger.debug(f"Recording already exists: {data.get('recording_id')}")

        session.commit()
        return inserted_count

    @staticmethod
    def get_processing_summary(
        session: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get processing summary for a date range

        Args:
            session: Database session
            start_date: Start date (optional)
            end_date: End date (optional)

        Returns:
            Processing summary dictionary
        """
        query = session.query(CallRecording)

        if start_date:
            query = query.filter(CallRecording.start_time >= start_date)
        if end_date:
            query = query.filter(CallRecording.start_time <= end_date)

        recordings = query.all()

        summary = {
            'total': len(recordings),
            'downloads': {
                'pending': 0,
                'in_progress': 0,
                'completed': 0,
                'failed': 0
            },
            'transcriptions': {
                'pending': 0,
                'in_progress': 0,
                'completed': 0,
                'failed': 0
            },
            'uploads': {
                'pending': 0,
                'in_progress': 0,
                'completed': 0,
                'failed': 0
            },
            'total_duration_seconds': 0,
            'average_confidence': 0.0
        }

        total_confidence = 0
        confidence_count = 0

        for recording in recordings:
            # Download status
            if recording.download_status:
                status = recording.download_status.lower()
                if status in summary['downloads']:
                    summary['downloads'][status] += 1

            # Transcription status
            if recording.transcription_status:
                status = recording.transcription_status.lower()
                if status in summary['transcriptions']:
                    summary['transcriptions'][status] += 1

            # Upload status
            if recording.upload_status:
                status = recording.upload_status.lower()
                if status in summary['uploads']:
                    summary['uploads'][status] += 1

            # Duration
            if recording.duration:
                summary['total_duration_seconds'] += recording.duration

            # Confidence
            if recording.transcript_confidence:
                total_confidence += recording.transcript_confidence
                confidence_count += 1

        if confidence_count > 0:
            summary['average_confidence'] = total_confidence / confidence_count

        return summary

    @staticmethod
    def optimize_database(session: Session):
        """
        Run database optimization tasks

        Args:
            session: Database session
        """
        try:
            # Analyze tables for query optimization
            tables = ['call_recordings', 'processing_history', 'system_metrics']

            for table in tables:
                session.execute(text(f"ANALYZE {table}"))
                logger.info(f"Analyzed table: {table}")

            # Reindex if needed (be careful with this in production)
            # session.execute(text("REINDEX DATABASE call_recordings"))

            session.commit()
            logger.info("Database optimization completed")

        except SQLAlchemyError as e:
            logger.error(f"Database optimization failed: {e}")
            session.rollback()

    @staticmethod
    def export_recordings_to_csv(
        session: Session,
        output_path: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ):
        """
        Export recordings to CSV for reporting

        Args:
            session: Database session
            output_path: Path for CSV file
            start_date: Start date filter
            end_date: End date filter
        """
        import csv

        query = session.query(CallRecording)

        if start_date:
            query = query.filter(CallRecording.start_time >= start_date)
        if end_date:
            query = query.filter(CallRecording.start_time <= end_date)

        recordings = query.all()

        with open(output_path, 'w', newline='') as csvfile:
            fieldnames = [
                'recording_id', 'call_id', 'start_time', 'duration',
                'direction', 'from_number', 'to_number',
                'download_status', 'transcription_status', 'upload_status',
                'transcript_confidence', 'language_detected',
                'google_drive_file_id'
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for recording in recordings:
                writer.writerow({
                    'recording_id': recording.recording_id,
                    'call_id': recording.call_id,
                    'start_time': recording.start_time,
                    'duration': recording.duration,
                    'direction': recording.direction,
                    'from_number': recording.from_number,
                    'to_number': recording.to_number,
                    'download_status': recording.download_status,
                    'transcription_status': recording.transcription_status,
                    'upload_status': recording.upload_status,
                    'transcript_confidence': recording.transcript_confidence,
                    'language_detected': recording.language_detected,
                    'google_drive_file_id': recording.google_drive_file_id
                })

        logger.info(f"Exported {len(recordings)} recordings to {output_path}")
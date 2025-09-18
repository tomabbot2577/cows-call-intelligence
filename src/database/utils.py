"""
Database utility functions
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session

from src.database.models import CallRecording, ProcessingHistory, SystemMetric, ProcessingState
from src.database.session import SessionManager

logger = logging.getLogger(__name__)


class DatabaseUtils:
    """
    Database utility functions
    """

    @staticmethod
    def check_database_health(session_manager: SessionManager = None) -> Dict[str, Any]:
        """
        Check database health and connectivity

        Args:
            session_manager: Optional SessionManager instance

        Returns:
            Health status dictionary
        """
        if session_manager is None:
            from src.database.session import get_session_manager
            session_manager = get_session_manager()

        health_status = {
            'status': 'unknown',
            'connected': False,
            'tables_exist': False,
            'connection_info': {},
            'statistics': {},
            'error': None
        }

        try:
            # Check basic connectivity
            if session_manager.health_check():
                health_status['connected'] = True
                health_status['status'] = 'healthy'

                # Get connection pool info
                health_status['connection_info'] = session_manager.get_connection_info()

                # Check if tables exist
                inspector = inspect(session_manager.engine)
                tables = inspector.get_table_names()
                expected_tables = ['call_recordings', 'processing_history', 'system_metrics', 'processing_states']
                health_status['tables_exist'] = all(table in tables for table in expected_tables)

                # Get statistics
                with session_manager.get_session() as session:
                    health_status['statistics'] = {
                        'total_recordings': session.query(CallRecording).count(),
                        'pending_downloads': session.query(CallRecording).filter_by(
                            download_status='pending'
                        ).count(),
                        'completed_uploads': session.query(CallRecording).filter_by(
                            upload_status='completed'
                        ).count(),
                        'failed_recordings': session.query(CallRecording).filter(
                            (CallRecording.download_status == 'failed') |
                            (CallRecording.transcription_status == 'failed') |
                            (CallRecording.upload_status == 'failed')
                        ).count()
                    }
            else:
                health_status['status'] = 'unhealthy'
                health_status['error'] = 'Failed to connect to database'

        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['error'] = str(e)
            logger.error(f"Database health check failed: {e}")

        return health_status

    @staticmethod
    def cleanup_old_records(
        session: Session,
        days: int = 90,
        dry_run: bool = False
    ) -> Dict[str, int]:
        """
        Clean up old records from database

        Args:
            session: Database session
            days: Age threshold in days
            dry_run: If True, only count records without deleting

        Returns:
            Dictionary with cleanup statistics
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        stats = {}

        try:
            # Count old completed recordings
            old_completed = session.query(CallRecording).filter(
                CallRecording.created_at < cutoff_date,
                CallRecording.upload_status == 'completed'
            )
            stats['completed_recordings'] = old_completed.count()

            # Count old processing history
            old_history = session.query(ProcessingHistory).filter(
                ProcessingHistory.started_at < cutoff_date
            )
            stats['processing_history'] = old_history.count()

            # Count old metrics
            old_metrics = session.query(SystemMetric).filter(
                SystemMetric.timestamp < cutoff_date
            )
            stats['system_metrics'] = old_metrics.count()

            if not dry_run:
                # Delete old records
                old_completed.delete()
                old_history.delete()
                old_metrics.delete()
                session.commit()
                logger.info(f"Cleaned up old records: {stats}")
            else:
                logger.info(f"Dry run - would clean up: {stats}")

        except Exception as e:
            session.rollback()
            logger.error(f"Cleanup failed: {e}")
            raise

        return stats

    @staticmethod
    def reset_failed_recordings(
        session: Session,
        max_retries: int = 3
    ) -> int:
        """
        Reset failed recordings for retry

        Args:
            session: Database session
            max_retries: Maximum retry count

        Returns:
            Number of recordings reset
        """
        count = 0

        try:
            # Find failed recordings under retry limit
            failed_recordings = session.query(CallRecording).filter(
                ((CallRecording.download_status == 'failed') |
                 (CallRecording.transcription_status == 'failed') |
                 (CallRecording.upload_status == 'failed')),
                CallRecording.retry_count < max_retries
            ).all()

            for recording in failed_recordings:
                # Reset status based on failure point
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
                count += 1

            session.commit()
            logger.info(f"Reset {count} failed recordings for retry")

        except Exception as e:
            session.rollback()
            logger.error(f"Reset failed: {e}")
            raise

        return count

    @staticmethod
    def get_processing_statistics(session: Session) -> Dict[str, Any]:
        """
        Get detailed processing statistics

        Args:
            session: Database session

        Returns:
            Statistics dictionary
        """
        stats = {
            'total_recordings': 0,
            'status_breakdown': {},
            'daily_counts': [],
            'error_summary': {},
            'average_processing_time': None,
            'success_rate': 0.0
        }

        try:
            # Total recordings
            stats['total_recordings'] = session.query(CallRecording).count()

            # Status breakdown
            status_query = session.query(
                CallRecording.download_status,
                CallRecording.transcription_status,
                CallRecording.upload_status,
                text('COUNT(*)')
            ).group_by(
                CallRecording.download_status,
                CallRecording.transcription_status,
                CallRecording.upload_status
            ).all()

            stats['status_breakdown'] = [
                {
                    'download': row[0],
                    'transcription': row[1],
                    'upload': row[2],
                    'count': row[3]
                }
                for row in status_query
            ]

            # Daily counts for last 30 days
            daily_query = session.query(
                text("DATE(call_start_time) as date"),
                text("COUNT(*) as count")
            ).group_by(
                text("DATE(call_start_time)")
            ).order_by(
                text("DATE(call_start_time) DESC")
            ).limit(30).all()

            stats['daily_counts'] = [
                {'date': str(row[0]), 'count': row[1]}
                for row in daily_query
            ]

            # Error summary
            error_types = ['download_error', 'transcription_error', 'upload_error']
            for error_type in error_types:
                error_count = session.query(CallRecording).filter(
                    getattr(CallRecording, error_type).isnot(None)
                ).count()
                stats['error_summary'][error_type] = error_count

            # Calculate success rate
            completed = session.query(CallRecording).filter_by(
                upload_status='completed'
            ).count()
            if stats['total_recordings'] > 0:
                stats['success_rate'] = (completed / stats['total_recordings']) * 100

        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")

        return stats

    @staticmethod
    def migrate_data(
        source_session: Session,
        target_session: Session,
        batch_size: int = 100
    ) -> Dict[str, int]:
        """
        Migrate data between databases

        Args:
            source_session: Source database session
            target_session: Target database session
            batch_size: Batch size for migration

        Returns:
            Migration statistics
        """
        stats = {'recordings': 0, 'history': 0, 'metrics': 0}

        try:
            # Migrate call recordings
            recordings = source_session.query(CallRecording).all()
            for i in range(0, len(recordings), batch_size):
                batch = recordings[i:i + batch_size]
                for record in batch:
                    # Create new instance to avoid session conflicts
                    new_record = CallRecording(**{
                        col.name: getattr(record, col.name)
                        for col in CallRecording.__table__.columns
                        if col.name != 'id'
                    })
                    target_session.add(new_record)
                    stats['recordings'] += 1

                target_session.commit()

            logger.info(f"Migrated {stats['recordings']} recordings")

        except Exception as e:
            target_session.rollback()
            logger.error(f"Migration failed: {e}")
            raise

        return stats

    @staticmethod
    def create_backup_table(session: Session, table_name: str) -> bool:
        """
        Create backup of a table

        Args:
            session: Database session
            table_name: Table to backup

        Returns:
            True if successful
        """
        backup_name = f"{table_name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        try:
            session.execute(
                text(f"CREATE TABLE {backup_name} AS SELECT * FROM {table_name}")
            )
            session.commit()
            logger.info(f"Created backup table: {backup_name}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Backup failed: {e}")
            return False
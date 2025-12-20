"""
Database session management
"""

import logging
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.pool import QueuePool

from src.database.config import DatabaseConfig

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages database sessions with proper connection pooling
    """

    def __init__(self, db_config: DatabaseConfig):
        """
        Initialize session manager

        Args:
            db_config: Database configuration
        """
        self.db_config = db_config

        # Create engine with connection pooling
        self.engine = create_engine(
            db_config.database_url,
            pool_size=db_config.pool_size,
            max_overflow=db_config.max_overflow,
            pool_timeout=db_config.pool_timeout,
            pool_recycle=3600,  # Recycle connections after 1 hour
            pool_pre_ping=True,  # Verify connections before using
            poolclass=QueuePool,
            echo=db_config.echo
        )

        # Create session factory
        self._session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False
        )

        # Create scoped session for thread safety
        self.Session = scoped_session(self._session_factory)

        logger.info(f"SessionManager initialized with pool_size={db_config.pool_size}")

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Get a database session with automatic cleanup

        Yields:
            Database session

        Example:
            with session_manager.get_session() as session:
                result = session.query(Model).all()
        """
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Session error: {e}")
            raise
        finally:
            session.close()

    def get_new_session(self) -> Session:
        """
        Get a new session (caller responsible for closing)

        Returns:
            New database session
        """
        return self._session_factory()

    def close_all(self):
        """Close all sessions and dispose of engine"""
        self.Session.remove()
        self.engine.dispose()
        logger.info("All database connections closed")

    def execute_raw(self, query: str, params: dict = None):
        """
        Execute raw SQL query

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            Query result
        """
        with self.engine.connect() as conn:
            result = conn.execute(query, params or {})
            return result.fetchall()

    def get_connection_info(self) -> dict:
        """
        Get current connection pool information

        Returns:
            Dictionary with connection pool stats
        """
        pool = self.engine.pool
        return {
            'size': pool.size(),
            'checked_in': pool.checkedin(),
            'checked_out': pool.checkedout(),
            'overflow': pool.overflow(),
            'total': pool.size() + pool.overflow()
        }

    def health_check(self) -> bool:
        """
        Check database connectivity

        Returns:
            True if database is accessible
        """
        try:
            with self.get_session() as session:
                session.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


class DatabaseTransaction:
    """
    Context manager for database transactions
    """

    def __init__(self, session_manager: SessionManager):
        """
        Initialize transaction

        Args:
            session_manager: SessionManager instance
        """
        self.session_manager = session_manager
        self.session = None

    def __enter__(self) -> Session:
        """Begin transaction"""
        self.session = self.session_manager.get_new_session()
        self.session.begin()
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Complete or rollback transaction"""
        if exc_type is not None:
            self.session.rollback()
            logger.error(f"Transaction rolled back: {exc_val}")
        else:
            try:
                self.session.commit()
            except Exception as e:
                self.session.rollback()
                logger.error(f"Transaction commit failed: {e}")
                raise
        finally:
            self.session.close()


def get_session_manager(database_url: str = None) -> SessionManager:
    """
    Get a configured session manager

    Args:
        database_url: Optional database URL override

    Returns:
        SessionManager instance
    """
    from src.config.settings import Settings

    if database_url is None:
        settings = Settings()
        database_url = settings.database_url

    db_config = DatabaseConfig(database_url)
    return SessionManager(db_config)
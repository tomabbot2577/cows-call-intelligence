"""
Database connection and session management
"""

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.pool import NullPool, QueuePool
from dotenv import load_dotenv

load_dotenv()


class DatabaseConnection:
    """
    Manages database connections and sessions
    """

    def __init__(self, database_url: str = None):
        """
        Initialize database connection

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url or os.getenv('DATABASE_URL')

        if not self.database_url:
            raise ValueError("DATABASE_URL must be set")

        # Configure connection pool
        pool_config = {
            'pool_size': int(os.getenv('DB_POOL_SIZE', 20)),
            'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', 40)),
            'pool_timeout': int(os.getenv('DB_POOL_TIMEOUT', 30)),
            'pool_recycle': 3600,  # Recycle connections after 1 hour
            'pool_pre_ping': True,  # Test connections before using
        }

        # Create engine with appropriate pool
        if os.getenv('ENVIRONMENT') == 'test':
            # Use NullPool for testing
            self.engine = create_engine(
                self.database_url,
                poolclass=NullPool,
                echo=False
            )
        else:
            # Use QueuePool for production
            self.engine = create_engine(
                self.database_url,
                poolclass=QueuePool,
                echo=os.getenv('DB_ECHO', 'false').lower() == 'true',
                **pool_config
            )

        # Setup event listeners
        self._setup_listeners()

        # Create session factory
        self.SessionLocal = scoped_session(
            sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
        )

    def _setup_listeners(self):
        """
        Setup SQLAlchemy event listeners for monitoring
        """
        @event.listens_for(Engine, "connect")
        def receive_connect(dbapi_conn, connection_record):
            # Enable autocommit for better connection pooling
            dbapi_conn.autocommit = False

            # Set connection parameters
            with dbapi_conn.cursor() as cursor:
                cursor.execute("SET TIME ZONE 'UTC'")
                cursor.execute("SET statement_timeout = '300s'")

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Context manager for database sessions

        Yields:
            Session: SQLAlchemy session
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self):
        """
        Close all database connections
        """
        self.SessionLocal.remove()
        self.engine.dispose()


# Global database connection instance
_db_connection = None


def get_db_connection() -> DatabaseConnection:
    """
    Get or create global database connection

    Returns:
        DatabaseConnection: Database connection instance
    """
    global _db_connection
    if _db_connection is None:
        _db_connection = DatabaseConnection()
    return _db_connection


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Convenience function to get database session

    Yields:
        Session: SQLAlchemy session
    """
    db = get_db_connection()
    with db.get_session() as session:
        yield session
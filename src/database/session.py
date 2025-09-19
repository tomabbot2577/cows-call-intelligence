from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
import logging
import os

logger = logging.getLogger(__name__)

class DatabaseTransaction:
    def __init__(self, session: Session):
        self.session = session
    
    def __enter__(self):
        return self.session
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.session.rollback()
        else:
            self.session.commit()
        self.session.close()

class SessionManager:
    def __init__(self, database_url: Optional[str] = None):
        # Handle DatabaseConfig object or string URL
        if hasattr(database_url, 'database_url'):
            # It's a DatabaseConfig object
            actual_url = database_url.database_url
        elif isinstance(database_url, str):
            actual_url = database_url
        elif not database_url:
            actual_url = os.getenv('DATABASE_URL')
        else:
            actual_url = database_url

        if not actual_url:
            raise ValueError("DATABASE_URL not provided")

        self.engine = create_engine(
            actual_url,
            poolclass=NullPool,
            echo=False
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Session error: {e}")
            raise
        finally:
            session.close()
    
    def close(self):
        self.engine.dispose()

    def health_check(self) -> bool:
        """Check database health by attempting a simple query"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                return result.scalar() == 1
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def get_connection_info(self) -> dict:
        """Get database connection information"""
        url = self.engine.url
        return {
            'host': url.host,
            'port': url.port,
            'database': url.database,
            'driver': url.drivername,
            'pool_size': getattr(self.engine.pool, 'size', 'N/A')
        }

def get_session_manager() -> SessionManager:
    """Get or create a session manager instance"""
    database_url = os.getenv('DATABASE_URL')
    return SessionManager(database_url)

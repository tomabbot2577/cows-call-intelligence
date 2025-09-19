#!/usr/bin/env python3
"""
Initialize the database schema for the Call Recording System
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.models import Base
from src.database.session import SessionManager
from src.config.settings import Settings
from sqlalchemy import inspect
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_database():
    """Initialize database tables"""
    try:
        # Get database settings
        settings = Settings()

        # Create session manager
        session_manager = SessionManager(settings.database_url)

        # Create all tables
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=session_manager.engine)

        logger.info("Database tables created successfully!")

        # Verify tables were created
        inspector = inspect(session_manager.engine)
        tables = inspector.get_table_names()
        logger.info(f"Created tables: {', '.join(tables)}")

        # Close the connection
        session_manager.close()

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    init_database()
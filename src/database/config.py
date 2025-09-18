"""
Database configuration
"""

import os
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Optional


@dataclass
class DatabaseConfig:
    """
    Database configuration settings
    """
    database_url: str
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    echo: bool = False

    def __post_init__(self):
        """Validate and parse database URL"""
        if not self.database_url:
            raise ValueError("Database URL is required")

        # Parse URL to validate format
        parsed = urlparse(self.database_url)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError(f"Invalid database URL: {self.database_url}")

        # Set pool size from environment if available
        if os.getenv('DB_POOL_SIZE'):
            self.pool_size = int(os.getenv('DB_POOL_SIZE'))
        if os.getenv('DB_MAX_OVERFLOW'):
            self.max_overflow = int(os.getenv('DB_MAX_OVERFLOW'))
        if os.getenv('DB_POOL_TIMEOUT'):
            self.pool_timeout = int(os.getenv('DB_POOL_TIMEOUT'))
        if os.getenv('DEBUG'):
            self.echo = os.getenv('DEBUG', 'false').lower() == 'true'

    @property
    def host(self) -> str:
        """Get database host"""
        parsed = urlparse(self.database_url)
        return parsed.hostname or 'localhost'

    @property
    def port(self) -> int:
        """Get database port"""
        parsed = urlparse(self.database_url)
        return parsed.port or 5432

    @property
    def database(self) -> str:
        """Get database name"""
        parsed = urlparse(self.database_url)
        return parsed.path.lstrip('/')

    @property
    def username(self) -> Optional[str]:
        """Get database username"""
        parsed = urlparse(self.database_url)
        return parsed.username

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite"""
        return self.database_url.startswith('sqlite')

    @property
    def is_postgresql(self) -> bool:
        """Check if using PostgreSQL"""
        return self.database_url.startswith('postgresql')

    def get_connection_string(self, hide_password: bool = True) -> str:
        """
        Get connection string with optional password hiding

        Args:
            hide_password: Whether to hide password

        Returns:
            Connection string
        """
        if not hide_password:
            return self.database_url

        parsed = urlparse(self.database_url)
        if parsed.password:
            # Replace password with asterisks
            return self.database_url.replace(parsed.password, '****')
        return self.database_url
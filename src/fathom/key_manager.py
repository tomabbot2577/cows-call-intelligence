"""
Fathom API Key Manager

Manages encrypted storage and retrieval of employee Fathom API keys.
Uses Fernet symmetric encryption for secure storage.
"""

import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    raise ImportError("cryptography package required: pip install cryptography")

logger = logging.getLogger(__name__)


@dataclass
class FathomEmployee:
    """Represents an employee with Fathom API access."""
    id: int
    employee_name: str
    employee_email: str
    team: str
    is_active: bool
    is_admin: bool
    last_sync_at: Optional[datetime]
    last_recording_id: Optional[int]


class FathomKeyManager:
    """
    Manages Fathom API keys for employees.

    Provides:
    - Encrypted storage of API keys
    - CRUD operations for employee keys
    - Sync tracking per employee
    """

    def __init__(self, database_url: str = None, encryption_key: str = None):
        """
        Initialize the key manager.

        Args:
            database_url: PostgreSQL connection URL
            encryption_key: Fernet encryption key (base64 encoded)
        """
        self.database_url = database_url or os.getenv('RAG_DATABASE_URL')
        if not self.database_url:
            raise ValueError("Database URL is required")

        encryption_key = encryption_key or os.getenv('FATHOM_ENCRYPTION_KEY')
        if not encryption_key:
            raise ValueError("FATHOM_ENCRYPTION_KEY is required")

        # Initialize Fernet cipher
        self.fernet = Fernet(encryption_key.encode())

        logger.info("FathomKeyManager initialized")

    def _get_connection(self):
        """Get a database connection."""
        return psycopg2.connect(self.database_url)

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a string value."""
        return self.fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt a string value."""
        try:
            return self.fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            raise ValueError("Invalid encryption key or corrupted data")

    def add_employee(self, employee_name: str, employee_email: str,
                     api_key: str, team: str = None,
                     is_admin: bool = False) -> int:
        """
        Add a new employee with Fathom API access.

        Args:
            employee_name: Full name of the employee
            employee_email: Email address
            api_key: Fathom API key (will be encrypted)
            team: Team name (optional)
            is_admin: Whether this is an admin user

        Returns:
            The new employee ID
        """
        encrypted_key = self._encrypt(api_key)

        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO fathom_api_keys
                    (employee_name, employee_email, api_key_encrypted, team, is_active, is_admin)
                    VALUES (%s, %s, %s, %s, TRUE, %s)
                    ON CONFLICT (employee_email) DO UPDATE SET
                        employee_name = EXCLUDED.employee_name,
                        api_key_encrypted = EXCLUDED.api_key_encrypted,
                        team = EXCLUDED.team,
                        is_admin = EXCLUDED.is_admin,
                        is_active = TRUE,
                        updated_at = NOW()
                    RETURNING id
                """, (employee_name, employee_email, encrypted_key, team, is_admin))

                employee_id = cur.fetchone()[0]
                conn.commit()

                logger.info(f"Added/updated employee {employee_email} (id={employee_id})")
                return employee_id

        finally:
            conn.close()

    def get_api_key(self, employee_email: str) -> Optional[str]:
        """
        Get the decrypted API key for an employee.

        Args:
            employee_email: Email address of the employee

        Returns:
            Decrypted API key or None if not found
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT api_key_encrypted
                    FROM fathom_api_keys
                    WHERE employee_email = %s AND is_active = TRUE
                """, (employee_email,))

                row = cur.fetchone()
                if row:
                    return self._decrypt(row[0])
                return None

        finally:
            conn.close()

    def get_active_employees(self) -> List[FathomEmployee]:
        """
        Get all active employees with Fathom API keys.

        Returns:
            List of FathomEmployee objects
        """
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, employee_name, employee_email, team,
                           is_active, is_admin, last_sync_at, last_recording_id
                    FROM fathom_api_keys
                    WHERE is_active = TRUE
                    ORDER BY employee_name
                """)

                employees = []
                for row in cur.fetchall():
                    employees.append(FathomEmployee(
                        id=row['id'],
                        employee_name=row['employee_name'],
                        employee_email=row['employee_email'],
                        team=row['team'],
                        is_active=row['is_active'],
                        is_admin=row['is_admin'],
                        last_sync_at=row['last_sync_at'],
                        last_recording_id=row['last_recording_id']
                    ))

                return employees

        finally:
            conn.close()

    def get_employee(self, employee_email: str) -> Optional[FathomEmployee]:
        """
        Get an employee by email.

        Args:
            employee_email: Email address

        Returns:
            FathomEmployee object or None
        """
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, employee_name, employee_email, team,
                           is_active, is_admin, last_sync_at, last_recording_id
                    FROM fathom_api_keys
                    WHERE employee_email = %s
                """, (employee_email,))

                row = cur.fetchone()
                if row:
                    return FathomEmployee(
                        id=row['id'],
                        employee_name=row['employee_name'],
                        employee_email=row['employee_email'],
                        team=row['team'],
                        is_active=row['is_active'],
                        is_admin=row['is_admin'],
                        last_sync_at=row['last_sync_at'],
                        last_recording_id=row['last_recording_id']
                    )
                return None

        finally:
            conn.close()

    def update_sync_status(self, employee_email: str,
                           last_recording_id: int = None) -> bool:
        """
        Update the sync status for an employee.

        Args:
            employee_email: Email address
            last_recording_id: Most recent recording ID synced

        Returns:
            True if updated successfully
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE fathom_api_keys
                    SET last_sync_at = NOW(),
                        last_recording_id = COALESCE(%s, last_recording_id),
                        updated_at = NOW()
                    WHERE employee_email = %s
                """, (last_recording_id, employee_email))

                conn.commit()
                return cur.rowcount > 0

        finally:
            conn.close()

    def deactivate_employee(self, employee_email: str) -> bool:
        """
        Deactivate an employee's API key.

        Args:
            employee_email: Email address

        Returns:
            True if deactivated successfully
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE fathom_api_keys
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE employee_email = %s
                """, (employee_email,))

                conn.commit()
                updated = cur.rowcount > 0

                if updated:
                    logger.info(f"Deactivated employee {employee_email}")

                return updated

        finally:
            conn.close()

    def verify_key(self, employee_email: str) -> bool:
        """
        Verify that an employee's API key is valid.

        Args:
            employee_email: Email address

        Returns:
            True if key is valid and can authenticate
        """
        from .client import FathomClient

        api_key = self.get_api_key(employee_email)
        if not api_key:
            return False

        try:
            client = FathomClient(api_key)
            return client.verify_api_key()
        except Exception as e:
            logger.error(f"Error verifying key for {employee_email}: {e}")
            return False

    def get_admin_emails(self) -> List[str]:
        """
        Get email addresses of all admin users.

        Returns:
            List of admin email addresses
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT employee_email
                    FROM fathom_api_keys
                    WHERE is_admin = TRUE AND is_active = TRUE
                """)

                return [row[0] for row in cur.fetchall()]

        finally:
            conn.close()

    def get_employee_count(self) -> Dict[str, int]:
        """
        Get counts of employees by status.

        Returns:
            Dict with 'total', 'active', 'admin' counts
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE is_active = TRUE) as active,
                        COUNT(*) FILTER (WHERE is_admin = TRUE AND is_active = TRUE) as admin
                    FROM fathom_api_keys
                """)

                row = cur.fetchone()
                return {
                    'total': row[0],
                    'active': row[1],
                    'admin': row[2]
                }

        finally:
            conn.close()

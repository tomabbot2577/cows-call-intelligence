"""
Simple Authentication Service with Role-Based Access
Users: first letter + lastname (e.g., rmontoni)
Default password: see .env (DEFAULT_USER_PASSWORD)
Admin: admin / see .env (ADMIN_PASSWORD)
"""

import hashlib
import logging
from datetime import datetime
from typing import Dict, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash password with SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash."""
    # Check if it's a legacy format or direct comparison
    if hashed.startswith('pbkdf2:'):
        # Legacy format - extract actual password from end
        parts = hashed.split('$')
        if len(parts) >= 3:
            return password == parts[-1]
    # Check against hash
    return hash_password(password) == hashed


class AuthService:
    """Simple authentication with user/admin roles."""

    # Default passwords from environment
    import os as _os
    DEFAULT_USER_PASSWORD = _os.getenv("DEFAULT_USER_PASSWORD", "")
    ADMIN_PASSWORD = _os.getenv("ADMIN_PASSWORD", "")

    def __init__(self, connection_string: str = None):
        """Initialize with database connection."""
        import os
        # Use same database as DatabaseReader (call_insights has the transcripts and users)
        self.connection_string = connection_string or os.getenv(
            "RAG_DATABASE_URL",
            "" + os.getenv('DATABASE_URL', '')"
        )

    @contextmanager
    def get_connection(self):
        """Get database connection."""
        conn = psycopg2.connect(self.connection_string)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def authenticate(self, username: str, password: str) -> Optional[Dict]:
        """
        Authenticate user by username and password.
        Returns user dict with role if successful, None if failed.
        """
        username = username.lower().strip()

        # Try to find user in database
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, username, password_hash, display_name, role,
                           employee_name, is_active, must_change_password
                    FROM users
                    WHERE username = %s AND is_active = TRUE
                """, (username,))
                user = cur.fetchone()

                if user:
                    # Verify password
                    if verify_password(password, user['password_hash']):
                        # Update last login
                        cur.execute("""
                            UPDATE users SET last_login = NOW() WHERE id = %s
                        """, (user['id'],))
                        conn.commit()

                        return {
                            'id': user['id'],
                            'username': user['username'],
                            'display_name': user['display_name'],
                            'role': user['role'],
                            'employee_name': user['employee_name'],
                            'must_change_password': user['must_change_password']
                        }

        # If not in DB, check if it's the legacy admin password
        if username == 'admin' and password == self.ADMIN_PASSWORD:
            return {
                'id': 0,
                'username': 'admin',
                'display_name': 'Administrator',
                'role': 'admin',
                'employee_name': None,
                'must_change_password': False
            }

        return None

    def change_password(self, username: str, old_password: str, new_password: str) -> Dict:
        """
        Change user's password.
        Returns success/error status.
        """
        # Verify old password
        user = self.authenticate(username, old_password)
        if not user:
            return {'success': False, 'error': 'Current password is incorrect'}

        # Validate new password
        if len(new_password) < 6:
            return {'success': False, 'error': 'New password must be at least 6 characters'}

        if new_password == old_password:
            return {'success': False, 'error': 'New password must be different from current password'}

        # Update password
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users
                    SET password_hash = %s,
                        must_change_password = FALSE,
                        password_changed_at = NOW()
                    WHERE username = %s
                """, (hash_password(new_password), username.lower()))
                conn.commit()

        return {'success': True, 'message': 'Password changed successfully'}

    def admin_reset_password(self, admin_user: Dict, target_username: str) -> Dict:
        """
        Admin resets a user's password to default.
        """
        if admin_user.get('role') != 'admin':
            return {'success': False, 'error': 'Only admins can reset passwords'}

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if user exists
                cur.execute("SELECT id, username, display_name FROM users WHERE username = %s",
                           (target_username.lower(),))
                user = cur.fetchone()

                if not user:
                    return {'success': False, 'error': 'User not found'}

                # Reset to default password and require change
                default_hash = f'pbkdf2:sha256:600000$user${self.DEFAULT_USER_PASSWORD}'
                cur.execute("""
                    UPDATE users
                    SET password_hash = %s,
                        must_change_password = TRUE,
                        password_changed_at = NULL
                    WHERE username = %s
                """, (default_hash, target_username.lower()))
                conn.commit()

        return {
            'success': True,
            'message': f"Password reset for {user['display_name']}. Default password: {self.DEFAULT_USER_PASSWORD}"
        }

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user info by username."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, username, display_name, role, employee_name, is_active
                    FROM users
                    WHERE username = %s
                """, (username.lower(),))
                user = cur.fetchone()

                if user:
                    return dict(user)
        return None

    def create_user_from_employee(self, employee_name: str) -> Optional[Dict]:
        """
        Create a user account from an employee name.
        Format: first letter + lastname (e.g., Robin Montoni -> rmontoni)
        """
        parts = employee_name.strip().split()
        if len(parts) < 2:
            return None

        # Handle names like "Jodi O'Donnell"
        first_letter = parts[0][0].lower()
        last_name = parts[-1].lower().replace("'", "").replace("-", "")
        username = first_letter + last_name

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                try:
                    cur.execute("""
                        INSERT INTO users (username, password_hash, display_name, role, employee_name)
                        VALUES (%s, %s, %s, 'user', %s)
                        ON CONFLICT (username) DO UPDATE SET employee_name = EXCLUDED.employee_name
                        RETURNING id, username, display_name, role, employee_name
                    """, (username, f'pbkdf2:sha256:600000$user${self.USER_PASSWORD}',
                          employee_name, employee_name))
                    user = cur.fetchone()
                    conn.commit()
                    return dict(user) if user else None
                except Exception as e:
                    logger.error(f"Error creating user for {employee_name}: {e}")
                    return None

    def sync_users_from_employees(self) -> Dict:
        """Sync users table from known employee names."""
        from ..config.employee_names import get_canonical_employee_list

        employees = get_canonical_employee_list()
        created = 0
        updated = 0

        for emp in employees:
            result = self.create_user_from_employee(emp)
            if result:
                created += 1

        return {'created': created, 'updated': updated, 'total_employees': len(employees)}

    def list_users(self) -> list:
        """List all users."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, username, display_name, email, role, employee_name, is_active,
                           created_at, last_login
                    FROM users
                    ORDER BY role DESC, display_name
                """)
                return [dict(row) for row in cur.fetchall()]

    def is_admin(self, user: Dict) -> bool:
        """Check if user has admin role."""
        return user.get('role') == 'admin'

    def get_data_filter(self, user: Dict) -> Optional[str]:
        """
        Get the employee name to filter data by.
        Returns None for admins (no filter), employee_name for users.
        """
        if self.is_admin(user):
            return None  # Admin sees all data
        return user.get('employee_name')

    def change_user_role(self, admin_user: Dict, target_username: str, new_role: str) -> Dict:
        """
        Admin changes a user's role.
        """
        if admin_user.get('role') != 'admin':
            return {'success': False, 'error': 'Only admins can change roles'}

        if new_role not in ('user', 'admin'):
            return {'success': False, 'error': 'Role must be user or admin'}

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if user exists
                cur.execute("SELECT id, username, display_name, role FROM users WHERE username = %s",
                           (target_username.lower(),))
                user = cur.fetchone()

                if not user:
                    return {'success': False, 'error': 'User not found'}

                if user['role'] == new_role:
                    return {'success': False, 'error': f"User is already {new_role}"}

                # Update role
                cur.execute("""
                    UPDATE users SET role = %s WHERE username = %s
                """, (new_role, target_username.lower()))
                conn.commit()

        return {
            'success': True,
            'message': f"{user['display_name']} is now {new_role}"
        }

    def toggle_user_active(self, admin_user: Dict, target_username: str) -> Dict:
        """
        Admin toggles a user's active status.
        """
        if admin_user.get('role') != 'admin':
            return {'success': False, 'error': 'Only admins can change user status'}

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if user exists
                cur.execute("SELECT id, username, display_name, is_active FROM users WHERE username = %s",
                           (target_username.lower(),))
                user = cur.fetchone()

                if not user:
                    return {'success': False, 'error': 'User not found'}

                new_status = not user['is_active']
                cur.execute("""
                    UPDATE users SET is_active = %s WHERE username = %s
                """, (new_status, target_username.lower()))
                conn.commit()

        status_text = 'activated' if new_status else 'deactivated'
        return {
            'success': True,
            'message': f"{user['display_name']} has been {status_text}"
        }


def get_auth_service() -> AuthService:
    """Get AuthService instance."""
    return AuthService()

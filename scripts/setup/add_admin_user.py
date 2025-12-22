#!/usr/bin/env python3
"""
Add Steve Abbey as admin user with Fathom API key.

Usage:
    python scripts/setup/add_admin_user.py

This script:
1. Generates a Fernet encryption key if not exists in .env
2. Encrypts the Fathom API key
3. Inserts Steve Abbey as admin in fathom_api_keys table
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv, set_key

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
env_path = project_root / '.env'
load_dotenv(env_path)

try:
    from cryptography.fernet import Fernet
    import psycopg2
except ImportError:
    print("Installing required packages...")
    os.system(f"{sys.executable} -m pip install cryptography psycopg2-binary python-dotenv")
    from cryptography.fernet import Fernet
    import psycopg2


# Configuration
ADMIN_USER = {
    'employee_name': 'Steve Abbey',
    'employee_email': 'sabbey@mainsequence.net',
    'api_key': 'idMPkHx4E1MUtpKU5aAo0w.Esyt_nuoEitT_KT8q5UR8ucO1NaGBDssYaT_rJNAgoc',
    'team': 'Executive',
    'is_admin': True
}


def get_or_create_encryption_key() -> bytes:
    """Get existing or create new Fernet encryption key."""
    key = os.getenv('FATHOM_ENCRYPTION_KEY')

    if key:
        print("Using existing FATHOM_ENCRYPTION_KEY from .env")
        return key.encode()

    # Generate new key
    print("Generating new FATHOM_ENCRYPTION_KEY...")
    new_key = Fernet.generate_key()

    # Add to .env file
    with open(env_path, 'a') as f:
        f.write(f"\n# Fathom API key encryption\nFATHOM_ENCRYPTION_KEY={new_key.decode()}\n")

    print(f"Added FATHOM_ENCRYPTION_KEY to .env")
    return new_key


def encrypt_api_key(api_key: str, encryption_key: bytes) -> str:
    """Encrypt API key using Fernet."""
    f = Fernet(encryption_key)
    encrypted = f.encrypt(api_key.encode())
    return encrypted.decode()


def decrypt_api_key(encrypted_key: str, encryption_key: bytes) -> str:
    """Decrypt API key using Fernet."""
    f = Fernet(encryption_key)
    decrypted = f.decrypt(encrypted_key.encode())
    return decrypted.decode()


def get_db_connection():
    """Get database connection."""
    db_url = os.getenv('RAG_DATABASE_URL')
    if not db_url:
        raise ValueError("RAG_DATABASE_URL not set in .env")

    # Parse the URL
    # Format: postgresql://user:pass@host/dbname
    if db_url.startswith('postgresql://'):
        db_url = db_url[13:]

    parts = db_url.split('@')
    user_pass = parts[0].split(':')
    host_db = parts[1].split('/')

    return psycopg2.connect(
        host=host_db[0],
        database=host_db[1],
        user=user_pass[0],
        password=user_pass[1]
    )


def add_admin_user(user: dict, encryption_key: bytes) -> bool:
    """Add admin user to fathom_api_keys table."""
    encrypted_key = encrypt_api_key(user['api_key'], encryption_key)

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Check if user already exists
        cur.execute(
            "SELECT id, is_admin FROM fathom_api_keys WHERE employee_email = %s",
            (user['employee_email'],)
        )
        existing = cur.fetchone()

        if existing:
            print(f"User {user['employee_email']} already exists (id={existing[0]}, is_admin={existing[1]})")

            # Update the API key and admin status
            cur.execute("""
                UPDATE fathom_api_keys
                SET api_key_encrypted = %s,
                    employee_name = %s,
                    team = %s,
                    is_admin = %s,
                    is_active = TRUE,
                    updated_at = NOW()
                WHERE employee_email = %s
            """, (
                encrypted_key,
                user['employee_name'],
                user['team'],
                user['is_admin'],
                user['employee_email']
            ))
            print(f"Updated user {user['employee_email']}")
        else:
            # Insert new user
            cur.execute("""
                INSERT INTO fathom_api_keys
                (employee_name, employee_email, api_key_encrypted, team, is_active, is_admin)
                VALUES (%s, %s, %s, %s, TRUE, %s)
                RETURNING id
            """, (
                user['employee_name'],
                user['employee_email'],
                encrypted_key,
                user['team'],
                user['is_admin']
            ))
            new_id = cur.fetchone()[0]
            print(f"Created user {user['employee_email']} with id={new_id}")

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        return False
    finally:
        cur.close()
        conn.close()


def verify_user(email: str, encryption_key: bytes) -> bool:
    """Verify user was added correctly by decrypting the API key."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT employee_name, employee_email, api_key_encrypted,
                   team, is_admin, is_active
            FROM fathom_api_keys
            WHERE employee_email = %s
        """, (email,))

        row = cur.fetchone()
        if not row:
            print(f"User {email} not found!")
            return False

        name, email, encrypted_key, team, is_admin, is_active = row

        # Try to decrypt
        decrypted = decrypt_api_key(encrypted_key, encryption_key)

        print("\n--- User Verification ---")
        print(f"Name: {name}")
        print(f"Email: {email}")
        print(f"Team: {team}")
        print(f"Is Admin: {is_admin}")
        print(f"Is Active: {is_active}")
        print(f"API Key (decrypted): {decrypted[:20]}...{decrypted[-10:]}")
        print(f"API Key matches: {decrypted == ADMIN_USER['api_key']}")

        return decrypted == ADMIN_USER['api_key']

    except Exception as e:
        print(f"Verification error: {e}")
        return False
    finally:
        cur.close()
        conn.close()


def main():
    print("=" * 60)
    print("COWS Video Meeting Intelligence - Admin User Setup")
    print("=" * 60)

    # Step 1: Get or create encryption key
    print("\n[1/3] Setting up encryption key...")
    encryption_key = get_or_create_encryption_key()

    # Step 2: Add admin user
    print("\n[2/3] Adding admin user...")
    success = add_admin_user(ADMIN_USER, encryption_key)

    if not success:
        print("\nFailed to add admin user!")
        sys.exit(1)

    # Step 3: Verify
    print("\n[3/3] Verifying user...")
    verified = verify_user(ADMIN_USER['employee_email'], encryption_key)

    if verified:
        print("\n" + "=" * 60)
        print("SUCCESS! Admin user added and verified.")
        print("=" * 60)
    else:
        print("\nVerification failed!")
        sys.exit(1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Fetch Extension Directory from RingCentral

This script fetches the extension directory from RingCentral API
and populates the extension_employee_map table.

Usage:
    python -m rag_integration.jobs.fetch_extension_directory
"""

import os
import sys
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

# Add project root to path
sys.path.insert(0, '/var/www/call-recording-system')

# Load .env file
from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

from ringcentral import SDK

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(
        os.getenv('DATABASE_URL', '')
    )


def get_ringcentral_client():
    """Initialize and authenticate RingCentral SDK."""
    client_id = os.getenv('RC_CLIENT_ID') or os.getenv('RINGCENTRAL_CLIENT_ID')
    client_secret = os.getenv('RC_CLIENT_SECRET') or os.getenv('RINGCENTRAL_CLIENT_SECRET')
    jwt_token = os.getenv('RC_JWT_TOKEN') or os.getenv('RINGCENTRAL_JWT_TOKEN')
    server_url = os.getenv('RC_SERVER_URL') or os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')

    if not all([client_id, client_secret, jwt_token]):
        raise ValueError("Missing required RingCentral credentials in environment")

    sdk = SDK(client_id, client_secret, server_url)
    platform = sdk.platform()
    platform.login(jwt=jwt_token)
    logger.info("Successfully authenticated with RingCentral")

    return platform


def fetch_extensions(platform):
    """
    Fetch all extensions from RingCentral.

    Returns list of dicts with:
        extension_number, name, type, status, email
    """
    extensions = []

    try:
        # Get account ID
        response = platform.get('/restapi/v1.0/account/~')
        account_id = response.json().id

        # Fetch extensions list
        response = platform.get(
            f'/restapi/v1.0/account/{account_id}/extension',
            {
                'status': 'Enabled',
                'perPage': 1000
            }
        )
        result = response.json()

        for ext in result.records:
            ext_data = {
                'extension_number': getattr(ext, 'extensionNumber', None),
                'name': getattr(ext, 'name', None),
                'type': getattr(ext, 'type', None),
                'status': getattr(ext, 'status', None),
                'email': getattr(ext.contact, 'email', None) if hasattr(ext, 'contact') else None,
                'extension_id': getattr(ext, 'id', None)
            }

            # Only include User type extensions with numbers
            if ext_data['extension_number'] and ext_data['type'] == 'User':
                extensions.append(ext_data)
                logger.info(f"  Found: {ext_data['extension_number']} - {ext_data['name']}")

        logger.info(f"Found {len(extensions)} user extensions")

    except Exception as e:
        logger.error(f"Error fetching extensions: {e}")
        raise

    return extensions


def update_extension_map(extensions):
    """
    Update extension_employee_map with fetched extensions.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for ext in extensions:
                if not ext['extension_number'] or not ext['name']:
                    continue

                cur.execute("""
                    INSERT INTO extension_employee_map
                        (extension_number, employee_name, occurrence_count, first_seen, last_seen)
                    VALUES (%s, %s, 1, NOW(), NOW())
                    ON CONFLICT (extension_number) DO UPDATE SET
                        employee_name = EXCLUDED.employee_name,
                        last_seen = NOW()
                """, (ext['extension_number'], ext['name']))

            conn.commit()

    logger.info(f"Updated {len(extensions)} extensions in map")


def show_extension_map():
    """Show current extension map."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT extension_number, employee_name, occurrence_count
                FROM extension_employee_map
                ORDER BY extension_number
            """)
            mappings = cur.fetchall()

            logger.info("\nExtension-Employee Map:")
            for m in mappings:
                logger.info(f"  {m['extension_number']}: {m['employee_name']} ({m['occurrence_count']} calls)")


def main():
    logger.info("Fetching extension directory from RingCentral")

    # Initialize RingCentral client
    platform = get_ringcentral_client()

    # Fetch extensions
    extensions = fetch_extensions(platform)

    # Update database
    update_extension_map(extensions)

    # Show results
    show_extension_map()


if __name__ == '__main__':
    main()

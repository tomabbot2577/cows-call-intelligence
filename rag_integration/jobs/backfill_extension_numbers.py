#!/usr/bin/env python3
"""
Backfill Extension Numbers from call_legs

This script extracts extension numbers from the call_legs JSONB field
and populates the to_extension_number and from_extension_number fields
in the call_log table.

Usage:
    python -m rag_integration.jobs.backfill_extension_numbers [--dry-run] [--limit N]
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# Add project root to path
sys.path.insert(0, '/var/www/call-recording-system')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(
        'postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights'
    )


def extract_extension_from_legs(call_legs: list, direction: str) -> dict:
    """
    Extract extension numbers from call_legs.

    For inbound calls: Employee is the recipient (to)
    For outbound calls: Employee is the caller (from)

    Returns dict with:
        to_extension_number, to_name (final destination)
        from_extension_number, from_name (originator with ext)
    """
    result = {
        'to_extension_number': None,
        'to_name': None,
        'from_extension_number': None,
        'from_name': None
    }

    if not call_legs:
        return result

    # For each leg, check for extension numbers
    for leg in call_legs:
        if not isinstance(leg, dict):
            continue

        # Check 'to' party
        to_party = leg.get('to', {})
        if isinstance(to_party, dict):
            ext_num = to_party.get('extensionNumber')
            if ext_num:
                # Prefer the last leg with extension (final destination)
                result['to_extension_number'] = str(ext_num)
                result['to_name'] = to_party.get('name')

        # Check 'from_' party (note: stored as from_ in our legs)
        from_party = leg.get('from_', {}) or leg.get('from', {})
        if isinstance(from_party, dict):
            ext_num = from_party.get('extensionNumber')
            if ext_num:
                result['from_extension_number'] = str(ext_num)
                result['from_name'] = from_party.get('name')

    return result


def backfill_extensions(dry_run: bool = False, limit: int = None):
    """
    Backfill extension numbers from call_legs.

    Args:
        dry_run: If True, don't commit changes
        limit: Max records to process
    """
    logger.info(f"Starting extension backfill (dry_run={dry_run}, limit={limit})")

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get calls with legs but missing extension numbers
            query = """
                SELECT
                    id, ringcentral_id, direction, call_legs,
                    to_extension_number, from_extension_number,
                    to_name, from_name
                FROM call_log
                WHERE call_legs IS NOT NULL
                  AND jsonb_array_length(call_legs) > 0
                  AND (to_extension_number IS NULL OR from_extension_number IS NULL)
            """
            if limit:
                query += f" LIMIT {limit}"

            cur.execute(query)
            records = cur.fetchall()

            logger.info(f"Found {len(records)} calls to process")

            updated = 0
            skipped = 0

            for record in records:
                call_legs = record['call_legs']
                direction = record['direction']

                # Extract extension info from legs
                ext_info = extract_extension_from_legs(call_legs, direction)

                # Build update query only for fields that need updating
                updates = []
                params = []

                if ext_info['to_extension_number'] and not record['to_extension_number']:
                    updates.append("to_extension_number = %s")
                    params.append(ext_info['to_extension_number'])

                if ext_info['from_extension_number'] and not record['from_extension_number']:
                    updates.append("from_extension_number = %s")
                    params.append(ext_info['from_extension_number'])

                # Also update names if missing
                if ext_info['to_name'] and not record['to_name']:
                    updates.append("to_name = %s")
                    params.append(ext_info['to_name'])

                if ext_info['from_name'] and not record['from_name']:
                    updates.append("from_name = %s")
                    params.append(ext_info['from_name'])

                if updates:
                    params.append(record['id'])

                    if dry_run:
                        logger.info(
                            f"Would update {record['ringcentral_id']}: "
                            f"to_ext={ext_info['to_extension_number']}, "
                            f"from_ext={ext_info['from_extension_number']}"
                        )
                    else:
                        cur.execute(
                            f"UPDATE call_log SET {', '.join(updates)} WHERE id = %s",
                            params
                        )
                    updated += 1
                else:
                    skipped += 1

            if not dry_run:
                conn.commit()

            logger.info(f"Backfill complete: {updated} updated, {skipped} skipped")
            return updated, skipped


def update_extension_employee_map():
    """
    Update extension_employee_map with newly discovered extensions.
    Uses names from call_log that look like employee names.
    """
    logger.info("Updating extension_employee_map with new extensions")

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Find extensions with employee-like names not in the map
            cur.execute("""
                WITH extension_counts AS (
                    SELECT
                        to_extension_number as ext,
                        to_name as name,
                        COUNT(*) as cnt
                    FROM call_log
                    WHERE to_extension_number IS NOT NULL
                      AND to_name IS NOT NULL
                      AND to_name NOT LIKE '%IVR%'
                      AND to_name NOT LIKE '%Sales%'
                      AND to_name NOT LIKE '%Support%'
                      AND to_name NOT LIKE '%Queue%'
                    GROUP BY to_extension_number, to_name

                    UNION ALL

                    SELECT
                        from_extension_number as ext,
                        from_name as name,
                        COUNT(*) as cnt
                    FROM call_log
                    WHERE from_extension_number IS NOT NULL
                      AND from_name IS NOT NULL
                      AND from_name NOT LIKE '%IVR%'
                      AND from_name NOT LIKE '%Sales%'
                      AND from_name NOT LIKE '%Support%'
                      AND from_name NOT LIKE '%Queue%'
                    GROUP BY from_extension_number, from_name
                )
                SELECT ext, name, SUM(cnt) as total_count
                FROM extension_counts
                WHERE ext NOT IN (SELECT extension_number FROM extension_employee_map)
                GROUP BY ext, name
                HAVING SUM(cnt) >= 2
                ORDER BY total_count DESC
            """)

            new_extensions = cur.fetchall()
            logger.info(f"Found {len(new_extensions)} new extensions to map")

            for ext in new_extensions:
                logger.info(f"  Extension {ext['ext']}: {ext['name']} ({ext['total_count']} calls)")

                # Insert into map
                cur.execute("""
                    INSERT INTO extension_employee_map
                        (extension_number, employee_name, occurrence_count, first_seen, last_seen)
                    VALUES (%s, %s, %s, NOW(), NOW())
                    ON CONFLICT (extension_number) DO UPDATE SET
                        occurrence_count = extension_employee_map.occurrence_count + EXCLUDED.occurrence_count,
                        last_seen = NOW()
                """, (ext['ext'], ext['name'], ext['total_count']))

            conn.commit()
            return len(new_extensions)


def show_stats():
    """Show current extension coverage statistics."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    COUNT(to_extension_number) as has_to_ext,
                    COUNT(from_extension_number) as has_from_ext,
                    COUNT(*) FILTER (
                        WHERE to_extension_number IS NOT NULL
                           OR from_extension_number IS NOT NULL
                    ) as has_any_ext,
                    COUNT(*) FILTER (
                        WHERE to_extension_number IS NULL
                          AND from_extension_number IS NULL
                    ) as no_ext
                FROM call_log
                WHERE start_time >= '2024-12-01'
            """)
            stats = cur.fetchone()

            logger.info("Extension Coverage (Dec 2024+):")
            logger.info(f"  Total calls: {stats['total_calls']}")
            logger.info(f"  Has to_extension: {stats['has_to_ext']}")
            logger.info(f"  Has from_extension: {stats['has_from_ext']}")
            logger.info(f"  Has any extension: {stats['has_any_ext']}")
            logger.info(f"  No extension: {stats['no_ext']}")

            # Show extension_employee_map
            cur.execute("""
                SELECT extension_number, employee_name, occurrence_count
                FROM extension_employee_map
                ORDER BY occurrence_count DESC
            """)
            mappings = cur.fetchall()

            logger.info("\nExtension-Employee Mappings:")
            for m in mappings:
                logger.info(f"  {m['extension_number']}: {m['employee_name']} ({m['occurrence_count']} calls)")


def main():
    parser = argparse.ArgumentParser(description='Backfill extension numbers from call_legs')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--limit', type=int, help='Limit records to process')
    parser.add_argument('--stats', action='store_true', help='Show stats only')
    parser.add_argument('--update-map', action='store_true', help='Update extension_employee_map')

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    # Run backfill
    updated, skipped = backfill_extensions(dry_run=args.dry_run, limit=args.limit)

    if args.update_map and not args.dry_run:
        new_mappings = update_extension_employee_map()
        logger.info(f"Added {new_mappings} new extension mappings")

    # Show final stats
    show_stats()


if __name__ == '__main__':
    main()

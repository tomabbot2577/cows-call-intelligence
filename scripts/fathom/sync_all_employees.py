#!/usr/bin/env python3
"""
Fathom Meeting Sync - All Employees

Downloads video meeting data from Fathom AI for all configured employees.
Designed to run hourly via cron during business hours.

Usage:
    python scripts/fathom/sync_all_employees.py
    python scripts/fathom/sync_all_employees.py --hours-back 24
    python scripts/fathom/sync_all_employees.py --employee sabbey@mainsequence.net

Cron:
    30 8-17 * * 1-5 /var/www/call-recording-system/scripts/run_fathom_sync.sh
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from src.fathom.downloader import FathomDownloader

# Configure logging
log_dir = project_root / 'logs'
log_dir.mkdir(exist_ok=True)

log_file = log_dir / f"fathom_sync_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Fathom Meeting Sync')
    parser.add_argument('--hours-back', type=int, default=2,
                        help='Hours to look back for meetings (default: 2)')
    parser.add_argument('--employee', type=str,
                        help='Sync specific employee by email')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be synced without saving')

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Fathom Meeting Sync Started")
    logger.info(f"Hours back: {args.hours_back}")
    logger.info("=" * 60)

    try:
        downloader = FathomDownloader(hours_back=args.hours_back)

        if args.employee:
            # Sync single employee
            employee = downloader.key_manager.get_employee(args.employee)
            if not employee:
                logger.error(f"Employee not found: {args.employee}")
                sys.exit(1)

            logger.info(f"Syncing single employee: {employee.employee_name}")
            results = downloader.sync_employee(employee)

            logger.info(f"Results for {employee.employee_name}:")
            logger.info(f"  Meetings found: {results['meetings_found']}")
            logger.info(f"  Meetings saved: {results['meetings_saved']}")
            logger.info(f"  Duplicates skipped: {results['duplicates_skipped']}")

        else:
            # Sync all employees
            results = downloader.sync_all_employees()

            logger.info("=" * 60)
            logger.info("Fathom Sync Complete")
            logger.info("=" * 60)
            logger.info(f"Employees synced: {results['employees_synced']}")
            logger.info(f"Total meetings found: {results['total_meetings_found']}")
            logger.info(f"Total meetings saved: {results['total_meetings_saved']}")
            logger.info(f"Duplicates skipped: {results['total_duplicates_skipped']}")

            if results['errors']:
                logger.warning(f"Errors encountered: {len(results['errors'])}")
                for err in results['errors'][:10]:
                    logger.warning(f"  - {err}")

            # Save results to file for monitoring
            results_file = project_root / 'data' / 'scheduler' / 'fathom_sync_last.json'
            results_file.parent.mkdir(parents=True, exist_ok=True)

            with open(results_file, 'w') as f:
                json.dump(results, f, indent=2, default=str)

            logger.info(f"Results saved to {results_file}")

        return 0

    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())

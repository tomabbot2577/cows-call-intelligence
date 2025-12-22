#!/usr/bin/env python3
"""
RingCentral Video Meeting Sync

Syncs video meetings from RingCentral Video API.
Requires Video permission to be enabled on the RingCentral app.

Usage:
    python scripts/ringcentral/sync_video_meetings.py
    python scripts/ringcentral/sync_video_meetings.py --hours-back 24
    python scripts/ringcentral/sync_video_meetings.py --check-only

Cron:
    0 8-17 * * 1-5 /var/www/call-recording-system/scripts/run_ringcentral_video_sync.sh
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from src.ringcentral.video_sync_job import RCVideoSyncJob

# Configure logging
log_dir = project_root / 'logs'
log_dir.mkdir(exist_ok=True)

log_file = log_dir / f"ringcentral_video_sync_{datetime.now().strftime('%Y%m%d')}.log"

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
    parser = argparse.ArgumentParser(description='RingCentral Video Sync')
    parser.add_argument('--hours-back', type=int, default=12,
                        help='Hours to look back (default: 12)')
    parser.add_argument('--check-only', action='store_true',
                        help='Only check if Video API is accessible')

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("RingCentral Video Sync Started")
    logger.info(f"Hours back: {args.hours_back}")
    logger.info("=" * 60)

    try:
        sync_job = RCVideoSyncJob(hours_back=args.hours_back)

        if args.check_only:
            # Just check permission
            perm = sync_job.check_permission()
            logger.info(f"Video API Permission: {perm}")

            if perm['has_permission']:
                print("✓ Video API is accessible")
                return 0
            else:
                print(f"✗ Video API not accessible: {perm['message']}")
                print("\nTo enable Video API access:")
                print("  1. Go to RingCentral Developer Portal")
                print("  2. Select your app")
                print("  3. Add 'Video' permission")
                print("  4. Regenerate and update JWT token")
                return 1

        else:
            # Run sync
            results = sync_job.sync()

            logger.info("=" * 60)
            logger.info("RingCentral Video Sync Complete")
            logger.info("=" * 60)
            logger.info(f"Meetings found: {results['meetings_found']}")
            logger.info(f"Meetings saved: {results['meetings_saved']}")
            logger.info(f"Duplicates skipped: {results['duplicates_skipped']}")

            if results['errors']:
                logger.warning(f"Errors: {len(results['errors'])}")
                for err in results['errors'][:10]:
                    logger.warning(f"  - {err}")

            # Save results for monitoring
            results_file = project_root / 'data' / 'scheduler' / 'ringcentral_video_sync_last.json'
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

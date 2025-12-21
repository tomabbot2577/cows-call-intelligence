#!/usr/bin/env python3
"""
Freshdesk Sync Cron Job
Syncs Freshdesk tickets to Knowledge Base.
Run every 15 minutes via cron - uses lock file to prevent overlapping runs.
"""

import os
import sys
import fcntl
import logging
from datetime import datetime

# Add project to path
sys.path.insert(0, '/var/www/call-recording-system')

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

from rag_integration.services.freshdesk_scraper import FreshdeskScraper

# Lock file to prevent concurrent runs
LOCK_FILE = "/tmp/freshdesk_sync.lock"

# Setup logging
log_dir = '/var/www/call-recording-system/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/freshdesk_sync_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_qa_count_from_db() -> int:
    """Get current Q&A count directly from database."""
    import psycopg2
    db_url = os.getenv('RAG_DATABASE_URL',
                       'postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights')
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM kb_freshdesk_qa")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.error(f"Error getting count: {e}")
        return 0


def main():
    """Run Freshdesk sync with lock file protection."""

    # Try to acquire lock
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        logger.info("Another sync is already running, exiting")
        sys.exit(0)

    try:
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info(f"Freshdesk Sync Started at {start_time}")
        logger.info("=" * 60)

        # Get before count
        before_count = get_qa_count_from_db()
        logger.info(f"Starting Q&A count: {before_count}")

        scraper = FreshdeskScraper()

        # Test connection first
        test = scraper.test_connection()
        if not test['success']:
            logger.error(f"Freshdesk connection failed: {test.get('error')}")
            sys.exit(1)

        logger.info(f"Connected to {test['domain']}.freshdesk.com")

        # Sync last 7 days of tickets (incremental sync)
        # Limit to 100 tickets per run to stay within rate limits
        logger.info("Syncing tickets from last 7 days (max 100)...")
        stats = scraper.sync_tickets(since_days=7, max_tickets=100)

        logger.info(f"Sync complete:")
        logger.info(f"  Tickets processed: {stats['tickets_processed']}")
        logger.info(f"  Q&A pairs created: {stats['qa_pairs_created']}")
        logger.info(f"  Q&A pairs updated: {stats['qa_pairs_updated']}")
        logger.info(f"  Errors: {stats['errors']}")

        if stats['errors'] > 0:
            logger.warning(f"Errors encountered: {stats.get('error_details', [])[:5]}")

        # Get after count
        after_count = get_qa_count_from_db()
        elapsed = (datetime.now() - start_time).total_seconds()

        # Summary
        logger.info("=" * 60)
        logger.info(f"Sync completed in {elapsed:.1f} seconds")
        logger.info(f"Before: {before_count} | After: {after_count} | New: {after_count - before_count}")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Freshdesk sync failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
    finally:
        # Release lock
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            os.remove(LOCK_FILE)
        except:
            pass


if __name__ == "__main__":
    main()

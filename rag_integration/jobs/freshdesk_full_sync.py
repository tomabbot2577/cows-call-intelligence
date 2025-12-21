#!/usr/bin/env python3
"""
Freshdesk Full Sync - Syncs ALL tickets and exports to JSONL
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

from rag_integration.services.freshdesk_scraper import FreshdeskScraper

# Setup logging
log_dir = '/var/www/call-recording-system/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/freshdesk_full_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=" * 60)
    logger.info("FULL Freshdesk Sync - All Tickets")
    logger.info("=" * 60)

    scraper = FreshdeskScraper()

    # Test connection
    test = scraper.test_connection()
    if not test['success']:
        logger.error(f"Connection failed: {test.get('error')}")
        sys.exit(1)

    logger.info(f"Connected to {test['domain']}.freshdesk.com")

    # Full sync - 5 years, 10000 tickets
    logger.info("Syncing ALL tickets (5 years, max 10000)...")
    logger.info("This will take 1-2 hours due to API rate limits...")

    stats = scraper.sync_tickets(since_days=1825, max_tickets=10000)

    logger.info(f"Sync complete:")
    logger.info(f"  Tickets processed: {stats['tickets_processed']}")
    logger.info(f"  Q&A pairs created: {stats['qa_pairs_created']}")
    logger.info(f"  Q&A pairs updated: {stats['qa_pairs_updated']}")
    logger.info(f"  Errors: {stats['errors']}")

    # Export to JSONL
    logger.info("Exporting to JSONL...")
    export = scraper.export_to_jsonl()
    logger.info(f"Exported {export['exported']} Q&A pairs to {export['output_path']}")

    total = scraper.get_qa_count()
    logger.info(f"Total Q&A in Knowledge Base: {total}")
    logger.info("=" * 60)
    logger.info("DONE")


if __name__ == "__main__":
    main()

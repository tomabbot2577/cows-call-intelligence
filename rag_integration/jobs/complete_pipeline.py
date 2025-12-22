#!/usr/bin/env python3
"""
Complete Freshdesk Pipeline:
1. Wait for sync to complete (or run it)
2. Deduplicate data
3. Run AI enrichment
4. Export to JSONL
"""

import os
import sys
import time
import logging
import subprocess
from datetime import datetime

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

import psycopg2

log_dir = '/var/www/call-recording-system/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/complete_pipeline_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_db():
    return psycopg2.connect(
        os.getenv('RAG_DATABASE_URL',
                  '" + os.getenv('DATABASE_URL', '')')
    )


def get_stats():
    """Get current Q&A stats."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM kb_freshdesk_qa")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM kb_freshdesk_qa WHERE enriched_at IS NOT NULL")
    enriched = cur.fetchone()[0]

    conn.close()
    return total, enriched


def is_sync_running():
    """Check if sync is currently running."""
    result = subprocess.run(['pgrep', '-f', 'freshdesk_gentle_sync'], capture_output=True)
    return result.returncode == 0


def wait_for_sync():
    """Wait for sync to complete."""
    logger.info("=" * 60)
    logger.info("STEP 1: Waiting for Freshdesk sync to complete...")
    logger.info("=" * 60)

    while is_sync_running():
        total, enriched = get_stats()
        logger.info(f"Sync running... Current: {total} Q&As, {enriched} enriched")
        time.sleep(60)  # Check every minute

    total, _ = get_stats()
    logger.info(f"Sync complete! Total Q&As: {total}")
    return total


def deduplicate():
    """Remove duplicate Q&A entries."""
    logger.info("=" * 60)
    logger.info("STEP 2: Deduplicating data...")
    logger.info("=" * 60)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM kb_freshdesk_qa")
    before = cur.fetchone()[0]

    # Remove duplicates by ticket_id (keep lowest id)
    cur.execute("""
        DELETE FROM kb_freshdesk_qa a
        USING kb_freshdesk_qa b
        WHERE a.id > b.id
        AND a.ticket_id = b.ticket_id
    """)
    deleted = cur.rowcount
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM kb_freshdesk_qa")
    after = cur.fetchone()[0]

    conn.close()

    logger.info(f"Before: {before}, After: {after}, Deleted: {deleted} duplicates")
    return after


def run_enrichment(workers=25, limit=10000):
    """Run AI enrichment on unenriched Q&As."""
    logger.info("=" * 60)
    logger.info(f"STEP 3: Running AI enrichment ({workers} workers)...")
    logger.info("=" * 60)

    from rag_integration.jobs.enrich_freshdesk_parallel import OpenRouterEnricher, ensure_columns

    ensure_columns()
    enricher = OpenRouterEnricher()

    # Check how many need enrichment
    total, enriched = get_stats()
    pending = total - enriched

    if pending == 0:
        logger.info("All Q&As already enriched!")
        return {'enriched': enriched, 'errors': 0}

    logger.info(f"Enriching {pending} unenriched Q&As...")
    result = enricher.run_parallel(limit=min(limit, pending), workers=workers)

    logger.info(f"Enrichment complete: {result}")
    return result


def export_jsonl():
    """Export to JSONL for Vertex AI RAG."""
    logger.info("=" * 60)
    logger.info("STEP 4: Exporting to JSONL...")
    logger.info("=" * 60)

    from rag_integration.services.freshdesk_scraper import FreshdeskScraper

    scraper = FreshdeskScraper()
    result = scraper.export_to_jsonl()

    logger.info(f"Exported {result['exported']} Q&As to {result['output_path']}")
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-wait', action='store_true', help='Skip waiting for sync')
    parser.add_argument('--skip-dedupe', action='store_true', help='Skip deduplication')
    parser.add_argument('--skip-enrich', action='store_true', help='Skip enrichment')
    parser.add_argument('--skip-export', action='store_true', help='Skip export')
    parser.add_argument('--workers', type=int, default=25, help='Enrichment workers')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("COMPLETE FRESHDESK PIPELINE")
    logger.info("=" * 60)

    start_time = datetime.now()

    # Step 1: Wait for sync
    if not args.skip_wait:
        if is_sync_running():
            wait_for_sync()
        else:
            logger.info("No sync running, proceeding with existing data")

    # Step 2: Deduplicate
    if not args.skip_dedupe:
        deduplicate()

    # Step 3: Enrich
    if not args.skip_enrich:
        run_enrichment(workers=args.workers)

    # Step 4: Export
    if not args.skip_export:
        export_jsonl()

    # Final stats
    total, enriched = get_stats()
    duration = datetime.now() - start_time

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE!")
    logger.info(f"Total Q&As: {total}")
    logger.info(f"Enriched: {enriched}")
    logger.info(f"Duration: {duration}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

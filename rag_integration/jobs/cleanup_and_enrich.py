#!/usr/bin/env python3
"""
Cleanup and Enrich - Run after sync completes:
1. Remove duplicates
2. Run AI enrichment on clean data
3. Export to JSONL
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

import psycopg2
from psycopg2.extras import RealDictCursor

log_dir = '/var/www/call-recording-system/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/cleanup_enrich_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_db_connection():
    return psycopg2.connect(
        os.getenv('RAG_DATABASE_URL',
                  os.getenv('DATABASE_URL', ''))
    )


def deduplicate():
    """Remove duplicate Q&A entries (keep first by id)."""
    logger.info("=" * 60)
    logger.info("STEP 1: Deduplicating data")
    logger.info("=" * 60)

    conn = get_db_connection()
    cur = conn.cursor()

    # Count before
    cur.execute("SELECT COUNT(*) FROM kb_freshdesk_qa")
    before = cur.fetchone()[0]
    logger.info(f"Total Q&A before dedupe: {before}")

    # Find and remove duplicates by ticket_id (keep lowest id)
    cur.execute("""
        DELETE FROM kb_freshdesk_qa a
        USING kb_freshdesk_qa b
        WHERE a.id > b.id
        AND a.ticket_id = b.ticket_id
    """)
    deleted = cur.rowcount
    conn.commit()

    # Count after
    cur.execute("SELECT COUNT(*) FROM kb_freshdesk_qa")
    after = cur.fetchone()[0]

    logger.info(f"Deleted {deleted} duplicates")
    logger.info(f"Total Q&A after dedupe: {after}")

    conn.close()
    return {'before': before, 'after': after, 'deleted': deleted}


def reset_enrichment():
    """Reset enrichment status to re-process all."""
    logger.info("=" * 60)
    logger.info("STEP 2: Resetting enrichment status")
    logger.info("=" * 60)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("UPDATE kb_freshdesk_qa SET enriched_at = NULL")
    reset_count = cur.rowcount
    conn.commit()
    conn.close()

    logger.info(f"Reset {reset_count} Q&As for re-enrichment")
    return reset_count


def run_enrichment(workers=25, limit=10000):
    """Run parallel enrichment."""
    logger.info("=" * 60)
    logger.info(f"STEP 3: Running AI enrichment ({workers} workers)")
    logger.info("=" * 60)

    from rag_integration.jobs.enrich_freshdesk_parallel import OpenRouterEnricher, ensure_columns

    ensure_columns()
    enricher = OpenRouterEnricher()
    result = enricher.run_parallel(limit=limit, workers=workers)

    logger.info(f"Enrichment complete: {result}")
    return result


def export_jsonl():
    """Export to JSONL for Vertex AI RAG."""
    logger.info("=" * 60)
    logger.info("STEP 4: Exporting to JSONL")
    logger.info("=" * 60)

    from rag_integration.services.freshdesk_scraper import FreshdeskScraper

    scraper = FreshdeskScraper()
    result = scraper.export_to_jsonl()

    logger.info(f"Exported {result['exported']} Q&As to {result['output_path']}")
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-dedupe', action='store_true', help='Skip deduplication')
    parser.add_argument('--skip-reset', action='store_true', help='Skip enrichment reset')
    parser.add_argument('--skip-enrich', action='store_true', help='Skip enrichment')
    parser.add_argument('--skip-export', action='store_true', help='Skip JSONL export')
    parser.add_argument('--workers', type=int, default=25, help='Enrichment workers')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("FRESHDESK CLEANUP & ENRICHMENT")
    logger.info("=" * 60)

    # Step 1: Deduplicate
    if not args.skip_dedupe:
        dedupe_result = deduplicate()
    else:
        logger.info("Skipping deduplication")

    # Step 2: Reset enrichment (optional - to re-process all)
    if not args.skip_reset:
        reset_enrichment()
    else:
        logger.info("Skipping enrichment reset")

    # Step 3: Run enrichment
    if not args.skip_enrich:
        enrich_result = run_enrichment(workers=args.workers)
    else:
        logger.info("Skipping enrichment")

    # Step 4: Export to JSONL
    if not args.skip_export:
        export_result = export_jsonl()
    else:
        logger.info("Skipping export")

    logger.info("=" * 60)
    logger.info("ALL DONE!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

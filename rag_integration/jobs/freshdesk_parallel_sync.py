#!/usr/bin/env python3
"""
Parallel Freshdesk Sync - Runs 20 processes for different date ranges.
Each process handles a portion of the 5-year history.
"""

import os
import sys
import logging
import time
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

# Setup logging
log_dir = '/var/www/call-recording-system/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(processName)s] %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/freshdesk_parallel_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def sync_date_range(args):
    """Sync tickets for a specific date range."""
    start_days, end_days, worker_id = args

    # Each process needs its own imports
    import os
    import sys
    sys.path.insert(0, '/var/www/call-recording-system')
    from dotenv import load_dotenv
    load_dotenv('/var/www/call-recording-system/.env')

    import requests
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from datetime import datetime, timedelta
    import time
    import re
    import json

    domain = os.getenv('FRESHDESK_DOMAIN', 'mainsequencetechnology')
    api_key = os.getenv('FRESHDESK_API_KEY')
    db_url = os.getenv('RAG_DATABASE_URL', os.getenv('DATABASE_URL', ''))

    base_url = f"https://{domain}.freshdesk.com/api/v2"
    auth = (api_key, 'X')
    headers = {"Content-Type": "application/json"}

    # Calculate date range
    end_date = datetime.utcnow() - timedelta(days=end_days)
    start_date = datetime.utcnow() - timedelta(days=start_days)

    logger.info(f"Worker {worker_id}: Syncing {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")

    stats = {'processed': 0, 'created': 0, 'updated': 0, 'errors': 0}

    def clean_html(text):
        if not text:
            return ""
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'\s+', ' ', clean)
        clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&')
        return clean.strip()

    def get_agent_name(agent_id, cache={}):
        if agent_id in cache:
            return cache[agent_id]
        try:
            resp = requests.get(f"{base_url}/agents/{agent_id}", auth=auth, headers=headers, timeout=10)
            if resp.status_code == 200:
                name = resp.json().get('contact', {}).get('name', f'Agent {agent_id}')
                cache[agent_id] = name
                return name
        except:
            pass
        return f"Agent {agent_id}"

    try:
        conn = psycopg2.connect(db_url)
        page = 1

        while True:
            # Fetch tickets
            params = {
                "updated_since": start_date.strftime('%Y-%m-%dT00:00:00Z'),
                "order_by": "updated_at",
                "order_type": "asc",
                "per_page": 100,
                "page": page,
                "include": "description"
            }

            try:
                resp = requests.get(f"{base_url}/tickets", auth=auth, headers=headers, params=params, timeout=30)
                resp.raise_for_status()
                tickets = resp.json()
            except Exception as e:
                logger.error(f"Worker {worker_id}: Error fetching page {page}: {e}")
                time.sleep(5)
                continue

            if not tickets:
                break

            # Filter by date range and status
            for ticket in tickets:
                updated = datetime.strptime(ticket['updated_at'][:19], '%Y-%m-%dT%H:%M:%S')
                if updated > end_date:
                    # Past our date range, stop
                    logger.info(f"Worker {worker_id}: Reached end of date range")
                    conn.close()
                    return stats

                if ticket.get('status') not in [4, 5, 6]:
                    continue

                # Get conversations
                time.sleep(1.5)  # Rate limit - Freshdesk is strict
                try:
                    conv_resp = requests.get(f"{base_url}/tickets/{ticket['id']}/conversations",
                                            auth=auth, headers=headers, timeout=30)
                    conversations = conv_resp.json() if conv_resp.status_code == 200 else []
                except:
                    conversations = []

                # Extract Q&A
                subject = ticket.get('subject', '').strip()
                description = clean_html(ticket.get('description_text', '') or ticket.get('description', ''))

                if not subject:
                    continue

                question = subject
                if description and len(description) > 20:
                    question += "\n" + description[:1000]

                # Find agent reply
                agent_replies = [c for c in conversations if not c.get('incoming', True)]
                answer = None
                responder_id = None

                for reply in agent_replies:
                    body = clean_html(reply.get('body_text', '') or reply.get('body', ''))
                    if len(body) >= 30:
                        answer = body[:2000]
                        responder_id = reply.get('user_id')
                        break

                if not answer:
                    continue

                agent_name = get_agent_name(responder_id) if responder_id else None
                qa_id = f"fd_{ticket['id']}"

                # Save to DB
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM kb_freshdesk_qa WHERE qa_id = %s", (qa_id,))
                    existing = cur.fetchone()

                    if existing:
                        cur.execute("""
                            UPDATE kb_freshdesk_qa
                            SET question = %s, answer = %s, category = %s, tags = %s,
                                requester_email = %s, agent_name = %s, priority = %s,
                                resolved_at = %s, synced_at = NOW()
                            WHERE qa_id = %s
                        """, (question, answer, ticket.get('type') or 'general',
                              ticket.get('tags', []),
                              ticket.get('requester', {}).get('email') if isinstance(ticket.get('requester'), dict) else None,
                              agent_name, ticket.get('priority'),
                              ticket.get('updated_at'), qa_id))
                        stats['updated'] += 1
                    else:
                        cur.execute("""
                            INSERT INTO kb_freshdesk_qa
                            (qa_id, question, answer, category, tags, ticket_id,
                             requester_email, agent_name, priority, created_at, resolved_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (qa_id, question, answer, ticket.get('type') or 'general',
                              ticket.get('tags', []), ticket['id'],
                              ticket.get('requester', {}).get('email') if isinstance(ticket.get('requester'), dict) else None,
                              agent_name, ticket.get('priority'),
                              ticket.get('created_at'), ticket.get('updated_at')))
                        stats['created'] += 1

                    conn.commit()

                stats['processed'] += 1
                if stats['processed'] % 50 == 0:
                    logger.info(f"Worker {worker_id}: Processed {stats['processed']} tickets")

            page += 1
            time.sleep(3)  # Rate limit between pages

        conn.close()

    except Exception as e:
        logger.error(f"Worker {worker_id}: Fatal error: {e}")
        stats['errors'] += 1

    logger.info(f"Worker {worker_id}: Done - {stats}")
    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=20, help='Number of parallel workers')
    parser.add_argument('--days', type=int, default=1825, help='Days of history (default 5 years)')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"Parallel Freshdesk Sync - {args.workers} workers, {args.days} days")
    logger.info("=" * 60)

    # Split date range into chunks for each worker
    days_per_worker = args.days // args.workers
    work_items = []

    for i in range(args.workers):
        start_days = i * days_per_worker
        end_days = start_days + days_per_worker if i < args.workers - 1 else 0
        work_items.append((start_days + days_per_worker, start_days, i + 1))

    # Run workers
    total_stats = {'processed': 0, 'created': 0, 'updated': 0, 'errors': 0}

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(sync_date_range, item): item for item in work_items}

        for future in as_completed(futures):
            try:
                result = future.result()
                for key in total_stats:
                    total_stats[key] += result.get(key, 0)
            except Exception as e:
                logger.error(f"Worker failed: {e}")
                total_stats['errors'] += 1

    logger.info("=" * 60)
    logger.info(f"COMPLETE: {total_stats}")
    logger.info("=" * 60)

    return total_stats


if __name__ == "__main__":
    main()

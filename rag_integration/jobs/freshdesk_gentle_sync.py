#!/usr/bin/env python3
"""
Gentle Freshdesk Sync - Single process with long delays to respect rate limits.
Syncs all tickets from 2021-present without hitting 429 errors.
"""

import os
import sys
import logging
import time
import re
import requests
from datetime import datetime, timedelta

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

import psycopg2
from psycopg2.extras import RealDictCursor

# Setup logging
log_dir = '/var/www/call-recording-system/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/freshdesk_gentle_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class GentleFreshdeskSync:
    """Gentle Freshdesk sync with rate limit handling."""

    def __init__(self):
        self.domain = os.getenv('FRESHDESK_DOMAIN', 'mainsequencetechnology')
        self.api_key = os.getenv('FRESHDESK_API_KEY')
        self.db_url = os.getenv('RAG_DATABASE_URL',
                                '" + os.getenv('DATABASE_URL', '')')

        self.base_url = f"https://{self.domain}.freshdesk.com/api/v2"
        self.auth = (self.api_key, 'X')
        self.headers = {"Content-Type": "application/json"}

        # Gentle timing
        self.base_delay = 10  # 10 seconds between requests
        self.page_delay = 15  # 15 seconds between pages
        self.backoff_multiplier = 2
        self.max_backoff = 300  # Max 5 minute wait

        self.stats = {'processed': 0, 'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
        self.agent_cache = {}

    def clean_html(self, text):
        if not text:
            return ""
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'\s+', ' ', clean)
        clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&')
        clean = clean.replace('&lt;', '<').replace('&gt;', '>')
        return clean.strip()

    def get_agent_name(self, agent_id):
        if not agent_id:
            return None
        if agent_id in self.agent_cache:
            return self.agent_cache[agent_id]

        try:
            time.sleep(2)  # Rate limit for agent lookup
            resp = requests.get(f"{self.base_url}/agents/{agent_id}",
                               auth=self.auth, headers=self.headers, timeout=15)
            if resp.status_code == 200:
                name = resp.json().get('contact', {}).get('name', f'Agent {agent_id}')
                self.agent_cache[agent_id] = name
                return name
            elif resp.status_code == 429:
                logger.warning("Rate limited on agent lookup, using ID")
                return f"Agent {agent_id}"
        except Exception as e:
            logger.warning(f"Agent lookup failed: {e}")

        return f"Agent {agent_id}"

    def api_request(self, url, params=None):
        """Make API request with exponential backoff."""
        backoff = self.base_delay

        for attempt in range(10):  # Max 10 retries
            try:
                resp = requests.get(url, auth=self.auth, headers=self.headers,
                                   params=params, timeout=30)

                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    # Rate limited - back off
                    retry_after = int(resp.headers.get('Retry-After', backoff))
                    wait_time = max(retry_after, backoff)
                    logger.warning(f"Rate limited (429). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    backoff = min(backoff * self.backoff_multiplier, self.max_backoff)
                else:
                    logger.error(f"API error {resp.status_code}: {resp.text[:200]}")
                    return None

            except Exception as e:
                logger.error(f"Request failed: {e}")
                time.sleep(backoff)
                backoff = min(backoff * self.backoff_multiplier, self.max_backoff)

        return None

    def sync_all(self, start_date=None, end_date=None):
        """Sync all tickets from start_date to end_date."""
        if not start_date:
            start_date = datetime(2021, 1, 1)
        if not end_date:
            end_date = datetime.utcnow()

        logger.info("=" * 60)
        logger.info(f"Gentle Freshdesk Sync: {start_date.date()} to {end_date.date()}")
        logger.info("=" * 60)

        conn = psycopg2.connect(self.db_url)
        page = 1

        try:
            while True:
                logger.info(f"Fetching page {page}...")

                params = {
                    "updated_since": start_date.strftime('%Y-%m-%dT00:00:00Z'),
                    "order_by": "updated_at",
                    "order_type": "asc",
                    "per_page": 100,
                    "page": page,
                    "include": "description"
                }

                tickets = self.api_request(f"{self.base_url}/tickets", params)

                if not tickets:
                    logger.info("No more tickets or API error")
                    break

                if len(tickets) == 0:
                    logger.info("Empty page - sync complete")
                    break

                logger.info(f"Processing {len(tickets)} tickets from page {page}")

                for ticket in tickets:
                    self.process_ticket(conn, ticket, end_date)

                # Log progress
                logger.info(f"Progress: {self.stats}")

                page += 1

                # Gentle delay between pages
                logger.info(f"Waiting {self.page_delay}s before next page...")
                time.sleep(self.page_delay)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            conn.close()

        logger.info("=" * 60)
        logger.info(f"SYNC COMPLETE: {self.stats}")
        logger.info("=" * 60)

        return self.stats

    def process_ticket(self, conn, ticket, end_date):
        """Process a single ticket."""
        try:
            # Check if past end date
            updated = datetime.strptime(ticket['updated_at'][:19], '%Y-%m-%dT%H:%M:%S')
            if updated > end_date:
                self.stats['skipped'] += 1
                return

            # Only process resolved/closed tickets
            if ticket.get('status') not in [4, 5, 6]:
                self.stats['skipped'] += 1
                return

            # Get conversations (with rate limiting)
            time.sleep(self.base_delay)
            conversations = self.api_request(
                f"{self.base_url}/tickets/{ticket['id']}/conversations"
            ) or []

            # Extract Q&A
            subject = ticket.get('subject', '').strip()
            description = self.clean_html(
                ticket.get('description_text', '') or ticket.get('description', '')
            )

            if not subject:
                self.stats['skipped'] += 1
                return

            question = subject
            if description and len(description) > 20:
                question += "\n" + description[:2000]

            # Find agent reply
            agent_replies = [c for c in conversations if not c.get('incoming', True)]
            answer = None
            responder_id = None

            for reply in agent_replies:
                body = self.clean_html(reply.get('body_text', '') or reply.get('body', ''))
                if len(body) >= 30:
                    answer = body[:4000]
                    responder_id = reply.get('user_id')
                    break

            if not answer:
                self.stats['skipped'] += 1
                return

            agent_name = self.get_agent_name(responder_id)
            qa_id = f"fd_{ticket['id']}"

            # Save to DB
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM kb_freshdesk_qa WHERE qa_id = %s", (qa_id,))
                existing = cur.fetchone()

                requester_email = None
                if isinstance(ticket.get('requester'), dict):
                    requester_email = ticket['requester'].get('email')

                if existing:
                    cur.execute("""
                        UPDATE kb_freshdesk_qa
                        SET question = %s, answer = %s, category = %s, tags = %s,
                            requester_email = %s, agent_name = %s, priority = %s,
                            resolved_at = %s, synced_at = NOW()
                        WHERE qa_id = %s
                    """, (question, answer, ticket.get('type') or 'general',
                          ticket.get('tags', []), requester_email,
                          agent_name, ticket.get('priority'),
                          ticket.get('updated_at'), qa_id))
                    self.stats['updated'] += 1
                else:
                    cur.execute("""
                        INSERT INTO kb_freshdesk_qa
                        (qa_id, question, answer, category, tags, ticket_id,
                         requester_email, agent_name, priority, created_at, resolved_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (qa_id, question, answer, ticket.get('type') or 'general',
                          ticket.get('tags', []), ticket['id'], requester_email,
                          agent_name, ticket.get('priority'),
                          ticket.get('created_at'), ticket.get('updated_at')))
                    self.stats['created'] += 1

                conn.commit()

            self.stats['processed'] += 1

            if self.stats['processed'] % 25 == 0:
                logger.info(f"Processed {self.stats['processed']} Q&As")

        except Exception as e:
            logger.error(f"Error processing ticket {ticket.get('id')}: {e}")
            self.stats['errors'] += 1
            conn.rollback()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-year', type=int, default=2021)
    parser.add_argument('--end-year', type=int, default=2025)
    args = parser.parse_args()

    syncer = GentleFreshdeskSync()

    start_date = datetime(args.start_year, 1, 1)
    end_date = datetime.utcnow()

    result = syncer.sync_all(start_date, end_date)
    return result


if __name__ == "__main__":
    main()

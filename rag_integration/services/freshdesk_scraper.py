"""
Freshdesk Scraper Service
Pull resolved tickets from Freshdesk, extract Q&A pairs for Knowledge Base
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import re

logger = logging.getLogger(__name__)


class FreshdeskScraper:
    """Scrape resolved tickets from Freshdesk and store as Q&A pairs."""

    def __init__(self, domain: str = None, api_key: str = None, connection_string: str = None):
        """
        Initialize Freshdesk scraper.

        Args:
            domain: Freshdesk subdomain (e.g., 'yourcompany' for yourcompany.freshdesk.com)
            api_key: Freshdesk API key
            connection_string: Database connection string
        """
        self.domain = domain or os.getenv('FRESHDESK_DOMAIN', 'pcrecruiter')
        self.api_key = api_key or os.getenv('FRESHDESK_API_KEY')

        if not self.api_key:
            raise ValueError("Freshdesk API key required. Set FRESHDESK_API_KEY env var.")

        self.base_url = f"https://{self.domain}.freshdesk.com/api/v2"
        self.auth = (self.api_key, 'X')
        self.headers = {"Content-Type": "application/json"}

        # Database connection
        self.connection_string = connection_string or os.getenv(
            "RAG_DATABASE_URL",
            "postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights"
        )

        # Cache for agent names
        self._agent_cache = {}

    @contextmanager
    def get_connection(self):
        """Get database connection."""
        conn = psycopg2.connect(self.connection_string)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def get_agent_name(self, agent_id: int) -> str:
        """Get agent name from ID (cached)."""
        if agent_id in self._agent_cache:
            return self._agent_cache[agent_id]

        try:
            url = f"{self.base_url}/agents/{agent_id}"
            resp = requests.get(url, auth=self.auth, headers=self.headers)
            if resp.status_code == 200:
                agent = resp.json()
                name = agent.get('contact', {}).get('name', f'Agent {agent_id}')
                self._agent_cache[agent_id] = name
                return name
        except Exception as e:
            logger.warning(f"Could not get agent name for {agent_id}: {e}")

        return f"Agent {agent_id}"

    def get_resolved_tickets(self, since_days: int = 30, page: int = 1) -> List[Dict]:
        """Get resolved tickets from last N days."""
        since = (datetime.utcnow() - timedelta(days=since_days)).strftime('%Y-%m-%dT00:00:00Z')

        url = f"{self.base_url}/tickets"
        params = {
            "updated_since": since,
            "order_by": "updated_at",
            "order_type": "desc",
            "per_page": 100,
            "page": page,
            "include": "description"
        }

        try:
            resp = requests.get(url, auth=self.auth, headers=self.headers, params=params, timeout=30)
            resp.raise_for_status()

            tickets = resp.json()
            # Filter to resolved/closed statuses: 4=Resolved, 5=Closed, 6=Custom closed
            return [t for t in tickets if t.get('status') in [4, 5, 6]]
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching tickets page {page}: {e}")
            return []

    def get_conversations(self, ticket_id: int) -> List[Dict]:
        """Get all conversations for a ticket."""
        url = f"{self.base_url}/tickets/{ticket_id}/conversations"

        try:
            resp = requests.get(url, auth=self.auth, headers=self.headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching conversations for ticket {ticket_id}: {e}")
            return []

    def clean_html(self, text: str) -> str:
        """Remove HTML tags and clean text."""
        if not text:
            return ""
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', ' ', text)
        # Remove extra whitespace
        clean = re.sub(r'\s+', ' ', clean)
        # Remove common HTML entities
        clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&')
        clean = clean.replace('&lt;', '<').replace('&gt;', '>')
        return clean.strip()

    def extract_qa(self, ticket: Dict, conversations: List[Dict]) -> Optional[Dict]:
        """Extract Q&A pair from ticket + conversations."""

        # Build question from ticket subject and description
        subject = ticket.get('subject', '').strip()
        description = self.clean_html(ticket.get('description_text', '') or ticket.get('description', ''))

        if not subject:
            return None

        question = subject
        if description and len(description) > 20:
            # Limit description length
            question += "\n" + description[:1000]

        # Find agent replies (incoming=false means agent sent it)
        agent_replies = [c for c in conversations if not c.get('incoming', True)]

        if not agent_replies:
            return None

        # Get first substantive agent reply as answer
        answer = None
        responder_id = None
        for reply in agent_replies:
            body = self.clean_html(reply.get('body_text', '') or reply.get('body', ''))
            if len(body) >= 30:  # Skip very short replies
                answer = body[:2000]  # Limit answer length
                responder_id = reply.get('user_id')
                break

        if not answer:
            return None

        # Get agent name
        agent_name = None
        if responder_id:
            agent_name = self.get_agent_name(responder_id)

        # Get category from type or tags
        category = ticket.get('type') or 'general'
        tags = ticket.get('tags', []) or []

        # Get requester email
        requester_email = ticket.get('requester', {}).get('email') if isinstance(ticket.get('requester'), dict) else None

        return {
            "qa_id": f"fd_{ticket['id']}",
            "question": question,
            "answer": answer,
            "category": category,
            "tags": tags,
            "ticket_id": ticket['id'],
            "requester_email": requester_email,
            "agent_name": agent_name,
            "priority": ticket.get('priority'),
            "created_at": ticket.get('created_at'),
            "resolved_at": ticket.get('updated_at')
        }

    def sync_tickets(self, since_days: int = 30, max_tickets: int = 500) -> Dict:
        """
        Sync resolved tickets from Freshdesk to KB database.

        Returns sync statistics.
        """
        # Start sync log
        sync_id = self._start_sync_log()

        stats = {
            'tickets_processed': 0,
            'qa_pairs_created': 0,
            'qa_pairs_updated': 0,
            'errors': 0,
            'error_details': []
        }

        page = 1
        total_processed = 0

        try:
            while total_processed < max_tickets:
                logger.info(f"Fetching tickets page {page}...")
                tickets = self.get_resolved_tickets(since_days, page)

                if not tickets:
                    logger.info("No more tickets found")
                    break

                for ticket in tickets:
                    if total_processed >= max_tickets:
                        break

                    # Rate limit: 0.5 second between conversation fetches
                    time.sleep(0.5)

                    try:
                        conversations = self.get_conversations(ticket['id'])
                        qa = self.extract_qa(ticket, conversations)

                        if qa:
                            created, updated = self._save_qa(qa)
                            if created:
                                stats['qa_pairs_created'] += 1
                            elif updated:
                                stats['qa_pairs_updated'] += 1
                            logger.info(f"Processed ticket {ticket['id']}: {'created' if created else 'updated' if updated else 'skipped'}")

                        stats['tickets_processed'] += 1
                        total_processed += 1

                    except Exception as e:
                        stats['errors'] += 1
                        error_msg = f"Ticket {ticket['id']}: {str(e)}"
                        stats['error_details'].append(error_msg)
                        logger.error(error_msg)

                page += 1
                time.sleep(1)  # Rate limit between pages

            # Complete sync log
            self._complete_sync_log(sync_id, stats, 'completed')

        except Exception as e:
            stats['error_details'].append(f"Sync failed: {str(e)}")
            self._complete_sync_log(sync_id, stats, 'failed')
            raise

        return stats

    def _save_qa(self, qa: Dict) -> tuple:
        """Save Q&A to database. Returns (created, updated) booleans."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Check if exists
                cur.execute("SELECT id FROM kb_freshdesk_qa WHERE qa_id = %s", (qa['qa_id'],))
                existing = cur.fetchone()

                if existing:
                    # Update
                    cur.execute("""
                        UPDATE kb_freshdesk_qa
                        SET question = %s, answer = %s, category = %s, tags = %s,
                            requester_email = %s, agent_name = %s, priority = %s,
                            resolved_at = %s, synced_at = NOW()
                        WHERE qa_id = %s
                    """, (
                        qa['question'], qa['answer'], qa['category'], qa['tags'],
                        qa['requester_email'], qa['agent_name'], qa['priority'],
                        qa['resolved_at'], qa['qa_id']
                    ))
                    return (False, True)
                else:
                    # Insert
                    cur.execute("""
                        INSERT INTO kb_freshdesk_qa
                        (qa_id, question, answer, category, tags, ticket_id,
                         requester_email, agent_name, priority, created_at, resolved_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        qa['qa_id'], qa['question'], qa['answer'], qa['category'],
                        qa['tags'], qa['ticket_id'], qa['requester_email'],
                        qa['agent_name'], qa['priority'], qa['created_at'], qa['resolved_at']
                    ))
                    return (True, False)

    def _start_sync_log(self) -> int:
        """Start a sync log entry."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO kb_freshdesk_sync_log (status)
                    VALUES ('running')
                    RETURNING id
                """)
                return cur.fetchone()[0]

    def _complete_sync_log(self, sync_id: int, stats: Dict, status: str):
        """Complete a sync log entry."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE kb_freshdesk_sync_log
                    SET completed_at = NOW(),
                        tickets_processed = %s,
                        qa_pairs_created = %s,
                        qa_pairs_updated = %s,
                        errors = %s,
                        error_details = %s,
                        status = %s
                    WHERE id = %s
                """, (
                    stats['tickets_processed'],
                    stats['qa_pairs_created'],
                    stats['qa_pairs_updated'],
                    stats['errors'],
                    json.dumps(stats['error_details'][:50]),  # Limit error details
                    status,
                    sync_id
                ))

    def get_sync_history(self, limit: int = 10) -> List[Dict]:
        """Get recent sync history."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT *
                    FROM kb_freshdesk_sync_log
                    ORDER BY started_at DESC
                    LIMIT %s
                """, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def get_qa_count(self) -> int:
        """Get total Q&A pairs count."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM kb_freshdesk_qa")
                return cur.fetchone()[0]

    def test_connection(self) -> Dict:
        """Test Freshdesk API connection."""
        try:
            url = f"{self.base_url}/tickets"
            params = {"per_page": 1}
            resp = requests.get(url, auth=self.auth, headers=self.headers, params=params, timeout=10)
            resp.raise_for_status()

            return {
                'success': True,
                'domain': self.domain,
                'status_code': resp.status_code
            }
        except Exception as e:
            return {
                'success': False,
                'domain': self.domain,
                'error': str(e)
            }

    def get_all_qa_pairs(self, limit: int = None) -> List[Dict]:
        """Get all Q&A pairs from database for export."""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if limit:
                    cur.execute("""
                        SELECT * FROM kb_freshdesk_qa
                        ORDER BY resolved_at DESC
                        LIMIT %s
                    """, (limit,))
                else:
                    cur.execute("""
                        SELECT * FROM kb_freshdesk_qa
                        ORDER BY resolved_at DESC
                    """)
                return [dict(row) for row in cur.fetchall()]

    def export_to_jsonl(self, output_path: str = None, limit: int = None) -> Dict:
        """
        Export all Freshdesk Q&A pairs to JSONL format for Vertex AI RAG.

        Args:
            output_path: Path to output JSONL file. Defaults to RAG_EXPORT_DIR.
            limit: Optional limit on number of records to export.

        Returns:
            Dict with export statistics.
        """
        from .jsonl_formatter import JSONLFormatter
        from pathlib import Path
        from datetime import datetime

        # Get export directory from settings
        export_dir = os.getenv('RAG_EXPORT_DIR', '/var/www/call-recording-system/rag_integration/exports')
        if output_path is None:
            output_path = os.path.join(
                export_dir,
                f"freshdesk_qa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
            )

        # Ensure directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Get all Q&A pairs
        qa_pairs = self.get_all_qa_pairs(limit=limit)
        logger.info(f"Exporting {len(qa_pairs)} Freshdesk Q&A pairs to JSONL")

        # Format and write
        formatter = JSONLFormatter()
        exported = 0
        errors = 0

        with open(output_path, 'w') as f:
            for qa in qa_pairs:
                try:
                    doc = formatter.format_freshdesk_qa(qa)
                    f.write(json.dumps(doc, default=str) + '\n')
                    exported += 1
                except Exception as e:
                    logger.error(f"Error formatting QA {qa.get('qa_id')}: {e}")
                    errors += 1

        logger.info(f"Exported {exported} Q&A pairs to {output_path}")

        return {
            'success': True,
            'exported': exported,
            'errors': errors,
            'output_path': output_path
        }


def get_freshdesk_scraper() -> FreshdeskScraper:
    """Get FreshdeskScraper instance."""
    return FreshdeskScraper()


# CLI for manual sync
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    scraper = FreshdeskScraper()

    # Test connection first
    test = scraper.test_connection()
    print(f"Connection test: {test}")

    if not test['success']:
        print("Connection failed!")
        sys.exit(1)

    # Sync
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    max_tickets = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    print(f"Syncing last {days} days, max {max_tickets} tickets...")
    stats = scraper.sync_tickets(since_days=days, max_tickets=max_tickets)

    print(f"\nSync complete:")
    print(f"  Tickets processed: {stats['tickets_processed']}")
    print(f"  Q&A pairs created: {stats['qa_pairs_created']}")
    print(f"  Q&A pairs updated: {stats['qa_pairs_updated']}")
    print(f"  Errors: {stats['errors']}")

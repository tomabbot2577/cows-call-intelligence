#!/usr/bin/env python3
"""
Parallel Freshdesk Q&A Enrichment using OpenRouter + Gemini 2.0 Flash
Runs 25 parallel processes for fast enrichment.
"""

import os
import sys
import json
import logging
import time
import requests
from datetime import datetime
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

# Setup logging
log_dir = '/var/www/call-recording-system/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/freshdesk_enrich_parallel_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Thread-safe counters
lock = threading.Lock()
stats = {'enriched': 0, 'errors': 0, 'total': 0}


class OpenRouterEnricher:
    """Enrich Q&A using OpenRouter API with Gemini 2.0 Flash."""

    def __init__(self):
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")

        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.model = "google/gemini-2.0-flash-001"  # Gemini 2.0 Flash on OpenRouter

        self.db_url = os.getenv(
            'RAG_DATABASE_URL',
            'postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights'
        )

        # Connection pool for parallel access
        self.db_pool = pool.ThreadedConnectionPool(
            minconn=5,
            maxconn=30,
            dsn=self.db_url
        )

    def get_connection(self):
        return self.db_pool.getconn()

    def release_connection(self, conn):
        self.db_pool.putconn(conn)

    def get_unenriched_qa(self, limit: int = 1000) -> List[Dict]:
        """Get Q&A pairs that haven't been enriched yet."""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, qa_id, ticket_id, question, answer, category, tags,
                           agent_name, requester_email, priority, created_at, resolved_at
                    FROM kb_freshdesk_qa
                    WHERE enriched_at IS NULL
                    ORDER BY resolved_at DESC
                    LIMIT %s
                """, (limit,))
                return [dict(row) for row in cur.fetchall()]
        finally:
            self.release_connection(conn)

    def call_openrouter(self, prompt: str) -> Optional[Dict]:
        """Call OpenRouter API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mainsequence.net",
            "X-Title": "Freshdesk Q&A Enrichment"
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1000
        }

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            text = result['choices'][0]['message']['content'].strip()

            # Clean up JSON response
            if text.startswith('```'):
                text = text.split('\n', 1)[1]
            if text.endswith('```'):
                text = text.rsplit('\n', 1)[0]
            text = text.strip()

            return json.loads(text)

        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            return None

    def enrich_single_qa(self, qa: Dict) -> bool:
        """Enrich a single Q&A pair."""
        prompt = f"""Analyze this support ticket Q&A and provide structured metadata.

QUESTION/PROBLEM:
{qa['question'][:2000]}

ANSWER/SOLUTION:
{qa['answer'][:2000]}

EXISTING CATEGORY: {qa.get('category', 'Unknown')}

Respond with ONLY valid JSON (no markdown, no explanation):
{{
    "summary": "One sentence summary of the issue and resolution",
    "key_topics": ["topic1", "topic2", "topic3"],
    "problem_type": "technical|billing|account|integration|training|general",
    "product_area": "login|reports|data|api|email|calendar|other",
    "customer_sentiment": "frustrated|neutral|satisfied",
    "problem_complexity": "simple|medium|complex",
    "resolution_quality": 1-10,
    "resolution_complete": true or false,
    "follow_up_needed": true or false,
    "knowledge_gap": "Description of any knowledge gap identified, or null",
    "suggested_kb_article": "Title for a KB article based on this, or null"
}}"""

        metadata = self.call_openrouter(prompt)
        if not metadata:
            return False

        # Save to database
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE kb_freshdesk_qa
                    SET
                        ai_summary = %s,
                        ai_topics = %s,
                        ai_problem_type = %s,
                        ai_product_area = %s,
                        ai_sentiment = %s,
                        ai_complexity = %s,
                        ai_resolution_quality = %s,
                        ai_resolution_complete = %s,
                        ai_follow_up_needed = %s,
                        ai_knowledge_gap = %s,
                        ai_suggested_article = %s,
                        enriched_at = NOW()
                    WHERE qa_id = %s
                """, (
                    metadata.get('summary'),
                    metadata.get('key_topics'),
                    metadata.get('problem_type'),
                    metadata.get('product_area'),
                    metadata.get('customer_sentiment'),
                    metadata.get('problem_complexity'),
                    metadata.get('resolution_quality'),
                    metadata.get('resolution_complete'),
                    metadata.get('follow_up_needed'),
                    metadata.get('knowledge_gap'),
                    metadata.get('suggested_kb_article'),
                    qa['qa_id']
                ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"DB error saving {qa['qa_id']}: {e}")
            conn.rollback()
            return False
        finally:
            self.release_connection(conn)

    def process_qa(self, qa: Dict, index: int, total: int):
        """Process a single Q&A (called from thread pool)."""
        global stats
        try:
            success = self.enrich_single_qa(qa)
            with lock:
                if success:
                    stats['enriched'] += 1
                    logger.info(f"[{index}/{total}] Enriched {qa['qa_id']} (ticket #{qa['ticket_id']})")
                else:
                    stats['errors'] += 1
                    logger.warning(f"[{index}/{total}] Failed {qa['qa_id']}")
        except Exception as e:
            with lock:
                stats['errors'] += 1
            logger.error(f"[{index}/{total}] Error {qa['qa_id']}: {e}")

    def run_parallel(self, limit: int = 1000, workers: int = 25):
        """Run enrichment with parallel workers."""
        global stats

        qa_pairs = self.get_unenriched_qa(limit=limit)
        total = len(qa_pairs)
        stats['total'] = total

        logger.info(f"Starting parallel enrichment: {total} Q&A pairs, {workers} workers")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for i, qa in enumerate(qa_pairs, 1):
                future = executor.submit(self.process_qa, qa, i, total)
                futures.append(future)
                # Small delay to avoid rate limiting
                time.sleep(0.05)

            # Wait for all to complete
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Future error: {e}")

        logger.info(f"Enrichment complete: {stats['enriched']} enriched, {stats['errors']} errors")
        return stats


def ensure_columns():
    """Ensure enrichment columns exist."""
    db_url = os.getenv(
        'RAG_DATABASE_URL',
        'postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights'
    )

    with psycopg2.connect(db_url) as conn:
        with conn.cursor() as cur:
            columns = [
                ("ai_summary", "TEXT"),
                ("ai_topics", "TEXT[]"),
                ("ai_problem_type", "VARCHAR(50)"),
                ("ai_product_area", "VARCHAR(50)"),
                ("ai_sentiment", "VARCHAR(20)"),
                ("ai_complexity", "VARCHAR(20)"),
                ("ai_resolution_quality", "INTEGER"),
                ("ai_resolution_complete", "BOOLEAN"),
                ("ai_follow_up_needed", "BOOLEAN"),
                ("ai_knowledge_gap", "TEXT"),
                ("ai_suggested_article", "TEXT"),
                ("enriched_at", "TIMESTAMP"),
            ]

            for col_name, col_type in columns:
                try:
                    cur.execute(f"ALTER TABLE kb_freshdesk_qa ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
                except:
                    pass
            conn.commit()
    logger.info("Columns ensured")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=10000, help='Max Q&A to process')
    parser.add_argument('--workers', type=int, default=25, help='Parallel workers')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Parallel Freshdesk Enrichment (OpenRouter + Gemini 2.0 Flash)")
    logger.info(f"Workers: {args.workers}, Limit: {args.limit}")
    logger.info("=" * 60)

    ensure_columns()

    enricher = OpenRouterEnricher()
    result = enricher.run_parallel(limit=args.limit, workers=args.workers)

    logger.info("=" * 60)
    logger.info(f"DONE: {result}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

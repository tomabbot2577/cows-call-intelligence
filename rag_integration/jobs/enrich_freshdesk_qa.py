#!/usr/bin/env python3
"""
Enrich Freshdesk Q&A with AI-generated metadata using Gemini 2.0 Flash.
Adds: topics, sentiment, complexity, resolution quality, summary, etc.
"""

import os
import sys
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

import psycopg2
from psycopg2.extras import RealDictCursor
import google.generativeai as genai

# Setup logging
log_dir = '/var/www/call-recording-system/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/freshdesk_enrich_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class FreshdeskQAEnricher:
    """Enrich Freshdesk Q&A pairs with AI-generated metadata."""

    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set")

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash-exp')

        self.db_url = os.getenv(
            'RAG_DATABASE_URL',
            'postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights'
        )

    def get_unenriched_qa(self, limit: int = 100) -> List[Dict]:
        """Get Q&A pairs that haven't been enriched yet."""
        with psycopg2.connect(self.db_url) as conn:
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

    def enrich_qa(self, qa: Dict) -> Dict:
        """Use Gemini 2.0 Flash to generate rich metadata for a Q&A pair."""
        prompt = f"""Analyze this support ticket Q&A and provide structured metadata.

QUESTION/PROBLEM:
{qa['question'][:2000]}

ANSWER/SOLUTION:
{qa['answer'][:2000]}

EXISTING CATEGORY: {qa.get('category', 'Unknown')}
EXISTING TAGS: {qa.get('tags', [])}

Respond with ONLY valid JSON (no markdown, no explanation):
{{
    "summary": "One sentence summary of the issue and resolution",
    "key_topics": ["topic1", "topic2", "topic3"],
    "problem_type": "technical|billing|account|integration|training|general",
    "product_area": "login|reports|data|api|email|calendar|other",
    "customer_sentiment": "frustrated|neutral|satisfied",
    "problem_complexity": "simple|medium|complex",
    "resolution_quality": 1-10,
    "resolution_complete": true/false,
    "follow_up_needed": true/false,
    "knowledge_gap": "Description of any knowledge gap identified, or null",
    "suggested_kb_article": "Title for a KB article based on this, or null"
}}"""

        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()

            # Clean up response
            if text.startswith('```'):
                text = text.split('\n', 1)[1]
            if text.endswith('```'):
                text = text.rsplit('\n', 1)[0]
            text = text.strip()

            metadata = json.loads(text)
            return metadata

        except Exception as e:
            logger.error(f"Error enriching QA {qa['qa_id']}: {e}")
            return None

    def save_enrichment(self, qa_id: str, metadata: Dict):
        """Save enrichment metadata to database."""
        with psycopg2.connect(self.db_url) as conn:
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
                    qa_id
                ))
            conn.commit()

    def run(self, limit: int = 100, batch_size: int = 10):
        """Run enrichment on unenriched Q&A pairs."""
        logger.info(f"Starting Freshdesk Q&A enrichment (limit={limit})")

        qa_pairs = self.get_unenriched_qa(limit=limit)
        logger.info(f"Found {len(qa_pairs)} Q&A pairs to enrich")

        enriched = 0
        errors = 0

        for i, qa in enumerate(qa_pairs):
            try:
                logger.info(f"[{i+1}/{len(qa_pairs)}] Enriching {qa['qa_id']}...")

                metadata = self.enrich_qa(qa)
                if metadata:
                    self.save_enrichment(qa['qa_id'], metadata)
                    enriched += 1
                    logger.info(f"  -> {metadata.get('problem_type')} | {metadata.get('ai_complexity')} | Quality: {metadata.get('resolution_quality')}")
                else:
                    errors += 1

                # Rate limit - 0.5s between requests
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error processing {qa['qa_id']}: {e}")
                errors += 1

        logger.info(f"Enrichment complete: {enriched} enriched, {errors} errors")
        return {'enriched': enriched, 'errors': errors}


def ensure_enrichment_columns():
    """Add enrichment columns to kb_freshdesk_qa table if they don't exist."""
    db_url = os.getenv(
        'RAG_DATABASE_URL',
        'postgresql://call_insights_user:REDACTED_DB_PASSWORD@localhost/call_insights'
    )

    with psycopg2.connect(db_url) as conn:
        with conn.cursor() as cur:
            # Add columns if they don't exist
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
                    cur.execute(f"""
                        ALTER TABLE kb_freshdesk_qa
                        ADD COLUMN IF NOT EXISTS {col_name} {col_type}
                    """)
                except Exception as e:
                    logger.warning(f"Column {col_name} might already exist: {e}")

            conn.commit()
            logger.info("Enrichment columns ensured")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Enrich Freshdesk Q&A with AI metadata')
    parser.add_argument('--limit', type=int, default=100, help='Max Q&A pairs to enrich')
    parser.add_argument('--setup', action='store_true', help='Setup database columns only')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Freshdesk Q&A AI Enrichment (Gemini 2.0 Flash)")
    logger.info("=" * 60)

    # Ensure columns exist
    ensure_enrichment_columns()

    if args.setup:
        logger.info("Setup complete. Columns added.")
        return

    # Run enrichment
    enricher = FreshdeskQAEnricher()
    result = enricher.run(limit=args.limit)

    logger.info(f"Done: {result}")


if __name__ == "__main__":
    main()

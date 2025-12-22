#!/usr/bin/env python3
"""
Update Q&A Pairs for Layer 5 records that have empty qa_pairs.

This script re-processes the Q&A extraction for calls that already have
Layer 5 data but are missing the qa_pairs field.

Usage:
    python update_qa_pairs.py --limit 100
    python update_qa_pairs.py --recording-id 3014413617036
"""

import os
import sys
import json
import logging
import time
import argparse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('/var/www/call-recording-system/.env')
sys.path.insert(0, '/var/www/call-recording-system')

import psycopg2
from psycopg2.extras import Json
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'/var/www/call-recording-system/logs/update_qa_pairs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)

DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': os.getenv('PG_PASSWORD', ''),
    'host': 'localhost',
    'port': 5432
}

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class QAPairsUpdater:
    """Update Q&A pairs for existing Layer 5 records."""

    def __init__(self):
        self.model = "google/gemma-3-12b-it:free"
        self.headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://call-insights.local",
            "X-Title": "Call Insights QA Update"
        }

    def _call_llm(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call OpenRouter LLM."""
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers=self.headers,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.3
                },
                timeout=60
            )
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return None

    def extract_qa_pairs(self, transcript: str) -> dict:
        """Extract question-answer pairs from transcript."""
        prompt = f"""Analyze this call transcript and extract question-answer pairs.

Find all questions asked and their answers. Focus on:
1. Customer questions and agent responses
2. Agent questions and customer responses
3. Important clarifications

Return JSON only:
{{
    "pairs": [
        {{"question": "...", "answer": "...", "speaker_question": "customer|agent", "topic": "billing|support|product|other"}}
    ],
    "training_value_score": 0-10,
    "unanswered_questions": ["questions that weren't answered"],
    "total_questions": 0,
    "total_answered": 0
}}

TRANSCRIPT:
{transcript[:3000]}

JSON:"""

        response = self._call_llm(prompt, max_tokens=1500)
        if response:
            try:
                # Clean response
                if "```json" in response:
                    response = response.split("```json")[1].split("```")[0]
                elif "```" in response:
                    response = response.split("```")[1].split("```")[0]
                return json.loads(response.strip())
            except json.JSONDecodeError:
                logger.warning("Failed to parse Q&A response")
        return {"pairs": [], "training_value_score": 0, "total_questions": 0, "total_answered": 0}

    def update_record(self, recording_id: str, qa_pairs: dict) -> bool:
        """Update qa_pairs in call_advanced_metrics."""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            cur.execute("""
                UPDATE call_advanced_metrics
                SET qa_pairs = %s, processed_at = NOW()
                WHERE recording_id = %s
            """, (Json(qa_pairs), recording_id))

            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Database error: {e}")
            return False


def get_records_needing_qa(limit: int = 100):
    """Get records that need Q&A pairs updated."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Get records where qa_pairs is NULL or empty
    cur.execute("""
        SELECT m.recording_id, t.transcript_text
        FROM call_advanced_metrics m
        JOIN transcripts t ON m.recording_id = t.recording_id
        WHERE (m.qa_pairs IS NULL OR m.qa_pairs = '{}' OR m.qa_pairs = 'null')
        AND t.transcript_text IS NOT NULL
        AND LENGTH(t.transcript_text) > 100
        LIMIT %s
    """, (limit,))

    records = cur.fetchall()
    cur.close()
    conn.close()
    return records


def process_batch(limit: int = 100):
    """Process batch of records to update Q&A pairs."""
    updater = QAPairsUpdater()

    records = get_records_needing_qa(limit)
    logger.info(f"Found {len(records)} records needing Q&A pairs update")

    processed = 0
    failed = 0

    for recording_id, transcript in records:
        try:
            logger.info(f"Processing {recording_id}...")
            qa_pairs = updater.extract_qa_pairs(transcript)

            pairs_count = len(qa_pairs.get('pairs', []))
            logger.info(f"  Found {pairs_count} Q&A pairs")

            if updater.update_record(recording_id, qa_pairs):
                processed += 1
                logger.info(f"  Updated {recording_id}")
            else:
                failed += 1

            time.sleep(2)  # Rate limit for free model

        except Exception as e:
            logger.error(f"Error processing {recording_id}: {e}")
            failed += 1

    logger.info(f"\nCompleted: {processed} updated, {failed} failed")
    return processed, failed


def process_single(recording_id: str):
    """Process a single recording."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute("SELECT transcript_text FROM transcripts WHERE recording_id = %s", (recording_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    if not result:
        print(f"Recording {recording_id} not found")
        return

    updater = QAPairsUpdater()
    qa_pairs = updater.extract_qa_pairs(result[0])

    print(f"\nExtracted Q&A pairs for {recording_id}:")
    print(json.dumps(qa_pairs, indent=2))

    if updater.update_record(recording_id, qa_pairs):
        print(f"\nUpdated database for {recording_id}")
    else:
        print(f"\nFailed to update database")


def main():
    parser = argparse.ArgumentParser(description='Update Q&A Pairs for Layer 5')
    parser.add_argument('--limit', type=int, default=100, help='Number of records to process')
    parser.add_argument('--recording-id', type=str, help='Process single recording')
    parser.add_argument('--check', action='store_true', help='Check how many records need updating')
    args = parser.parse_args()

    if args.check:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*)
            FROM call_advanced_metrics
            WHERE qa_pairs IS NULL OR qa_pairs = '{}' OR qa_pairs = 'null'
        """)
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        print(f"Records needing Q&A pairs update: {count}")
        return

    if args.recording_id:
        process_single(args.recording_id)
    else:
        process_batch(limit=args.limit)


if __name__ == '__main__':
    main()

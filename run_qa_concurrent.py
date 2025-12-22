#!/usr/bin/env python3
"""
Concurrent Q&A Pairs Updater - Runs 15 parallel processes.

This script updates Q&A pairs for all Layer 5 records using concurrent processing.
Each process claims records using database locking to prevent duplicates.

Usage:
    python run_qa_concurrent.py --workers 15
"""

import os
import sys
import json
import logging
import time
import argparse
import signal
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import threading
from dotenv import load_dotenv

load_dotenv('/var/www/call-recording-system/.env')
sys.path.insert(0, '/var/www/call-recording-system')

import psycopg2
from psycopg2.extras import Json
import requests

# Global stats
stats_lock = Lock()
stats = {
    'processed': 0,
    'failed': 0,
    'skipped': 0,
    'total_pairs': 0
}
shutdown_flag = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'/var/www/call-recording-system/logs/qa_concurrent_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
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


def signal_handler(signum, frame):
    global shutdown_flag
    logger.info("Shutdown signal received, stopping workers...")
    shutdown_flag = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class QAProcessor:
    """Process Q&A pairs for a single record."""

    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self.model = "google/gemini-2.5-flash"  # Paid Gemini Flash - fast and reliable
        self.backup_model = "google/gemini-2.5-flash-lite"
        self.headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://call-insights.local",
            "X-Title": f"QA Worker {worker_id}"
        }

    def _call_llm(self, prompt: str, max_tokens: int = 1500) -> str:
        """Call OpenRouter LLM with fallback."""
        models = [self.model, self.backup_model]

        for model in models:
            try:
                response = requests.post(
                    OPENROUTER_URL,
                    headers=self.headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": 0.3
                    },
                    timeout=90
                )

                if response.status_code == 200:
                    return response.json()['choices'][0]['message']['content']
                elif response.status_code == 429:
                    logger.warning(f"Rate limited on {model}, waiting...")
                    time.sleep(5)
                else:
                    logger.warning(f"Error {response.status_code} on {model}")

            except Exception as e:
                logger.warning(f"LLM error with {model}: {e}")

        return None

    def extract_qa_pairs(self, transcript: str) -> dict:
        """Extract Q&A pairs from transcript."""
        # Truncate very long transcripts
        transcript_chunk = transcript[:4000] if len(transcript) > 4000 else transcript

        prompt = f"""Analyze this call transcript and extract all question-answer pairs.

Find every question asked and its corresponding answer. Include:
1. Customer questions and agent responses
2. Agent questions and customer responses
3. Clarifying questions
4. Technical questions

Return ONLY valid JSON (no markdown, no explanation):
{{
    "pairs": [
        {{"question": "exact question text", "answer": "answer given", "speaker_q": "customer|agent", "topic": "billing|support|product|general"}}
    ],
    "training_value_score": 1-10,
    "unanswered_questions": [],
    "total_questions": number,
    "total_answered": number
}}

TRANSCRIPT:
{transcript_chunk}"""

        response = self._call_llm(prompt)
        if response:
            try:
                # Clean response
                clean = response.strip()
                if "```json" in clean:
                    clean = clean.split("```json")[1].split("```")[0]
                elif "```" in clean:
                    clean = clean.split("```")[1].split("```")[0]
                clean = clean.strip()

                result = json.loads(clean)
                return result
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error: {e}")

        return {"pairs": [], "training_value_score": 0, "total_questions": 0, "total_answered": 0}


def claim_and_process_batch(worker_id: int, batch_size: int = 20):
    """Claim and process a batch of records atomically."""
    global shutdown_flag, stats

    processor = QAProcessor(worker_id)

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        cur = conn.cursor()

        # Claim records using FOR UPDATE SKIP LOCKED
        cur.execute("""
            WITH claimed AS (
                SELECT m.recording_id
                FROM call_advanced_metrics m
                JOIN transcripts t ON m.recording_id = t.recording_id
                WHERE (m.qa_pairs IS NULL OR m.qa_pairs = '{}' OR m.qa_pairs::text = 'null' OR m.qa_pairs::text = '[]')
                AND t.transcript_text IS NOT NULL
                AND LENGTH(t.transcript_text) > 100
                LIMIT %s
                FOR UPDATE OF m SKIP LOCKED
            )
            SELECT c.recording_id, t.transcript_text
            FROM claimed c
            JOIN transcripts t ON c.recording_id = t.recording_id
        """, (batch_size,))

        records = cur.fetchall()

        if not records:
            conn.commit()
            cur.close()
            conn.close()
            return 0

        logger.info(f"Worker {worker_id}: Claimed {len(records)} records")
        processed_count = 0

        for recording_id, transcript in records:
            if shutdown_flag:
                break

            try:
                qa_pairs = processor.extract_qa_pairs(transcript)
                pairs_count = len(qa_pairs.get('pairs', []))

                # Update the record
                cur.execute("""
                    UPDATE call_advanced_metrics
                    SET qa_pairs = %s, processed_at = NOW()
                    WHERE recording_id = %s
                """, (Json(qa_pairs), recording_id))

                processed_count += 1

                with stats_lock:
                    stats['processed'] += 1
                    stats['total_pairs'] += pairs_count

                logger.info(f"Worker {worker_id}: {recording_id} - {pairs_count} pairs")

                # Small delay between API calls
                time.sleep(1)

            except Exception as e:
                logger.error(f"Worker {worker_id}: Error on {recording_id}: {e}")
                with stats_lock:
                    stats['failed'] += 1

        conn.commit()
        cur.close()
        conn.close()

        return processed_count

    except Exception as e:
        logger.error(f"Worker {worker_id}: Batch error: {e}")
        return 0


def worker_loop(worker_id: int, batch_size: int = 15):
    """Worker loop that processes batches until no more work."""
    global shutdown_flag

    logger.info(f"Worker {worker_id} starting...")
    total_processed = 0

    while not shutdown_flag:
        count = claim_and_process_batch(worker_id, batch_size)
        if count == 0:
            logger.info(f"Worker {worker_id}: No more records, exiting")
            break
        total_processed += count
        time.sleep(0.5)  # Small delay between batches

    logger.info(f"Worker {worker_id} finished. Total processed: {total_processed}")
    return total_processed


def get_pending_count():
    """Get count of records needing Q&A update."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*)
        FROM call_advanced_metrics m
        JOIN transcripts t ON m.recording_id = t.recording_id
        WHERE (m.qa_pairs IS NULL OR m.qa_pairs = '{}' OR m.qa_pairs::text = 'null' OR m.qa_pairs::text = '[]')
        AND t.transcript_text IS NOT NULL
        AND LENGTH(t.transcript_text) > 100
    """)
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


def run_concurrent(num_workers: int = 15):
    """Run concurrent Q&A extraction."""
    global stats, shutdown_flag

    pending = get_pending_count()
    logger.info(f"=" * 60)
    logger.info(f"Q&A PAIRS CONCURRENT UPDATER")
    logger.info(f"=" * 60)
    logger.info(f"Records to process: {pending}")
    logger.info(f"Workers: {num_workers}")
    logger.info(f"Model: google/gemini-flash-1.5")
    logger.info(f"=" * 60)

    if pending == 0:
        logger.info("No records need Q&A extraction!")
        return

    start_time = datetime.now()

    with ThreadPoolExecutor(max_workers=num_workers, thread_name_prefix="QAWorker") as executor:
        futures = []
        for i in range(num_workers):
            future = executor.submit(worker_loop, i + 1, 15)
            futures.append(future)
            time.sleep(0.3)  # Stagger worker starts

        # Wait for all workers
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                logger.error(f"Worker error: {e}")

    elapsed = (datetime.now() - start_time).total_seconds()

    logger.info(f"\n" + "=" * 60)
    logger.info(f"PROCESSING COMPLETE")
    logger.info(f"=" * 60)
    logger.info(f"Total processed: {stats['processed']}")
    logger.info(f"Total failed: {stats['failed']}")
    logger.info(f"Total Q&A pairs extracted: {stats['total_pairs']}")
    logger.info(f"Time elapsed: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
    if stats['processed'] > 0:
        logger.info(f"Average time per record: {elapsed/stats['processed']:.2f} seconds")
        logger.info(f"Average pairs per call: {stats['total_pairs']/stats['processed']:.1f}")


def main():
    parser = argparse.ArgumentParser(description='Concurrent Q&A Pairs Updater')
    parser.add_argument('--workers', type=int, default=15, help='Number of concurrent workers')
    parser.add_argument('--check', action='store_true', help='Check pending count only')
    args = parser.parse_args()

    if args.check:
        count = get_pending_count()
        print(f"Records needing Q&A update: {count}")
        return

    run_concurrent(num_workers=args.workers)


if __name__ == '__main__':
    main()

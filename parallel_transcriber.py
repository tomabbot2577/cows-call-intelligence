#!/usr/bin/env python3
"""
Parallel Salad Transcription Processor
Runs multiple transcription jobs concurrently to speed up processing.
"""

import os
import sys
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv('/var/www/call-recording-system/.env')
sys.path.insert(0, '/var/www/call-recording-system')

import psycopg2
from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'/var/www/call-recording-system/logs/parallel_transcribe_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
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


class ParallelTranscriber:
    """Run multiple Salad transcription jobs in parallel"""

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self.queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        self.processed_dir = Path('/var/www/call-recording-system/data/processed')
        self.failed_dir = Path('/var/www/call-recording-system/data/failed')
        
        # Load metadata
        self.rc_metadata = self._load_metadata()
        logger.info(f"Loaded {len(self.rc_metadata)} metadata records")
        
        # Stats
        self.stats = {'processed': 0, 'failed': 0, 'total_time': 0}

    def _load_metadata(self) -> Dict:
        """Load RingCentral metadata"""
        metadata = {}
        json_file = Path('/var/www/call-recording-system/data/recordings_to_download.json')
        if json_file.exists():
            with open(json_file) as f:
                for rec in json.load(f):
                    rec_id = str(rec.get('id', ''))
                    if rec_id:
                        metadata[rec_id] = rec
        return metadata

    def _get_transcriber(self):
        """Create a new transcriber instance (thread-safe)"""
        return SaladTranscriberEnhanced(
            api_key=os.getenv('SALAD_API_KEY'),
            organization_name=os.getenv('SALAD_ORG_NAME', 'mst'),
            enable_diarization=True,
            enable_summarization=True,
            enable_monitoring=False,  # Disable per-instance monitoring for parallel
            polling_interval=5,  # Slightly longer poll for parallel
            max_wait_time=1800  # 30 min max per job
        )

    def _process_single(self, audio_file: Path) -> Dict:
        """Process a single file (called by thread pool)"""
        recording_id = audio_file.stem
        start_time = time.time()
        
        result = {
            'recording_id': recording_id,
            'success': False,
            'error': None,
            'words': 0,
            'time': 0
        }
        
        try:
            # Get audio URL
            audio_url = f"http://31.97.102.13:8080/audio/{audio_file.name}"
            
            # Get metadata
            meta = self.rc_metadata.get(recording_id, {})
            
            # Create transcriber for this thread
            transcriber = self._get_transcriber()
            
            # Transcribe
            logger.info(f"[{recording_id}] Starting transcription...")
            tx_result = transcriber.transcribe_file(audio_url)
            
            if tx_result and tx_result.text:
                # Parse date
                start_time_str = meta.get('start_time', '')
                call_date, call_time = None, None
                if start_time_str:
                    try:
                        dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        call_date = dt.date()
                        call_time = dt.time()
                    except:
                        pass
                
                # Save to database
                conn = psycopg2.connect(**DB_CONFIG)
                cur = conn.cursor()
                
                cur.execute("SELECT recording_id FROM transcripts WHERE recording_id = %s", (recording_id,))
                exists = cur.fetchone()
                
                if exists:
                    cur.execute("""
                        UPDATE transcripts SET
                            transcript_text = %s, word_count = %s, confidence_score = %s,
                            duration_seconds = %s, call_date = %s, call_time = %s,
                            direction = %s, updated_at = NOW()
                        WHERE recording_id = %s
                    """, (tx_result.text, tx_result.word_count, tx_result.confidence,
                          tx_result.duration_seconds, call_date, call_time,
                          meta.get('direction', 'Unknown'), recording_id))
                else:
                    cur.execute("""
                        INSERT INTO transcripts (recording_id, transcript_text, word_count,
                            confidence_score, duration_seconds, call_date, call_time, direction)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (recording_id, tx_result.text, tx_result.word_count, tx_result.confidence,
                          tx_result.duration_seconds, call_date, call_time,
                          meta.get('direction', 'Unknown')))
                
                conn.commit()
                cur.close()
                conn.close()
                
                # Move file
                audio_file.rename(self.processed_dir / audio_file.name)
                
                result['success'] = True
                result['words'] = tx_result.word_count
                
                logger.info(f"[{recording_id}] SUCCESS: {tx_result.word_count} words")
            else:
                raise Exception("No text returned")
                
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"[{recording_id}] FAILED: {e}")
            try:
                audio_file.rename(self.failed_dir / audio_file.name)
            except:
                pass
        
        result['time'] = time.time() - start_time
        return result

    def process_batch(self, limit: int = 50):
        """Process batch with parallel workers"""
        audio_files = sorted(self.queue_dir.glob('*.mp3'))[:limit]
        
        logger.info(f"Starting parallel processing: {len(audio_files)} files, {self.max_workers} workers")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._process_single, f): f for f in audio_files}
            
            for future in as_completed(futures):
                result = future.result()
                if result['success']:
                    self.stats['processed'] += 1
                else:
                    self.stats['failed'] += 1
        
        total_time = time.time() - start_time
        self.stats['total_time'] = total_time
        
        logger.info(f"\n{'='*50}")
        logger.info(f"BATCH COMPLETE")
        logger.info(f"  Processed: {self.stats['processed']}")
        logger.info(f"  Failed: {self.stats['failed']}")
        logger.info(f"  Total time: {total_time:.1f}s")
        logger.info(f"  Avg per file: {total_time/len(audio_files):.1f}s")
        logger.info(f"  Files/minute: {len(audio_files)/(total_time/60):.1f}")
        logger.info(f"{'='*50}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50, help='Number of files to process')
    parser.add_argument('--workers', type=int, default=3, help='Number of parallel workers')
    args = parser.parse_args()
    
    processor = ParallelTranscriber(max_workers=args.workers)
    processor.process_batch(limit=args.limit)


if __name__ == '__main__':
    main()

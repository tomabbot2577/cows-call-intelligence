#!/usr/bin/env python3
"""
Batch Processor with RingCentral Metadata Integration
Processes recordings with proper call metadata from RingCentral API.
"""

import os
import sys
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv('/var/www/call-recording-system/.env')
sys.path.insert(0, '/var/www/call-recording-system')

from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
from src.storage.enhanced_organizer import EnhancedStorageOrganizer
import psycopg2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'/var/www/call-recording-system/logs/batch_metadata_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)

DB_CONFIG = {
    'dbname': 'call_insights',
    'user': 'call_insights_user',
    'password': 'call_insights_pass',
    'host': 'localhost',
    'port': 5432
}


class MetadataBatchProcessor:
    """Process recordings with RingCentral metadata"""

    def __init__(self, rate_limit: int = 5):
        self.rate_limit = rate_limit
        self.queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        self.processed_dir = Path('/var/www/call-recording-system/data/processed')
        self.failed_dir = Path('/var/www/call-recording-system/data/failed')

        for d in [self.processed_dir, self.failed_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Load RingCentral metadata
        self.rc_metadata = self._load_ringcentral_metadata()
        logger.info(f"Loaded {len(self.rc_metadata)} RingCentral metadata records")

        # Initialize transcriber
        self.transcriber = SaladTranscriberEnhanced(
            api_key=os.getenv('SALAD_API_KEY'),
            organization_name=os.getenv('SALAD_ORG_NAME', 'mst'),
            enable_diarization=True,
            enable_summarization=True,
            enable_monitoring=True
        )

        self.storage = EnhancedStorageOrganizer()
        self.stats = {'processed': 0, 'failed': 0, 'skipped': 0}

    def _load_ringcentral_metadata(self) -> Dict:
        """Load RingCentral metadata from JSON"""
        metadata = {}
        json_file = Path('/var/www/call-recording-system/data/recordings_to_download.json')
        if json_file.exists():
            with open(json_file) as f:
                for rec in json.load(f):
                    rec_id = str(rec.get('id', ''))
                    if rec_id:
                        metadata[rec_id] = rec
        return metadata

    def _get_audio_url(self, audio_file: Path) -> Optional[str]:
        """Get nginx URL for audio file"""
        try:
            import requests
            url = f"http://31.97.102.13:8080/audio/{audio_file.name}"
            response = requests.head(url, timeout=5)
            return url if response.status_code == 200 else None
        except:
            return None

    def _parse_datetime(self, iso_str: str):
        """Parse ISO datetime string"""
        if not iso_str:
            return None, None
        try:
            dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
            return dt.date(), dt.time()
        except:
            return None, None

    def _save_to_database(self, recording_id: str, transcript_text: str, 
                          word_count: int, confidence: float, duration: float,
                          call_date, call_time, direction: str, from_name: str, to_name: str):
        """Save transcript to PostgreSQL"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            # Check if exists
            cur.execute("SELECT recording_id FROM transcripts WHERE recording_id = %s", (recording_id,))
            exists = cur.fetchone()

            if exists:
                cur.execute("""
                    UPDATE transcripts SET
                        transcript_text = %s, word_count = %s, confidence_score = %s,
                        duration_seconds = %s, call_date = %s, call_time = %s,
                        direction = %s, updated_at = NOW()
                    WHERE recording_id = %s
                """, (transcript_text, word_count, confidence, duration, 
                      call_date, call_time, direction, recording_id))
            else:
                cur.execute("""
                    INSERT INTO transcripts (recording_id, transcript_text, word_count, 
                        confidence_score, duration_seconds, call_date, call_time, direction)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (recording_id, transcript_text, word_count, confidence,
                      duration, call_date, call_time, direction))

            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Database error: {e}")
            return False

    def process_recording(self, audio_file: Path) -> bool:
        """Process single recording with metadata"""
        recording_id = audio_file.stem
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing: {recording_id}")

        # Get RingCentral metadata
        rc_meta = self.rc_metadata.get(recording_id, {})
        start_time = rc_meta.get('start_time', '')
        call_date, call_time = self._parse_datetime(start_time)
        direction = rc_meta.get('direction', 'Unknown')
        from_name = rc_meta.get('from', 'Unknown')
        to_name = rc_meta.get('to', 'Unknown')
        duration = rc_meta.get('duration', 0)

        logger.info(f"  Call Date: {call_date}, Direction: {direction}")
        logger.info(f"  From: {from_name}, To: {to_name}")

        try:
            # Get audio URL
            audio_url = self._get_audio_url(audio_file)
            if not audio_url:
                raise Exception("Audio file not accessible via nginx")

            # Transcribe with Salad
            logger.info("  Transcribing with Salad Cloud...")
            result = self.transcriber.transcribe_file(audio_url)

            if not result or not result.text:
                raise Exception("Transcription returned no text")

            logger.info(f"  Transcribed: {result.word_count} words, {result.confidence:.1%} confidence")

            # Save to database
            saved = self._save_to_database(
                recording_id=recording_id,
                transcript_text=result.text,
                word_count=result.word_count,
                confidence=result.confidence,
                duration=result.duration_seconds or duration,
                call_date=call_date,
                call_time=call_time,
                direction=direction,
                from_name=from_name,
                to_name=to_name
            )

            if saved:
                # Move to processed
                audio_file.rename(self.processed_dir / audio_file.name)
                self.stats['processed'] += 1
                logger.info(f"  SUCCESS - saved with metadata")
                return True
            else:
                raise Exception("Failed to save to database")

        except Exception as e:
            logger.error(f"  FAILED: {e}")
            audio_file.rename(self.failed_dir / audio_file.name)
            self.stats['failed'] += 1
            return False

    def process_batch(self, limit: int = 50):
        """Process batch of recordings"""
        audio_files = sorted(self.queue_dir.glob('*.mp3'))[:limit]
        logger.info(f"Processing {len(audio_files)} files...")

        for i, audio_file in enumerate(audio_files, 1):
            logger.info(f"[{i}/{len(audio_files)}]")
            self.process_recording(audio_file)
            
            if i < len(audio_files):
                time.sleep(self.rate_limit)

        logger.info(f"\nCOMPLETE: {self.stats['processed']} processed, {self.stats['failed']} failed")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--rate-limit', type=int, default=5)
    args = parser.parse_args()

    processor = MetadataBatchProcessor(rate_limit=args.rate_limit)
    processor.process_batch(limit=args.limit)


if __name__ == '__main__':
    main()

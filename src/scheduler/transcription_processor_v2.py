#!/usr/bin/env python3
"""
Transcription Processor v2
Processes recordings from audio_queue using call_log metadata
Saves full metadata to transcripts table
"""

import os
import sys
import json
import logging
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, List
import subprocess

sys.path.insert(0, '/var/www/call-recording-system')

from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TranscriptionProcessorV2:
    """
    Transcription processor that uses call_log for complete metadata
    """

    def __init__(self):
        """Initialize the transcription processor"""

        # Database connection
        self.db_url = '" + os.getenv('DATABASE_URL', '')'

        # Initialize Salad transcriber
        self.transcriber = SaladTranscriberEnhanced(
            api_key=os.getenv('SALAD_API_KEY'),
            organization_name=os.getenv('SALAD_ORG_NAME', 'mst'),
            enable_diarization=True,
            enable_summarization=True
        )

        # Paths
        self.queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        self.processed_dir = Path('/var/www/call-recording-system/data/processed')
        self.failed_dir = Path('/var/www/call-recording-system/data/failed')

        # Audio server URL (nginx serves files)
        self.audio_base_url = os.getenv('AUDIO_SERVER_URL', 'http://31.97.102.13:8080/audio')

        # Create directories
        for d in [self.queue_dir, self.processed_dir, self.failed_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Stats
        self.stats = {'processed': 0, 'failed': 0, 'skipped': 0}

        logger.info("TranscriptionProcessorV2 initialized")

    def _get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.db_url)

    def get_pending_recordings(self, limit: int = 10) -> List[Dict]:
        """
        Get recordings that need transcription:
        - Has audio file in queue
        - Has entry in call_log with has_recording=true
        - Not yet in transcripts table
        """
        # Get files in queue
        queue_files = {f.stem: f for f in self.queue_dir.glob('*.mp3')}
        if not queue_files:
            return []

        conn = self._get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Find call_log entries for queued files that aren't transcribed yet
                placeholders = ','.join(['%s'] * len(queue_files))
                cur.execute(f"""
                    SELECT cl.*
                    FROM call_log cl
                    WHERE cl.ringcentral_id IN ({placeholders})
                    AND cl.has_recording = TRUE
                    AND cl.is_transcribed = FALSE
                    AND NOT EXISTS (
                        SELECT 1 FROM transcripts t
                        WHERE t.recording_id = cl.ringcentral_id
                    )
                    LIMIT %s
                """, list(queue_files.keys()) + [limit])

                results = cur.fetchall()

                # Add file path to each result
                for r in results:
                    r['audio_path'] = str(queue_files.get(r['ringcentral_id']))

                return results

        finally:
            conn.close()

    def get_call_metadata(self, ringcentral_id: str) -> Optional[Dict]:
        """Get full metadata from call_log"""
        conn = self._get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM call_log WHERE ringcentral_id = %s
                """, (ringcentral_id,))
                return cur.fetchone()
        finally:
            conn.close()

    def save_transcript(self, recording_id: str, transcription: Dict, call_metadata: Dict) -> bool:
        """
        Save transcript with full metadata from call_log
        """
        conn = self._get_db_connection()
        try:
            with conn.cursor() as cur:
                # Check if already exists
                cur.execute("SELECT 1 FROM transcripts WHERE recording_id = %s", (recording_id,))
                if cur.fetchone():
                    logger.info(f"Transcript {recording_id} already exists, skipping")
                    return False

                # Extract data from call_log
                start_time = call_metadata.get('start_time')
                call_date = start_time.date() if start_time else None
                call_time = start_time.time() if start_time else None

                # Insert transcript with all metadata
                cur.execute("""
                    INSERT INTO transcripts (
                        recording_id,
                        ringcentral_id,
                        transcript_text,
                        transcript_segments,
                        word_count,
                        confidence_score,
                        language,
                        call_date,
                        call_time,
                        duration_seconds,
                        from_number,
                        to_number,
                        from_extension,
                        to_extension,
                        direction,
                        salad_job_id,
                        salad_processing_time,
                        created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                """, (
                    recording_id,
                    call_metadata.get('ringcentral_id'),
                    transcription.get('text', ''),
                    json.dumps(transcription.get('segments', [])),
                    transcription.get('word_count', 0),
                    transcription.get('confidence', 0),
                    transcription.get('language', 'en'),
                    call_date,
                    call_time,
                    call_metadata.get('duration_seconds', 0),
                    call_metadata.get('from_phone_number'),
                    call_metadata.get('to_phone_number'),
                    call_metadata.get('from_extension_number'),
                    call_metadata.get('to_extension_number'),
                    call_metadata.get('direction'),
                    transcription.get('job_id'),
                    transcription.get('processing_time_seconds', 0)
                ))

                # Update call_log to mark as transcribed
                cur.execute("""
                    UPDATE call_log
                    SET is_transcribed = TRUE,
                        transcription_time = NOW()
                    WHERE ringcentral_id = %s
                """, (recording_id,))

                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Error saving transcript {recording_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def process_recording(self, call_data: Dict) -> bool:
        """
        Process a single recording through transcription
        """
        recording_id = call_data['ringcentral_id']
        audio_path = Path(call_data['audio_path'])

        logger.info(f"Processing {recording_id}")

        # Check audio file
        if not audio_path.exists():
            logger.error(f"Audio file not found: {audio_path}")
            self.stats['failed'] += 1
            return False

        # Check file size (skip tiny files that are errors)
        file_size = audio_path.stat().st_size
        if file_size < 1000:  # Less than 1KB is likely an error
            logger.warning(f"Skipping {recording_id} - file too small ({file_size} bytes)")
            # Move to failed
            audio_path.rename(self.failed_dir / audio_path.name)
            self.stats['skipped'] += 1
            return False

        try:
            # Get audio URL for Salad
            audio_url = f"{self.audio_base_url}/{audio_path.name}"

            # Transcribe
            logger.info(f"Transcribing {recording_id} ({file_size:,} bytes)")
            result = self.transcriber.transcribe_file(audio_url)

            if not result or not result.text:
                logger.error(f"Transcription failed for {recording_id}")
                audio_path.rename(self.failed_dir / audio_path.name)
                self.stats['failed'] += 1
                return False

            # Convert result to dict
            transcription = {
                'text': result.text,
                'confidence': result.confidence,
                'language': result.language,
                'word_count': result.word_count,
                'duration_seconds': result.duration_seconds,
                'processing_time_seconds': result.processing_time_seconds,
                'segments': result.segments,
                'job_id': result.job_id
            }

            # Save to database
            if self.save_transcript(recording_id, transcription, call_data):
                logger.info(f"Saved transcript for {recording_id}")

                # Securely delete audio file
                try:
                    subprocess.run(['shred', '-u', str(audio_path)], check=True, capture_output=True)
                    logger.info(f"Securely deleted {audio_path.name}")
                except:
                    # Fall back to regular delete
                    audio_path.unlink(missing_ok=True)

                self.stats['processed'] += 1
                return True
            else:
                self.stats['skipped'] += 1
                return False

        except Exception as e:
            logger.error(f"Error processing {recording_id}: {e}")
            if audio_path.exists():
                audio_path.rename(self.failed_dir / audio_path.name)
            self.stats['failed'] += 1
            return False

    def process_queue(self, limit: int = 10, rate_limit: float = 5.0) -> Dict:
        """
        Process recordings from the queue
        """
        start_time = time.time()
        logger.info(f"Starting queue processing (limit: {limit})")

        self.stats = {'processed': 0, 'failed': 0, 'skipped': 0}

        # Get pending recordings
        recordings = self.get_pending_recordings(limit)
        logger.info(f"Found {len(recordings)} recordings to process")

        for recording in recordings:
            self.process_recording(recording)
            time.sleep(rate_limit)  # Rate limit

        elapsed = time.time() - start_time
        summary = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds': round(elapsed, 2),
            'recordings_found': len(recordings),
            **self.stats
        }

        logger.info(f"Queue processing complete: {summary}")

        # Save summary
        summary_file = Path('/var/www/call-recording-system/data/scheduler/transcription_summary_v2.json')
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        return summary

    def get_status(self) -> Dict:
        """Get queue status"""
        queue_files = list(self.queue_dir.glob('*.mp3'))

        conn = self._get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_calls,
                        COUNT(*) FILTER (WHERE has_recording) as with_recordings,
                        COUNT(*) FILTER (WHERE is_transcribed) as transcribed,
                        COUNT(*) FILTER (WHERE has_recording AND NOT is_transcribed) as pending
                    FROM call_log
                """)
                stats = cur.fetchone()

                cur.execute("SELECT COUNT(*) as count FROM transcripts")
                transcript_count = cur.fetchone()['count']

                return {
                    'audio_queue': len(queue_files),
                    'call_log_total': stats['total_calls'],
                    'with_recordings': stats['with_recordings'],
                    'transcribed': stats['transcribed'],
                    'pending_transcription': stats['pending'],
                    'transcripts_table': transcript_count
                }
        finally:
            conn.close()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Transcription Processor v2')
    parser.add_argument('--limit', type=int, default=10, help='Max recordings to process')
    parser.add_argument('--rate-limit', type=float, default=5.0, help='Seconds between recordings')
    parser.add_argument('--status', action='store_true', help='Show status only')

    args = parser.parse_args()

    processor = TranscriptionProcessorV2()

    if args.status:
        status = processor.get_status()
        print("\n=== Transcription Queue Status ===")
        for key, value in status.items():
            print(f"  {key}: {value}")
        print()
    else:
        summary = processor.process_queue(limit=args.limit, rate_limit=args.rate_limit)
        print(f"\nProcessing complete:")
        print(f"  Processed: {summary['processed']}")
        print(f"  Failed: {summary['failed']}")
        print(f"  Skipped: {summary['skipped']}")
        print(f"  Time: {summary['elapsed_seconds']}s")


if __name__ == '__main__':
    main()

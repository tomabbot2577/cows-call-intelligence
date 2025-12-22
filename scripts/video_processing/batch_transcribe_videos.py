#!/usr/bin/env python3
"""
Batch Video Transcription with Parallel Processing

Transcribes all RingCentral Video recordings that need transcription.
Uses concurrent workers for faster processing.

Usage:
    python scripts/video_processing/batch_transcribe_videos.py [--workers N] [--limit N]
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BatchVideoTranscriber:
    """Batch transcription processor with parallel workers."""

    def __init__(self, max_workers: int = 3):
        """
        Initialize batch transcriber.

        Args:
            max_workers: Number of concurrent transcription workers
        """
        self.max_workers = max_workers

        # Database connection - use RAG_DATABASE_URL for video_meetings table
        db_url = os.getenv('RAG_DATABASE_URL')
        if not db_url:
            raise ValueError("RAG_DATABASE_URL not set")

        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)

        # Track temp files for cleanup
        self.temp_files = []

        # Stats
        self.stats = {
            'total': 0,
            'completed': 0,
            'failed': 0,
            'skipped': 0,
            'no_recording': 0
        }

        logger.info(f"BatchVideoTranscriber initialized with {max_workers} workers")

    def get_pending_recordings(self, limit: int = 100) -> list:
        """
        Get recordings that need transcription.

        Args:
            limit: Maximum number to return

        Returns:
            List of (id, recording_id, title) tuples
        """
        with self.Session() as session:
            result = session.execute(
                text("""
                    SELECT id,
                           raw_ringcentral_data->>'id' as rec_id,
                           title
                    FROM video_meetings
                    WHERE source = 'ringcentral'
                      AND transcript_text IS NULL
                      AND (transcription_status IS NULL OR transcription_status != 'failed')
                      AND raw_ringcentral_data IS NOT NULL
                    ORDER BY start_time DESC NULLS LAST
                    LIMIT :limit
                """),
                {'limit': limit}
            )
            return result.fetchall()

    def transcribe_single(self, meeting_id: int, recording_id: str, title: str) -> dict:
        """
        Transcribe a single recording.

        Args:
            meeting_id: Database ID
            recording_id: RingCentral recording ID
            title: Meeting title for logging

        Returns:
            Result dict with status
        """
        from src.ringcentral.video_transcription_handler import VideoTranscriptionHandler

        result = {
            'meeting_id': meeting_id,
            'recording_id': recording_id,
            'title': title,
            'status': 'pending',
            'error': None
        }

        try:
            # Create handler with its own DB session
            with self.Session() as session:
                handler = VideoTranscriptionHandler(db_session=session)

                logger.info(f"[{meeting_id}] Starting transcription: {title[:50]}...")

                # Download and transcribe
                transcription = handler.transcribe_video_meeting(
                    meeting_id=meeting_id,
                    recording_id=recording_id
                )

                if transcription:
                    result['status'] = 'completed'
                    result['word_count'] = transcription.get('word_count', 0)
                    logger.info(f"[{meeting_id}] Completed: {result['word_count']} words")
                else:
                    result['status'] = 'failed'
                    result['error'] = 'Transcription returned None'
                    logger.warning(f"[{meeting_id}] Failed: No transcription result")

        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
            logger.error(f"[{meeting_id}] Error: {e}")

            # Update status in DB
            try:
                with self.Session() as session:
                    session.execute(
                        text("""
                            UPDATE video_meetings
                            SET transcription_status = 'failed',
                                updated_at = NOW()
                            WHERE id = :meeting_id
                        """),
                        {'meeting_id': meeting_id}
                    )
                    session.commit()
            except:
                pass

        return result

    def process_batch(self, limit: int = 100) -> dict:
        """
        Process batch of recordings with parallel workers.

        Args:
            limit: Maximum number to process

        Returns:
            Summary stats
        """
        # Get pending recordings
        recordings = self.get_pending_recordings(limit)
        self.stats['total'] = len(recordings)

        if not recordings:
            logger.info("No pending recordings to process")
            return self.stats

        logger.info(f"Found {len(recordings)} recordings to process with {self.max_workers} workers")

        # Process with thread pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all jobs
            future_to_recording = {
                executor.submit(
                    self.transcribe_single,
                    meeting_id,
                    recording_id,
                    title or 'Untitled'
                ): (meeting_id, recording_id, title)
                for meeting_id, recording_id, title in recordings
            }

            # Process completed jobs
            for future in as_completed(future_to_recording):
                meeting_id, recording_id, title = future_to_recording[future]

                try:
                    result = future.result()

                    if result['status'] == 'completed':
                        self.stats['completed'] += 1
                    elif result['status'] == 'failed':
                        self.stats['failed'] += 1
                    else:
                        self.stats['skipped'] += 1

                except Exception as e:
                    logger.error(f"[{meeting_id}] Unexpected error: {e}")
                    self.stats['failed'] += 1

                # Rate limiting between completions
                time.sleep(2)

        return self.stats

    def show_progress(self):
        """Show current progress stats."""
        total = self.stats['total']
        done = self.stats['completed'] + self.stats['failed'] + self.stats['skipped']
        pct = (done / total * 100) if total > 0 else 0

        logger.info(f"Progress: {done}/{total} ({pct:.1f}%) - "
                   f"Completed: {self.stats['completed']}, "
                   f"Failed: {self.stats['failed']}, "
                   f"Skipped: {self.stats['skipped']}")


def main():
    parser = argparse.ArgumentParser(description='Batch transcribe video recordings')
    parser.add_argument('--workers', type=int, default=3,
                        help='Number of parallel workers (default: 3)')
    parser.add_argument('--limit', type=int, default=100,
                        help='Maximum recordings to process (default: 100)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be processed without transcribing')

    args = parser.parse_args()

    print("=" * 60)
    print("Batch Video Transcription")
    print(f"Workers: {args.workers}")
    print(f"Limit: {args.limit}")
    print("=" * 60)

    transcriber = BatchVideoTranscriber(max_workers=args.workers)

    if args.dry_run:
        recordings = transcriber.get_pending_recordings(args.limit)
        print(f"\nWould process {len(recordings)} recordings:")
        for meeting_id, recording_id, title in recordings[:10]:
            print(f"  [{meeting_id}] {title[:50]}...")
        if len(recordings) > 10:
            print(f"  ... and {len(recordings) - 10} more")
        return

    # Process batch
    start_time = time.time()
    stats = transcriber.process_batch(limit=args.limit)
    elapsed = time.time() - start_time

    print("\n" + "=" * 60)
    print("TRANSCRIPTION COMPLETE")
    print("=" * 60)
    print(f"Total: {stats['total']}")
    print(f"Completed: {stats['completed']}")
    print(f"Failed: {stats['failed']}")
    print(f"Skipped: {stats['skipped']}")
    print(f"Time: {elapsed:.1f} seconds")
    print("=" * 60)


if __name__ == '__main__':
    main()

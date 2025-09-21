#!/usr/bin/env python3
"""
Final Batch Processor for Queue
Processes all downloaded recordings with proper rate limiting and database updates

SALAD API RATE LIMITS:
- Official limit: 240 requests per minute (4 requests/second)
- Safe rate: 15 seconds between requests = 4 requests/minute
- Processing speed: ~5x real-time (12min audio processes in ~2.4min)
- Max file duration: 3 hours
- Max file size: 100MB for temporary uploads
"""

import os
import sys
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv('/var/www/call-recording-system/.env')

sys.path.insert(0, '/var/www/call-recording-system')

from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
from src.storage.google_drive import GoogleDriveManager
from src.storage.enhanced_organizer import EnhancedStorageOrganizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'/var/www/call-recording-system/logs/batch_processing_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)


class QueueBatchProcessor:
    """Process all recordings in the queue with rate limiting and database tracking"""

    def __init__(self, rate_limit_seconds: int = 3):
        """
        Initialize the batch processor

        Args:
            rate_limit_seconds: Seconds to wait between each transcription
                               Salad API limit: 240 requests/minute = 4/second
                               Default 3s gives us ~20 requests/minute (safe with headroom)
                               For max speed: 0.26s = 230 requests/minute
        """
        self.rate_limit = rate_limit_seconds

        # Initialize components
        logger.info("🚀 Initializing Batch Queue Processor...")

        self.transcriber = SaladTranscriberEnhanced(
            api_key=os.getenv('SALAD_API_KEY'),
            organization_name=os.getenv('SALAD_ORG_NAME', 'mst'),
            enable_diarization=True,
            enable_summarization=True,
            enable_monitoring=True
        )

        self.drive_manager = GoogleDriveManager()
        self.storage_organizer = EnhancedStorageOrganizer()

        # Paths
        self.queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        self.processed_dir = Path('/var/www/call-recording-system/data/processed')
        self.failed_dir = Path('/var/www/call-recording-system/data/failed')

        # Create directories
        for dir_path in [self.processed_dir, self.failed_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # Initialize statistics
        self.stats = {
            'total_files': 0,
            'processed': 0,
            'failed': 0,
            'skipped': 0,
            'google_drive_uploaded': 0,
            'start_time': datetime.now().isoformat(),
            'errors': []
        }

        # Load progress state
        self.state_file = Path('/var/www/call-recording-system/data/batch_progress.json')
        self.processed_ids = self._load_progress()

        logger.info(f"✅ Processor initialized with {self.rate_limit}s rate limit")
        logger.info(f"📊 Previously processed: {len(self.processed_ids)} recordings")

    def _load_progress(self) -> set:
        """Load list of already processed recordings"""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                data = json.load(f)
                return set(data.get('processed_ids', []))
        return set()

    def _save_progress(self):
        """Save current progress"""
        with open(self.state_file, 'w') as f:
            json.dump({
                'processed_ids': list(self.processed_ids),
                'stats': self.stats,
                'last_update': datetime.now().isoformat()
            }, f, indent=2)

    def _update_database(self, recording_id: str, status: str,
                        transcription_data: Optional[Dict] = None,
                        google_drive_id: Optional[str] = None,
                        error_message: Optional[str] = None):
        """
        Update database with recording status

        For now, we'll track in a JSON file since database isn't fully configured
        """
        db_file = Path('/var/www/call-recording-system/data/recordings_database.json')

        # Load existing data
        if db_file.exists():
            with open(db_file, 'r') as f:
                db_data = json.load(f)
        else:
            db_data = {}

        # Update entry
        db_data[recording_id] = {
            'recording_id': recording_id,
            'status': status,
            'processed_at': datetime.now().isoformat(),
            'google_drive_id': google_drive_id,
            'word_count': transcription_data.get('word_count') if transcription_data else None,
            'confidence': transcription_data.get('confidence') if transcription_data else None,
            'error_message': error_message
        }

        # Save
        with open(db_file, 'w') as f:
            json.dump(db_data, f, indent=2)

    def process_single_recording(self, audio_file: Path) -> bool:
        """
        Process a single recording through the complete pipeline

        Returns:
            True if successful, False otherwise
        """
        recording_id = audio_file.stem

        # Check if already processed
        if recording_id in self.processed_ids:
            logger.info(f"⏭️ Skipping {recording_id} - already processed")
            self.stats['skipped'] += 1
            return True

        logger.info(f"\n{'='*60}")
        logger.info(f"📞 Processing: {recording_id}")
        logger.info(f"📁 File: {audio_file.name} ({audio_file.stat().st_size:,} bytes)")

        try:
            # Step 1: Get URL for audio file
            logger.info("📤 Preparing audio URL for transcription...")
            audio_url = self._get_audio_url(audio_file)

            if not audio_url:
                raise Exception("Failed to create audio URL")

            # Step 2: Transcribe with Salad
            logger.info("🎙️ Starting transcription with Salad Cloud...")
            transcription_result = self.transcriber.transcribe_file(audio_url)

            if not transcription_result or not transcription_result.text:
                raise Exception("Transcription returned no text")

            logger.info(f"✅ Transcribed: {transcription_result.word_count} words, "
                       f"confidence: {transcription_result.confidence:.2%}")

            # Step 3: Prepare metadata
            call_metadata = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'time': datetime.now().strftime('%H:%M:%S'),
                'duration': transcription_result.duration_seconds,
                'direction': 'unknown',
                'from': {'number': 'unknown', 'name': ''},
                'to': {'number': 'unknown', 'name': ''},
                'file_size': audio_file.stat().st_size
            }

            # Convert transcription to dict
            transcription_dict = {
                'text': transcription_result.text,
                'confidence': transcription_result.confidence,
                'language': transcription_result.language,
                'language_probability': transcription_result.language_probability,
                'word_count': transcription_result.word_count,
                'duration_seconds': transcription_result.duration_seconds,
                'processing_time_seconds': transcription_result.processing_time_seconds,
                'segments': transcription_result.segments,
                'metadata': transcription_result.metadata,
                'timestamps': transcription_result.timestamps,
                'job_id': transcription_result.job_id
            }

            # Step 4: Upload transcription JSON to Google Drive
            logger.info("☁️ Uploading transcription to Google Drive...")
            try:
                # Create transcription data dictionary
                transcription_data = {
                    'recording_id': recording_id,
                    'transcription': transcription_dict,
                    'call_metadata': call_metadata,
                    'processed_at': datetime.now().isoformat()
                }

                # Upload JSON to Google Drive
                google_drive_id = self.drive_manager.upload_json(
                    data=transcription_data,
                    file_name=f"{recording_id}_transcription.json"
                )

                if google_drive_id:
                    logger.info(f"✅ Google Drive ID: {google_drive_id}")
                    self.stats['google_drive_uploaded'] += 1
                else:
                    logger.warning("⚠️ Google Drive upload failed, continuing anyway")
                    google_drive_id = None
            except Exception as e:
                logger.warning(f"⚠️ Google Drive error: {e}, continuing anyway")
                google_drive_id = None

            # Step 5: Save with enhanced organizer
            logger.info("💾 Saving in dual format (JSON + Markdown)...")
            saved_paths = self.storage_organizer.save_transcription(
                recording_id=recording_id,
                transcription_result=transcription_dict,
                call_metadata=call_metadata,
                google_drive_id=google_drive_id
            )

            logger.info(f"✅ Saved: {saved_paths['json']}")

            # Step 6: Update database
            self._update_database(
                recording_id,
                status='completed',
                transcription_data=transcription_dict,
                google_drive_id=google_drive_id
            )

            # Step 7: Move audio to processed
            processed_path = self.processed_dir / audio_file.name
            audio_file.rename(processed_path)
            logger.info(f"📦 Moved to processed: {processed_path.name}")

            # Update stats
            self.stats['processed'] += 1
            self.processed_ids.add(recording_id)
            self._save_progress()

            logger.info(f"✅ Successfully processed {recording_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error processing {recording_id}: {e}")

            # Update database with error
            self._update_database(
                recording_id,
                status='failed',
                error_message=str(e)[:500]
            )

            # Move to failed directory
            failed_path = self.failed_dir / audio_file.name
            audio_file.rename(failed_path)

            # Update stats
            self.stats['failed'] += 1
            self.stats['errors'].append({
                'recording_id': recording_id,
                'error': str(e)[:200],
                'timestamp': datetime.now().isoformat()
            })

            self._save_progress()
            return False

    def _get_audio_url(self, audio_file: Path) -> Optional[str]:
        """
        Get public URL for audio file via nginx server

        Audio files are served via nginx at port 8080
        Accessible at: http://SERVER_IP:8080/audio/filename.mp3
        """
        try:
            # Get server IP (or use configured URL)
            server_ip = "31.97.102.13"  # Your server's public IP
            file_name = audio_file.name

            # Construct the public URL
            audio_url = f"http://{server_ip}:8080/audio/{file_name}"

            # Verify the file is accessible
            import requests
            response = requests.head(audio_url, timeout=5)

            if response.status_code == 200:
                logger.info(f"✅ Audio file accessible at: {audio_url}")
                return audio_url
            else:
                logger.error(f"Audio file not accessible: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Failed to verify audio URL: {e}")
            return None

    def process_batch(self, limit: int = 50):
        """
        Process a batch of recordings

        Args:
            limit: Maximum number to process in this batch
        """
        logger.info("\n" + "="*80)
        logger.info("🚀 STARTING BATCH PROCESSING")
        logger.info(f"📊 Settings: Limit={limit}, Rate limit={self.rate_limit}s")
        logger.info("="*80)

        # Get audio files
        audio_files = sorted(self.queue_dir.glob('*.mp3'))[:limit]
        self.stats['total_files'] = len(audio_files)

        logger.info(f"📁 Found {len(audio_files)} files to process")

        start_time = time.time()

        for idx, audio_file in enumerate(audio_files, 1):
            logger.info(f"\n[{idx}/{len(audio_files)}] Processing...")

            # Process the recording
            success = self.process_single_recording(audio_file)

            # Rate limiting - wait between files
            if idx < len(audio_files):  # Don't wait after last file
                logger.info(f"⏰ Rate limiting: waiting {self.rate_limit}s before next file...")
                time.sleep(self.rate_limit)

            # Show progress every 5 files
            if idx % 5 == 0:
                elapsed = time.time() - start_time
                rate = idx / (elapsed / 60) if elapsed > 0 else 0
                eta = (len(audio_files) - idx) * (elapsed / idx) if idx > 0 else 0

                logger.info("\n" + "📊 PROGRESS UPDATE " + "="*40)
                logger.info(f"Processed: {self.stats['processed']}/{idx}")
                logger.info(f"Failed: {self.stats['failed']}")
                logger.info(f"Skipped: {self.stats['skipped']}")
                logger.info(f"Rate: {rate:.1f} files/min")
                logger.info(f"ETA: {eta/60:.1f} minutes")
                logger.info("="*60)

        # Final summary
        elapsed_total = time.time() - start_time
        self.stats['end_time'] = datetime.now().isoformat()
        self.stats['elapsed_seconds'] = elapsed_total

        logger.info("\n" + "="*80)
        logger.info("✅ BATCH PROCESSING COMPLETE")
        logger.info("="*80)
        logger.info(f"Total processed: {self.stats['processed']}")
        logger.info(f"Failed: {self.stats['failed']}")
        logger.info(f"Skipped: {self.stats['skipped']}")
        logger.info(f"Google Drive uploads: {self.stats['google_drive_uploaded']}")
        logger.info(f"Time elapsed: {elapsed_total/60:.1f} minutes")
        logger.info(f"Average time per file: {elapsed_total/len(audio_files):.1f}s")

        # Save final stats
        self._save_progress()

        # Save summary report
        summary_file = Path('/var/www/call-recording-system/data/batch_summary_final.json')
        with open(summary_file, 'w') as f:
            json.dump(self.stats, f, indent=2)

        logger.info(f"\n📄 Summary saved to: {summary_file}")

        return self.stats


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Process recording queue in batches')
    parser.add_argument('--limit', type=int, default=50,
                       help='Number of recordings to process (default: 50)')
    parser.add_argument('--rate-limit', type=int, default=3,
                       help='Seconds between recordings - Salad limit: 240/min (default: 3s = ~20/min)')
    parser.add_argument('--status', action='store_true',
                       help='Show queue status only')

    args = parser.parse_args()

    if args.status:
        # Show status
        queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        processed_dir = Path('/var/www/call-recording-system/data/processed')
        failed_dir = Path('/var/www/call-recording-system/data/failed')

        queue_count = len(list(queue_dir.glob('*.mp3')))
        processed_count = len(list(processed_dir.glob('*.mp3')))
        failed_count = len(list(failed_dir.glob('*.mp3')))

        print("\n" + "="*60)
        print("📊 QUEUE STATUS")
        print("="*60)
        print(f"In Queue: {queue_count} recordings")
        print(f"Processed: {processed_count} recordings")
        print(f"Failed: {failed_count} recordings")
        print(f"Total: {queue_count + processed_count + failed_count} recordings")

        # Check progress file
        state_file = Path('/var/www/call-recording-system/data/batch_progress.json')
        if state_file.exists():
            with open(state_file, 'r') as f:
                progress = json.load(f)
            print(f"\nLast batch:")
            print(f"  Processed: {progress['stats'].get('processed', 0)}")
            print(f"  Last update: {progress.get('last_update', 'N/A')}")
        print("="*60)
    else:
        # Process batch
        processor = QueueBatchProcessor(rate_limit_seconds=args.rate_limit)
        stats = processor.process_batch(limit=args.limit)

        print(f"\n✅ Batch complete: {stats['processed']} processed, {stats['failed']} failed")


if __name__ == '__main__':
    main()
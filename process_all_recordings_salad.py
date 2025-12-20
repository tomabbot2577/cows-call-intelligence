#!/usr/bin/env python3
"""
Process ALL 1,461 recordings through Salad Cloud
High-performance batch processor with proper error handling
"""

import os
import sys
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced

# Load environment
load_dotenv('/var/www/call-recording-system/.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/www/call-recording-system/logs/salad_batch.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SaladBatchProcessor:
    def __init__(self, batch_size=20, max_workers=5):
        """Initialize the batch processor"""
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.transcriber = SaladTranscriberEnhanced(
            engine='full',
            language='en-US',
            enable_diarization=True,
            enable_summarization=True,
            enable_monitoring=True
        )

        # Stats tracking
        self.stats = {
            'total': 0,
            'processed': 0,
            'succeeded': 0,
            'failed': 0,
            'skipped': 0,
            'start_time': datetime.now()
        }
        self.lock = threading.Lock()

    def process_file(self, audio_path: Path) -> dict:
        """Process a single audio file"""
        recording_id = audio_path.stem

        try:
            # Check if already transcribed
            transcript_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
            year = datetime.now().strftime('%Y')
            month = datetime.now().strftime('%m')
            day = datetime.now().strftime('%d')

            output_file = transcript_dir / year / month / day / f"{recording_id}.json"

            if output_file.exists():
                logger.info(f"⏭️  Skipping {recording_id} - already transcribed")
                return {'status': 'skipped', 'recording_id': recording_id}

            # Convert to HTTP URL for Salad Cloud
            # Nginx is serving at http://31.97.102.13:8080/audio/
            audio_url = f"http://31.97.102.13:8080/audio/{recording_id}.mp3"

            # Transcribe with Salad Cloud
            logger.info(f"🎤 Processing: {recording_id}")
            result = self.transcriber.transcribe_file(audio_url)

            if result and not result.error:
                # Save transcript using the transcriber's storage methods
                # The transcriber handles all the enhanced metadata automatically

                # Get the full transcript data from the result
                transcript_data = result.to_dict()

                # Save to our output location as well
                output_file.parent.mkdir(parents=True, exist_ok=True)
                with open(output_file, 'w') as f:
                    json.dump(transcript_data, f, indent=2)

                logger.info(f"✅ Completed: {recording_id}")
                logger.info(f"   Words: {result.word_count}, Duration: {result.duration_seconds:.1f}s")

                # Check if summary is in metadata
                if result.metadata and result.metadata.get('summary'):
                    logger.info(f"   Summary generated: {len(result.metadata['summary'])} chars")
                if result.metadata and result.metadata.get('key_issues'):
                    logger.info(f"   Key issues: {', '.join(result.metadata['key_issues'][:3])}")

                return {'status': 'succeeded', 'recording_id': recording_id, 'output': str(output_file)}
            else:
                error_msg = result.error if result and result.error else 'Invalid result'
                logger.error(f"❌ Failed: {recording_id} - {error_msg}")
                return {'status': 'failed', 'recording_id': recording_id, 'error': error_msg}

        except Exception as e:
            logger.error(f"❌ Error processing {recording_id}: {e}")
            return {'status': 'failed', 'recording_id': recording_id, 'error': str(e)}

    def update_stats(self, result: dict):
        """Update processing statistics"""
        with self.lock:
            self.stats['processed'] += 1
            status = result.get('status')
            if status == 'succeeded':
                self.stats['succeeded'] += 1
            elif status == 'failed':
                self.stats['failed'] += 1
            elif status == 'skipped':
                self.stats['skipped'] += 1

            # Print progress
            if self.stats['processed'] % 10 == 0:
                self.print_progress()

    def print_progress(self):
        """Print current progress"""
        elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
        rate = self.stats['processed'] / elapsed if elapsed > 0 else 0
        remaining = self.stats['total'] - self.stats['processed']
        eta = remaining / rate if rate > 0 else 0

        print(f"\n" + "=" * 60)
        print(f"PROGRESS: {self.stats['processed']}/{self.stats['total']} files")
        print(f"✅ Succeeded: {self.stats['succeeded']}")
        print(f"⏭️  Skipped: {self.stats['skipped']}")
        print(f"❌ Failed: {self.stats['failed']}")
        print(f"⚡ Rate: {rate:.1f} files/sec")
        print(f"⏱️  ETA: {eta/60:.1f} minutes")
        print("=" * 60 + "\n")

    def process_batch(self, audio_files: list):
        """Process a batch of files concurrently"""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.process_file, audio_file): audio_file
                for audio_file in audio_files
            }

            for future in as_completed(futures):
                result = future.result()
                self.update_stats(result)

    def run(self):
        """Run the batch processor"""
        print("=" * 80)
        print("SALAD CLOUD BATCH PROCESSOR - ALL RECORDINGS")
        print("=" * 80)

        # Find all audio files
        audio_queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        audio_files = sorted(audio_queue_dir.glob('*.mp3'))

        self.stats['total'] = len(audio_files)

        print(f"\n📊 FOUND {len(audio_files)} AUDIO FILES")
        print(f"📦 Batch size: {self.batch_size}")
        print(f"🔧 Max workers: {self.max_workers}")
        print(f"🚀 Starting processing...\n")

        # Process in batches
        for i in range(0, len(audio_files), self.batch_size):
            batch = audio_files[i:i+self.batch_size]
            logger.info(f"\n📦 Processing batch {i//self.batch_size + 1} ({len(batch)} files)")
            self.process_batch(batch)

            # Rate limiting between batches
            time.sleep(2)

        # Final statistics
        self.print_final_stats()

    def print_final_stats(self):
        """Print final processing statistics"""
        elapsed = (datetime.now() - self.stats['start_time']).total_seconds()

        print("\n" + "=" * 80)
        print("PROCESSING COMPLETE!")
        print("=" * 80)
        print(f"""
FINAL STATISTICS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total files:      {self.stats['total']}
Processed:        {self.stats['processed']}
Succeeded:        {self.stats['succeeded']}
Skipped:          {self.stats['skipped']}
Failed:           {self.stats['failed']}

Success rate:     {self.stats['succeeded']/self.stats['processed']*100:.1f}%
Total time:       {elapsed/60:.1f} minutes
Average speed:    {self.stats['processed']/elapsed:.1f} files/sec
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Output directory: /var/www/call-recording-system/data/transcriptions/json/
Log file:        /var/www/call-recording-system/logs/salad_batch.log
""")

        # Save final stats
        stats_file = Path('/var/www/call-recording-system/data/salad_batch_stats.json')
        with open(stats_file, 'w') as f:
            json.dump(self.stats, f, indent=2, default=str)
        print(f"Stats saved to: {stats_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process all recordings through Salad Cloud')
    parser.add_argument('--batch-size', type=int, default=20, help='Files per batch')
    parser.add_argument('--workers', type=int, default=5, help='Max concurrent workers')
    parser.add_argument('--test', action='store_true', help='Test mode - process only 10 files')

    args = parser.parse_args()

    processor = SaladBatchProcessor(
        batch_size=args.batch_size,
        max_workers=args.workers
    )

    if args.test:
        # Test mode - limit to 10 files
        audio_queue_dir = Path('/var/www/call-recording-system/data/audio_queue')
        audio_files = sorted(audio_queue_dir.glob('*.mp3'))[:10]
        processor.stats['total'] = len(audio_files)
        processor.process_batch(audio_files)
        processor.print_final_stats()
    else:
        processor.run()
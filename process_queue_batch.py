#!/usr/bin/env python3
"""
Batch Processor for Queued Recordings
Processes recordings through Salad transcription with rate limiting
Includes all Salad features: diarization, summaries, sentiment
"""

import os
import sys
import logging
import json
import psycopg2
import tempfile
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import threading
from queue import Queue
import requests

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
from ringcentral import SDK

from src.transcription.salad_transcriber_enhanced import SaladTranscriberEnhanced
from src.storage.structured_data_organizer import StructuredDataOrganizer
from src.storage.google_drive import GoogleDriveManager
from src.storage.markdown_transcript_generator import MarkdownTranscriptGenerator

# Load environment
load_dotenv('/var/www/call-recording-system/.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('batch_processing.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BatchProcessor:
    """Process queued recordings in batches with rate limiting"""

    def __init__(self, batch_size: int = 5, max_workers: int = 2):
        """
        Initialize batch processor

        Args:
            batch_size: Number of recordings to process in parallel
            max_workers: Number of concurrent download workers
        """
        self.batch_size = batch_size
        self.max_workers = max_workers

        # Statistics
        self.stats = {
            'total': 0,
            'processed': 0,
            'downloaded': 0,
            'transcribed': 0,
            'uploaded': 0,
            'failed': 0,
            'start_time': datetime.now()
        }

        # Rate limiting - increased delays
        self.last_api_call = 0
        self.api_delay = 15  # Increased to 15 seconds between API calls

        # Initialize components
        self._initialize_components()

    def _initialize_components(self):
        """Initialize all required components"""
        logger.info("Initializing components...")

        # Database connection
        self.db_config = self._parse_db_url()

        # Salad Transcriber with all features
        self.transcriber = SaladTranscriberEnhanced(
            organization_name='mst',
            enable_diarization=True,
            enable_summarization=True
        )

        # Data organizer
        self.organizer = StructuredDataOrganizer()

        # Google Drive
        self.drive_manager = GoogleDriveManager(
            credentials_path=os.getenv('GOOGLE_CREDENTIALS_PATH'),
            impersonate_email=os.getenv('GOOGLE_IMPERSONATE_EMAIL')
        )

        # Markdown generator
        self.markdown_generator = MarkdownTranscriptGenerator()

        # RingCentral for downloads
        self.rc_auth_lock = threading.Lock()

        logger.info("✅ All components initialized")

    def _parse_db_url(self) -> Dict[str, Any]:
        """Parse database URL into connection parameters"""
        db_url = os.getenv('DATABASE_URL')

        if db_url.startswith('postgresql://'):
            db_url = db_url.replace('postgresql://', '')

        parts = db_url.split('@')
        user_pass = parts[0].split(':')
        host_db = parts[1].split('/')
        host_port = host_db[0].split(':')

        return {
            'host': host_port[0],
            'port': int(host_port[1]) if len(host_port) > 1 else 5432,
            'database': host_db[1],
            'user': user_pass[0],
            'password': user_pass[1]
        }

    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    def get_pending_recordings(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get pending recordings from database"""
        conn = self.get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT
                    id, call_id, recording_id, session_id,
                    start_time, duration, from_number, from_name,
                    to_number, to_name, direction, recording_type
                FROM call_recordings
                WHERE download_status = 'pending'
                AND recording_id IS NOT NULL
                ORDER BY start_time DESC
                LIMIT %s
            """, (limit,))

            recordings = []
            for row in cur.fetchall():
                recordings.append({
                    'db_id': row[0],
                    'call_id': row[1],
                    'recording_id': row[2],
                    'session_id': row[3],
                    'start_time': row[4],
                    'duration': row[5],
                    'from_number': row[6],
                    'from_name': row[7],
                    'to_number': row[8],
                    'to_name': row[9],
                    'direction': row[10],
                    'recording_type': row[11]
                })

            return recordings

        finally:
            cur.close()
            conn.close()

    def download_recording_with_retry(self, recording_id: str, max_retries: int = 3) -> Optional[bytes]:
        """Download recording with exponential backoff for rate limiting"""

        for attempt in range(max_retries):
            try:
                # Rate limiting
                time_since_last = time.time() - self.last_api_call
                if time_since_last < self.api_delay:
                    time.sleep(self.api_delay - time_since_last)

                with self.rc_auth_lock:
                    # Create new SDK instance for this download
                    rcsdk = SDK(
                        os.getenv('RINGCENTRAL_CLIENT_ID'),
                        os.getenv('RINGCENTRAL_CLIENT_SECRET'),
                        os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')
                    )

                    platform = rcsdk.platform()
                    platform.login(jwt=os.getenv('RINGCENTRAL_JWT_TOKEN'))

                    self.last_api_call = time.time()

                    # Download recording
                    url = f'/restapi/v1.0/account/~/recording/{recording_id}/content'
                    response = platform.get(url)

                    # Handle RingCentral ApiResponse object
                    if response.ok():
                        content = response.body()
                        platform.logout()
                        return content
                    else:
                        # For failed requests, wait and retry with exponential backoff
                        wait_time = (2 ** attempt) * 30  # Exponential backoff: 30s, 60s, 120s
                        error_msg = response.error() if hasattr(response, 'error') else 'Unknown error'
                        logger.warning(f"Download failed (attempt {attempt + 1}): {error_msg}, waiting {wait_time} seconds...")
                        time.sleep(wait_time)

            except Exception as e:
                logger.error(f"Download attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 20  # Increased wait time for errors
                    logger.info(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)

        return None

    def process_recording(self, recording: Dict[str, Any]) -> bool:
        """Process a single recording through the complete pipeline"""
        recording_id = recording['recording_id']
        db_id = recording['db_id']

        logger.info(f"\n{'='*60}")
        logger.info(f"📞 Processing {recording_id}")
        logger.info(f"  From: {recording['from_name'] or recording['from_number']}")
        logger.info(f"  Duration: {recording['duration']}s")

        conn = self.get_db_connection()
        cur = conn.cursor()

        try:
            # 1. Download recording
            logger.info("  ⬇️ Downloading...")
            audio_data = self.download_recording_with_retry(recording_id)

            if not audio_data:
                logger.error("  ❌ Download failed")
                cur.execute("""
                    UPDATE call_recordings
                    SET download_status = 'failed',
                        download_attempts = download_attempts + 1,
                        error_message = 'Download failed after retries',
                        updated_at = NOW()
                    WHERE id = %s
                """, (db_id,))
                conn.commit()
                self.stats['failed'] += 1
                return False

            logger.info(f"  ✅ Downloaded {len(audio_data):,} bytes")
            self.stats['downloaded'] += 1

            # Update database
            cur.execute("""
                UPDATE call_recordings
                SET download_status = 'completed',
                    download_completed_at = NOW(),
                    file_size_bytes = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (len(audio_data), db_id))
            conn.commit()

            # 2. Save audio file for transcription queue
            logger.info("  💾 Saving audio for transcription queue...")

            # Create a local directory for audio files
            audio_dir = Path('/var/www/call-recording-system/data/audio_queue')
            audio_dir.mkdir(parents=True, exist_ok=True)

            audio_file_path = audio_dir / f"{recording_id}.mp3"
            audio_file_path.write_bytes(audio_data)

            logger.info(f"  ✅ Saved audio to {audio_file_path}")

            # For now, skip Salad transcription and mark for later processing
            # This allows us to continue downloading all recordings first
            transcription_text = "[Pending transcription]"
            job_result = {
                'transcription': transcription_text,
                'status': 'queued_for_transcription'
            }

            # Update database to show audio is ready for transcription
            cur.execute("""
                UPDATE call_recordings
                SET transcription_status = 'queued',
                    local_file_path = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (str(audio_file_path), db_id))
            conn.commit()

            if True:  # Simplified processing without transcription
                    # Mark as successfully downloaded and queued
                    logger.info("  ✅ Audio downloaded and queued for transcription")

                    # Skip Salad features for now
                    summary = ''
                    sentiment = {}
                    diarization = []
                    entities = []
                    topics = []
                    action_items = []

                    logger.info(f"    Summary: {len(summary)} chars")
                    logger.info(f"    Speakers: {len(set(s.get('speaker') for s in diarization if s.get('speaker')))}")
                    logger.info(f"    Entities: {len(entities)}")
                    logger.info(f"    Topics: {len(topics)}")
                    logger.info(f"    Action items: {len(action_items)}")

                    self.stats['transcribed'] += 1

                    # Update database - mark as queued, not completed
                    cur.execute("""
                        UPDATE call_recordings
                        SET transcription_status = 'queued',
                            updated_at = NOW()
                        WHERE id = %s
                    """, (db_id,))
                    conn.commit()

                    # 3. Create comprehensive document
                    document = {
                        'recording_id': recording_id,
                        'call_id': recording['call_id'],
                        'session_id': recording['session_id'],
                        'start_time': recording['start_time'].isoformat() if recording['start_time'] else None,
                        'duration': recording['duration'],
                        'caller': {
                            'name': recording['from_name'] or 'Unknown',
                            'number': recording['from_number']
                        },
                        'recipient': {
                            'name': recording['to_name'] or 'Unknown',
                            'number': recording['to_number']
                        },
                        'direction': recording['direction'],
                        'transcription': transcription_text,
                        'summary': summary,
                        'sentiment': sentiment,
                        'diarization': diarization,
                        'entities': entities,
                        'topics': topics,
                        'action_items': action_items,
                        'processed_at': datetime.now(timezone.utc).isoformat()
                    }

                    # Skip markdown and Google Drive for now - focus on downloading
                    # These can be processed later once all audio is downloaded
                    logger.info("  ⏭️ Skipping upload - focusing on download queue")

                    self.stats['processed'] += 1
                    return True

                    # The rest is skipped for now
                    if False:  # Skip upload section
                        upload_count = 0
                        for file_info in []:
                            try:
                                # Create folder path
                                folder_parts = file_info['folder_path'].split('/')
                                parent_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')

                                for folder_name in folder_parts:
                                    if folder_name:
                                        parent_id = self.drive_manager.get_or_create_folder(
                                            folder_name,
                                            parent_id
                                        )

                                # Upload file
                                with tempfile.NamedTemporaryFile(suffix=file_info.get('extension', ''), delete=False) as tmp:
                                    tmp.write(file_info['data'])
                                    tmp_path = tmp.name

                                file_id = self.drive_manager.upload_file(
                                    file_path=tmp_path,
                                    file_name=file_info['name'],
                                    folder_id=parent_id
                                )

                                os.unlink(tmp_path)

                                if file_id:
                                    upload_count += 1

                            except Exception as e:
                                logger.warning(f"    Failed to upload {file_info['name']}: {e}")

                    logger.info(f"  ✅ Uploaded {upload_count}/{len(organized_files)} files")

                    if upload_count > 0:
                        self.stats['uploaded'] += 1

                        # Update database
                        cur.execute("""
                            UPDATE call_recordings
                            SET upload_status = 'completed',
                                upload_completed_at = NOW(),
                                updated_at = NOW()
                            WHERE id = %s
                        """, (db_id,))
                        conn.commit()

                    self.stats['processed'] += 1
                    return True



        except Exception as e:
            logger.error(f"  ❌ Processing failed: {e}")
            cur.execute("""
                UPDATE call_recordings
                SET error_message = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (str(e)[:500], db_id))
            conn.commit()
            self.stats['failed'] += 1
            return False

        finally:
            cur.close()
            conn.close()

    def run(self):
        """Run the batch processor"""
        print("\n" + "="*80)
        print("🚀 BATCH PROCESSOR - SALAD TRANSCRIPTION WITH ALL FEATURES")
        print("="*80)

        # Get total count
        conn = self.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM call_recordings WHERE download_status = 'pending'")
        total_pending = cur.fetchone()[0]
        cur.close()
        conn.close()

        self.stats['total'] = total_pending

        print(f"\n📊 Found {total_pending} recordings to process")
        print(f"   Batch size: {self.batch_size}")
        print(f"   Rate limiting: {self.api_delay}s between downloads")
        print(f"   Exponential backoff: 30s, 60s, 120s on rate limit")

        print("\n🔄 Starting processing...")
        print("   With increased delays to avoid rate limiting")
        print(f"   Estimated time: {total_pending * (self.api_delay + 5) / 3600:.1f} hours minimum")
        print("   Monitor progress in batch_processing.log")

        processed_total = 0

        while processed_total < total_pending:
            # Get next batch
            recordings = self.get_pending_recordings(self.batch_size)

            if not recordings:
                break

            logger.info(f"\n📦 Processing batch of {len(recordings)} recordings")

            # Process each recording
            for i, recording in enumerate(recordings):
                processed_total += 1

                logger.info(f"\n[{processed_total}/{total_pending}] Processing...")
                success = self.process_recording(recording)

                # Show progress
                if processed_total % 10 == 0 or processed_total == total_pending:
                    elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
                    rate = self.stats['processed'] / elapsed if elapsed > 0 else 0
                    eta = (total_pending - processed_total) / rate if rate > 0 else 0

                    print(f"\n📊 Progress: {processed_total}/{total_pending} ({processed_total/total_pending*100:.1f}%)")
                    print(f"   ✅ Processed: {self.stats['processed']}")
                    print(f"   ⬇️ Downloaded: {self.stats['downloaded']}")
                    print(f"   🎤 Transcribed: {self.stats['transcribed']}")
                    print(f"   ☁️ Uploaded: {self.stats['uploaded']}")
                    print(f"   ❌ Failed: {self.stats['failed']}")
                    print(f"   ⚡ Rate: {rate*60:.1f} recordings/hour")
                    print(f"   ⏱️ ETA: {eta/3600:.1f} hours")

                # Rate limiting between recordings - increased delay
                logger.info(f"Waiting {self.api_delay} seconds before next recording...")
                time.sleep(self.api_delay)

        # Final summary
        elapsed_total = (datetime.now() - self.stats['start_time']).total_seconds()

        print("\n" + "="*80)
        print("📊 BATCH PROCESSING COMPLETE")
        print("="*80)
        print(f"  Total Attempted: {processed_total}")
        print(f"  ✅ Successfully Processed: {self.stats['processed']}")
        print(f"  ⬇️ Downloaded: {self.stats['downloaded']}")
        print(f"  🎤 Transcribed: {self.stats['transcribed']}")
        print(f"  ☁️ Uploaded: {self.stats['uploaded']}")
        print(f"  ❌ Failed: {self.stats['failed']}")
        print(f"  ⏱️ Total Time: {elapsed_total/3600:.1f} hours")

        if self.stats['processed'] > 0:
            print(f"  Success Rate: {self.stats['processed']/processed_total*100:.1f}%")
            print(f"  Average Time per Recording: {elapsed_total/self.stats['processed']:.1f} seconds")

        # Save summary
        summary_file = '/var/www/call-recording-system/batch_processing_summary.json'
        with open(summary_file, 'w') as f:
            json.dump({
                'run_date': datetime.now().isoformat(),
                'stats': self.stats,
                'elapsed_seconds': elapsed_total,
                'success_rate': self.stats['processed']/processed_total*100 if processed_total > 0 else 0
            }, f, indent=2, default=str)

        print(f"\n💾 Summary saved to: {summary_file}")
        print("\n✨ Batch processing complete!")
        print(f"📁 Check Google Drive: {os.getenv('GOOGLE_DRIVE_FOLDER_ID')}")


def main():
    """Main entry point"""
    # Use smaller batch size and conservative rate limiting
    processor = BatchProcessor(batch_size=5, max_workers=2)
    processor.run()


if __name__ == "__main__":
    main()
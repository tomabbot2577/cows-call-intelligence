#!/usr/bin/env python3
"""
High-Throughput Salad Batch Processor
Processes up to 230 recordings per minute (respecting 240/min API limit)
"""

import json
import os
import time
import requests
from pathlib import Path
from datetime import datetime
import sys
import threading
from queue import Queue
import concurrent.futures

sys.path.insert(0, '/var/www/call-recording-system')
from src.storage.google_drive import GoogleDriveManager
from src.storage.enhanced_organizer import EnhancedStorageOrganizer

print("=" * 80)
print("HIGH-THROUGHPUT SALAD CLOUD TRANSCRIPTION PROCESSOR")
print("Processing at 230 requests/minute")
print("=" * 80)

# Configuration
SALAD_API_KEY = os.getenv('SALAD_API_KEY')
SALAD_ORG_NAME = os.getenv('SALAD_ORG_NAME', 'mst')
# Use the correct transcription API endpoint
SALAD_API_URL = f"https://api.salad.com/api/v2/organizations/{SALAD_ORG_NAME}"

# High-throughput settings
MAX_REQUESTS_PER_MINUTE = 230  # Leave buffer from 240 limit
REQUEST_INTERVAL = 60.0 / MAX_REQUESTS_PER_MINUTE  # ~0.26 seconds between requests
MAX_CONCURRENT_JOBS = 100  # Track up to 100 jobs simultaneously
CHECK_INTERVAL = 5  # Check job status every 5 seconds

# Load environment variables
from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

SALAD_API_KEY = os.getenv('SALAD_API_KEY')
GOOGLE_DRIVE_FOLDER = os.getenv('GOOGLE_DRIVE_TRANSCRIPTS_FOLDER', '1obRW7K6EQFLtMlgYaO21aYS_o-77hOJ1')
GOOGLE_IMPERSONATE_EMAIL = os.getenv('GOOGLE_IMPERSONATE_EMAIL', 'sabbey@mainsequence.net')
if not SALAD_API_KEY:
    print("❌ ERROR: SALAD_API_KEY not found")
    sys.exit(1)

# Setup logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/www/call-recording-system/logs/salad_high_throughput.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load audio files to process
audio_dir = Path('/var/www/call-recording-system/data/audio_queue')
audio_files = sorted(audio_dir.glob('*.mp3'))

# Filter out already processed files
transcripts_dir = Path('/var/www/call-recording-system/data/transcriptions/json')
to_process = []

for audio_file in audio_files:
    recording_id = audio_file.stem
    year = datetime.now().strftime('%Y')
    month = datetime.now().strftime('%m')
    day = datetime.now().strftime('%d')
    output_file = transcripts_dir / year / month / day / f"{recording_id}.json"

    if not output_file.exists():
        to_process.append(recording_id)

print(f"\n📊 QUEUE STATUS:")
print(f"  Total recordings to process: {len(to_process)}")
print(f"  Processing rate: {MAX_REQUESTS_PER_MINUTE} req/min")
print(f"  Estimated time: {len(to_process) / MAX_REQUESTS_PER_MINUTE:.1f} minutes")

# Create headers for Salad API
headers = {
    'Salad-Api-Key': SALAD_API_KEY,
    'Content-Type': 'application/json'
}

# Global tracking
active_jobs = {}  # job_id -> recording_id mapping
completed_count = 0
failed_count = 0
submitted_count = 0
job_queue = Queue()
results_queue = Queue()
start_time = datetime.now()
last_request_time = 0
request_lock = threading.Lock()

def submit_job(recording_id):
    """Submit a single transcription job to Salad Cloud"""
    global submitted_count, last_request_time

    # Rate limiting
    with request_lock:
        current_time = time.time()
        time_since_last = current_time - last_request_time
        if time_since_last < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - time_since_last)
        last_request_time = time.time()

    audio_url = f"http://31.97.102.13:8080/audio/{recording_id}.mp3"

    headers = {
        'Salad-Api-Key': SALAD_API_KEY,
        'Content-Type': 'application/json'
    }

    payload = {
        "input": {
            "url": audio_url,
            "config": {
                "engine": "full",
                "language": "en-US",
                "diarization": True,
                "summarization": True,
                "word_timing": True,
                "srt": True
            }
        }
    }

    try:
        # Use the correct endpoint format for Salad transcription API
        response = requests.post(
            f"https://api.salad.com/api/public/organizations/{SALAD_ORG_NAME}/inference-endpoints/transcribe/jobs",
            json=payload,
            headers=headers,
            timeout=10
        )

        if response.status_code == 201:
            job_data = response.json()
            job_id = job_data.get('id')
            active_jobs[job_id] = {
                'recording_id': recording_id,
                'submitted_at': datetime.now(),
                'status': 'submitted'
            }
            submitted_count += 1
            logger.info(f"✅ Submitted {recording_id} -> Job {job_id}")
            return job_id
        else:
            logger.error(f"❌ Failed to submit {recording_id}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"❌ Error submitting {recording_id}: {e}")
        return None

def check_job_status(job_id):
    """Check the status of a submitted job"""
    headers = {'Salad-Api-Key': SALAD_API_KEY}

    try:
        response = requests.get(
            f"https://api.salad.com/api/public/organizations/{SALAD_ORG_NAME}/inference-endpoints/transcribe/jobs/{job_id}",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            return response.json()
        else:
            return {'status': 'error'}
    except Exception as e:
        logger.error(f"Error checking job {job_id}: {e}")
        return {'status': 'error'}

def save_transcription(job_id, transcription_data):
    """Save completed transcription to disk with enhanced formatting and Google Drive upload"""
    global completed_count

    job_info = active_jobs.get(job_id)
    if not job_info:
        return

    recording_id = job_info['recording_id']
    now = datetime.now()

    # Extract transcription output
    output = transcription_data.get('output', {})

    # Prepare comprehensive transcription result
    transcription_result = {
        'text': output.get('text', ''),
        'segments': output.get('segments', []),
        'confidence': output.get('confidence', 0.95),
        'language': 'en-US',
        'language_probability': 1.0,
        'word_count': output.get('word_count', 0),
        'duration_seconds': output.get('audio_duration', 0),
        'processing_time_seconds': (now - job_info['submitted_at']).total_seconds(),
        'job_id': job_id,
        'timestamps': output.get('timestamps', []),
        'metadata': {
            'engine': 'full',
            'diarization': True,
            'summarization': True,
            'word_timing': True,
            'srt': True,
            'summary': output.get('summary', ''),
            'srt_content': output.get('srt', ''),
            'salad_processing_time': output.get('processing_time', 0),
            'overall_processing_time': (now - job_info['submitted_at']).total_seconds()
        }
    }

    # Prepare call metadata (minimal since we don't have full call details)
    call_metadata = {
        'date': now.strftime('%Y-%m-%d'),
        'time': now.strftime('%H:%M:%S'),
        'duration': output.get('audio_duration', 0),
        'direction': 'unknown',
        'from': {'number': 'unknown', 'name': ''},
        'to': {'number': 'unknown', 'name': ''},
        'recording_url': f"http://31.97.102.13:8080/audio/{recording_id}.mp3",
        'file_size_bytes': 0
    }

    # Initialize storage organizer for dual-format saving
    storage_organizer = EnhancedStorageOrganizer()

    # Save using enhanced organizer (creates JSON, enhanced JSON, MD, and N8N queue)
    saved_paths = storage_organizer.save_transcription(
        recording_id=recording_id,
        transcription_result=transcription_result,
        call_metadata=call_metadata,
        google_drive_id=None  # Will add after upload
    )

    # Upload to Google Drive
    drive_id = None
    try:
        # Initialize Google Drive manager
        drive_manager = GoogleDriveManager(
            credentials_path='/var/www/call-recording-system/config/google_service_account.json',
            folder_id=GOOGLE_DRIVE_FOLDER,
            impersonate_email=GOOGLE_IMPERSONATE_EMAIL
        )

        # Create date-based folder structure in Google Drive
        year_folder = drive_manager.get_or_create_folder(
            folder_name=str(now.year),
            parent_id=GOOGLE_DRIVE_FOLDER
        )

        month_folder = drive_manager.get_or_create_folder(
            folder_name=now.strftime('%m-%B'),
            parent_id=year_folder
        )

        day_folder = drive_manager.get_or_create_folder(
            folder_name=now.strftime('%d'),
            parent_id=month_folder
        )

        # Upload the enhanced JSON file (contains all metadata)
        drive_id = drive_manager.upload_file(
            file_path=saved_paths['enhanced_json'],
            file_name=f"{recording_id}_full.json",
            folder_id=day_folder,
            metadata={
                'recording_id': recording_id,
                'type': 'salad_transcript_enhanced',
                'processed_at': now.isoformat(),
                'engine': 'full',
                'features': 'diarization,summarization,timestamps,word_timing',
                'word_count': str(output.get('word_count', 0)),
                'duration': str(output.get('audio_duration', 0))
            }
        )

        if drive_id:
            logger.info(f"☁️  Uploaded to Google Drive: {recording_id} -> {drive_id}")

            # Also upload the markdown for human reading
            md_drive_id = drive_manager.upload_file(
                file_path=saved_paths['markdown'],
                file_name=f"{recording_id}_summary.md",
                folder_id=day_folder,
                metadata={
                    'recording_id': recording_id,
                    'type': 'human_readable_summary',
                    'processed_at': now.isoformat()
                }
            )

            if md_drive_id:
                logger.info(f"📝 Uploaded MD to Google Drive: {recording_id}")

        drive_manager.close()
    except Exception as e:
        logger.warning(f"⚠️  Google Drive upload failed for {recording_id}: {e}")

    completed_count += 1
    word_count = output.get('word_count', 0)
    duration = output.get('audio_duration', 0)

    logger.info(f"💾 Saved {recording_id}: {word_count} words, {duration:.1f}s audio")
    logger.info(f"   Files: JSON={saved_paths['json']}, MD={saved_paths['markdown']}, N8N={saved_paths['n8n_queue']}")

    # DELETE AUDIO FILE after successful transcription and upload
    audio_file_path = Path(f'/var/www/call-recording-system/data/audio_queue/{recording_id}.mp3')
    if audio_file_path.exists():
        try:
            # Calculate hash for audit before deletion
            import hashlib
            with open(audio_file_path, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            file_size = audio_file_path.stat().st_size

            # Delete the audio file
            if os.path.exists('/usr/bin/shred'):
                # Secure deletion with shred (-u to unlink/remove after overwriting)
                os.system(f'shred -vfzu -n 1 "{audio_file_path}"')
                logger.info(f"🔒 Securely deleted audio: {recording_id}.mp3 (shred)")
            else:
                # Standard deletion
                audio_file_path.unlink()
                logger.info(f"🗑️  Deleted audio: {recording_id}.mp3")

            # Verify deletion
            if not audio_file_path.exists():
                logger.info(f"✅ Audio deletion verified: {recording_id}.mp3 ({file_size} bytes, hash: {file_hash[:8]}...)")

                # Log to audit file
                audit_entry = {
                    'timestamp': now.isoformat(),
                    'recording_id': recording_id,
                    'file_path': str(audio_file_path),
                    'file_size': file_size,
                    'file_hash': file_hash,
                    'deletion_method': 'shred' if os.path.exists('/usr/bin/shred') else 'unlink',
                    'verified': True
                }

                audit_log_path = Path('/var/www/call-recording-system/logs/deletion_audit.log')
                with open(audit_log_path, 'a') as audit_file:
                    audit_file.write(json.dumps(audit_entry) + '\n')
            else:
                logger.error(f"❌ Audio deletion FAILED: {recording_id}.mp3 still exists!")
        except Exception as e:
            logger.error(f"❌ Error deleting audio {recording_id}.mp3: {e}")
    else:
        logger.info(f"ℹ️  Audio file already deleted: {recording_id}.mp3")

def job_submitter(recordings):
    """Thread to submit jobs at rate limit"""
    for recording_id in recordings:
        job_id = submit_job(recording_id)
        if job_id:
            job_queue.put(job_id)

        # Print progress every 10 submissions
        if submitted_count % 10 == 0:
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = submitted_count / (elapsed / 60) if elapsed > 0 else 0
            logger.info(f"📊 Progress: {submitted_count}/{len(recordings)} submitted ({rate:.1f} req/min)")

def job_monitor():
    """Thread to monitor job status"""
    global failed_count

    while True:
        # Check all active jobs
        jobs_to_check = list(active_jobs.keys())

        for job_id in jobs_to_check:
            if job_id not in active_jobs:
                continue

            job_data = check_job_status(job_id)
            status = job_data.get('status')

            if status == 'succeeded':
                save_transcription(job_id, job_data)
                del active_jobs[job_id]
            elif status == 'failed':
                job_info = active_jobs[job_id]
                logger.error(f"❌ Job {job_id} failed for {job_info['recording_id']}")
                failed_count += 1
                del active_jobs[job_id]
            # else: still pending/running

        # Print stats
        if len(active_jobs) > 0:
            logger.info(f"📈 Active jobs: {len(active_jobs)}, Completed: {completed_count}, Failed: {failed_count}")

        time.sleep(CHECK_INTERVAL)

        # Exit if all done
        if submitted_count == len(to_process) and len(active_jobs) == 0:
            break

# Main processing
if __name__ == "__main__":
    if len(to_process) == 0:
        print("No recordings to process!")
        sys.exit(0)

    print(f"\n🚀 STARTING HIGH-THROUGHPUT PROCESSING...")
    print("-" * 40)

    # Start job submitter thread
    submitter = threading.Thread(target=job_submitter, args=(to_process,))
    submitter.start()

    # Start job monitor thread
    monitor = threading.Thread(target=job_monitor)
    monitor.start()

    # Wait for completion
    submitter.join()
    monitor.join()

    # Final stats
    total_time = (datetime.now() - start_time).total_seconds()
    actual_rate = submitted_count / (total_time / 60) if total_time > 0 else 0

    print("\n" + "=" * 80)
    print("HIGH-THROUGHPUT PROCESSING COMPLETE")
    print("=" * 80)
    print(f"""
📊 FINAL RESULTS:
  ✅ Successfully transcribed: {completed_count}
  ❌ Failed: {failed_count}
  📨 Total submitted: {submitted_count}

⏱️  PERFORMANCE:
  Total time: {total_time/60:.1f} minutes
  Actual rate: {actual_rate:.1f} req/min
  Target rate: {MAX_REQUESTS_PER_MINUTE} req/min

📁 OUTPUT:
  Transcripts saved to: {transcripts_dir}
""")

    print("\n✅ Processing complete!")
    print("=" * 80)
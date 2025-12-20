#!/usr/bin/env python3
"""
Catch up on RingCentral recordings from September 22 to December 18, 2025

Downloads all recordings with proper rate limiting to avoid API throttling.
RingCentral limits: ~1000 requests/minute for API calls, but downloads are slower.
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
import logging

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
from ringcentral import SDK

# Load environment
load_dotenv('/var/www/call-recording-system/.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Rate limit settings (optimized for faster downloads)
DELAY_BETWEEN_PAGES = 1  # seconds between API page requests
DELAY_BETWEEN_DOWNLOADS = 3  # seconds between file downloads (RingCentral allows more)
MAX_DOWNLOADS_PER_BATCH = 100  # downloads before a longer pause
BATCH_PAUSE = 60  # seconds between batches

def get_downloaded_ids():
    """Get list of already downloaded recording IDs"""
    downloaded = set()
    audio_dir = "/var/www/call-recording-system/data/audio_queue"

    if os.path.exists(audio_dir):
        for filename in os.listdir(audio_dir):
            if filename.endswith('.mp3'):
                recording_id = filename.replace('.mp3', '')
                downloaded.add(recording_id)

    return downloaded

def get_authenticated_platform():
    """Get authenticated RingCentral platform"""
    rcsdk = SDK(
        os.getenv('RINGCENTRAL_CLIENT_ID'),
        os.getenv('RINGCENTRAL_CLIENT_SECRET'),
        os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')
    )

    platform = rcsdk.platform()
    platform.login(jwt=os.getenv('RINGCENTRAL_JWT_TOKEN'))

    return platform

def fetch_recordings_for_period(platform, start_date, end_date):
    """Fetch recordings for a specific date range"""
    logger.info(f"Fetching recordings from {start_date.date()} to {end_date.date()}")

    all_recordings = []
    page = 1
    per_page = 100

    while True:
        try:
            response = platform.get('/restapi/v1.0/account/~/call-log', {
                'dateFrom': start_date.isoformat(),
                'dateTo': end_date.isoformat(),
                'view': 'Detailed',
                'recordingType': 'All',
                'perPage': per_page,
                'page': page
            })

            records = response.json_dict().get('records', [])

            for record in records:
                if 'recording' in record:
                    recording = record['recording']
                    rec_info = {
                        'id': str(recording.get('id', '')),
                        'uri': recording.get('contentUri', ''),
                        'duration': record.get('duration', 0),
                        'start_time': record.get('startTime', ''),
                        'from': record.get('from', {}).get('name', 'Unknown'),
                        'to': record.get('to', {}).get('name', 'Unknown'),
                        'direction': record.get('direction', 'Unknown')
                    }
                    if rec_info['id'] and rec_info['uri']:
                        all_recordings.append(rec_info)

            if len(records) < per_page:
                break

            page += 1
            time.sleep(DELAY_BETWEEN_PAGES)

        except Exception as e:
            if '429' in str(e):
                logger.warning(f"Rate limited on page {page}. Waiting 60s...")
                time.sleep(60)
            else:
                logger.error(f"Error fetching page {page}: {e}")
                break

    return all_recordings

def download_recording(platform, recording_info, output_dir):
    """Download a single recording with retry logic"""
    recording_id = recording_info['id']
    output_path = os.path.join(output_dir, f"{recording_id}.mp3")

    if os.path.exists(output_path):
        return True, "already_exists"

    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = platform.get(recording_info['uri'])

            with open(output_path, 'wb') as f:
                f.write(response.body())

            file_size = os.path.getsize(output_path)
            logger.info(f"  Downloaded {recording_id}: {file_size:,} bytes")

            return True, "downloaded"

        except Exception as e:
            if '429' in str(e) or 'rate' in str(e).lower():
                wait_time = 60 * (attempt + 1)
                logger.warning(f"  Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"  Download failed: {e}")
                time.sleep(10)

    return False, "failed"

def main():
    """Main processing function"""
    logger.info("=" * 80)
    logger.info("CATCHING UP ON RINGCENTRAL RECORDINGS")
    logger.info("Date range: September 22, 2025 to December 18, 2025")
    logger.info("=" * 80)

    # Setup output directory
    output_dir = "/var/www/call-recording-system/data/audio_queue"
    os.makedirs(output_dir, exist_ok=True)

    # Get already downloaded recordings
    downloaded_ids = get_downloaded_ids()
    logger.info(f"Already downloaded: {len(downloaded_ids)} recordings")

    # Authenticate
    logger.info("Authenticating with RingCentral...")
    platform = get_authenticated_platform()
    logger.info("Authentication successful!")

    # Fetch recordings in weekly chunks to avoid timeout
    start_date = datetime(2025, 9, 22)
    end_date = datetime(2025, 12, 18, 23, 59, 59)

    all_recordings = []
    current_start = start_date

    while current_start < end_date:
        current_end = min(current_start + timedelta(days=7), end_date)

        week_recordings = fetch_recordings_for_period(platform, current_start, current_end)
        all_recordings.extend(week_recordings)

        logger.info(f"  Found {len(week_recordings)} recordings for this week, total: {len(all_recordings)}")

        current_start = current_end
        time.sleep(DELAY_BETWEEN_PAGES)

    # Find recordings that need downloading
    to_download = []
    for rec in all_recordings:
        if rec['id'] not in downloaded_ids:
            to_download.append(rec)

    logger.info(f"Total recordings found: {len(all_recordings)}")
    logger.info(f"Need to download: {len(to_download)}")

    if not to_download:
        logger.info("All recordings already downloaded!")
        return

    # Save list of recordings to download
    with open('/var/www/call-recording-system/data/recordings_to_download.json', 'w') as f:
        json.dump(to_download, f, indent=2)
    logger.info(f"Saved list to recordings_to_download.json")

    # Download recordings
    stats = {'downloaded': 0, 'failed': 0, 'skipped': 0}
    batch_count = 0

    for i, rec in enumerate(to_download, 1):
        logger.info(f"[{i}/{len(to_download)}] Processing {rec['id']} ({rec['start_time'][:10] if rec['start_time'] else 'unknown date'})")

        success, status = download_recording(platform, rec, output_dir)

        if success:
            if status == "downloaded":
                stats['downloaded'] += 1
                batch_count += 1
            else:
                stats['skipped'] += 1
        else:
            stats['failed'] += 1

        # Rate limiting
        time.sleep(DELAY_BETWEEN_DOWNLOADS)

        # Batch pause
        if batch_count >= MAX_DOWNLOADS_PER_BATCH:
            logger.info(f"Batch pause - completed {stats['downloaded']} downloads. Waiting {BATCH_PAUSE}s...")
            time.sleep(BATCH_PAUSE)
            batch_count = 0

            # Re-authenticate to refresh token
            try:
                platform = get_authenticated_platform()
            except:
                pass

        # Progress update every 20 recordings
        if i % 20 == 0:
            logger.info(f"Progress: {i}/{len(to_download)} - Downloaded: {stats['downloaded']}, Failed: {stats['failed']}")

    # Final stats
    logger.info("=" * 80)
    logger.info("DOWNLOAD COMPLETE")
    logger.info(f"Downloaded: {stats['downloaded']}")
    logger.info(f"Skipped (already existed): {stats['skipped']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info("=" * 80)

    # Save stats
    with open('/var/www/call-recording-system/data/catchup_stats.json', 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'stats': stats,
            'date_range': f"{start_date.date()} to {end_date.date()}"
        }, f, indent=2)

if __name__ == '__main__':
    main()

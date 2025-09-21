#!/usr/bin/env python3
"""
Finish downloading remaining RingCentral recordings with improved rate limit handling
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

def fetch_available_recordings():
    """Fetch all available recordings from RingCentral"""
    logger.info("🔐 Authenticating with RingCentral...")
    platform = get_authenticated_platform()
    logger.info("✅ Successfully authenticated")

    # Get recordings from last 30 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    logger.info(f"📅 Fetching recordings from {start_date.date()} to {end_date.date()}")

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

            # RingCentral SDK returns a response object
            records = response.json_dict().get('records', [])

            for record in records:
                if 'recording' in record:
                    recording = record['recording']
                    rec_info = {
                        'id': str(recording.get('id', '')),
                        'uri': recording.get('contentUri', ''),
                        'duration': record.get('duration', 0),
                        'start_time': record.get('startTime', ''),
                        'from': record.get('from', {}).get('name', 'Unknown')
                    }
                    if rec_info['id'] and rec_info['uri']:
                        all_recordings.append(rec_info)

            if len(records) < per_page:
                break

            page += 1
            time.sleep(1)  # Rate limit protection

        except Exception as e:
            logger.error(f"Error fetching page {page}: {e}")
            break

    logger.info(f"✅ Found {len(all_recordings)} recordings available")
    return all_recordings

def download_recording(platform, recording_info, output_dir):
    """Download a single recording with retry logic"""
    recording_id = recording_info['id']
    output_path = os.path.join(output_dir, f"{recording_id}.mp3")

    if os.path.exists(output_path):
        return True

    max_retries = 3
    retry_delay = 30

    for attempt in range(max_retries):
        try:
            logger.info(f"  ⬇️ Downloading {recording_id} (attempt {attempt + 1}/{max_retries})...")

            # Download the recording
            response = platform.get(recording_info['uri'])

            # Save to file
            with open(output_path, 'wb') as f:
                f.write(response.body())

            file_size = os.path.getsize(output_path)
            logger.info(f"  ✅ Downloaded {file_size:,} bytes")

            return True

        except Exception as e:
            if '429' in str(e) or 'rate' in str(e).lower():
                wait_time = retry_delay * (attempt + 1)
                logger.warning(f"  ⚠️ Rate limited. Waiting {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"  ❌ Download failed: {e}")
                time.sleep(5)

    return False

def main():
    """Main processing function"""
    logger.info("=" * 80)
    logger.info("FINISHING RINGCENTRAL RECORDING DOWNLOADS")
    logger.info("=" * 80)

    # Setup output directory
    output_dir = "/var/www/call-recording-system/data/audio_queue"
    os.makedirs(output_dir, exist_ok=True)

    # Get already downloaded recordings
    downloaded_ids = get_downloaded_ids()
    logger.info(f"📂 Already downloaded: {len(downloaded_ids)} recordings")

    # Get available recordings
    available_recordings = fetch_available_recordings()

    # Find recordings that need to be downloaded
    to_download = []
    for rec in available_recordings:
        if rec['id'] not in downloaded_ids:
            to_download.append(rec)

    logger.info(f"📥 Need to download: {len(to_download)} recordings")

    if not to_download:
        logger.info("✅ All available recordings have been downloaded!")
        return

    # Get authenticated platform for downloads
    platform = get_authenticated_platform()

    # Download missing recordings
    successful = 0
    failed = 0

    for i, recording in enumerate(to_download, 1):
        logger.info(f"\n[{i}/{len(to_download)}] Processing {recording['id']}")
        logger.info(f"  From: {recording['from']}")
        logger.info(f"  Duration: {recording['duration']}s")

        if download_recording(platform, recording, output_dir):
            successful += 1
        else:
            failed += 1

        # Rate limit protection - wait longer between downloads
        if i < len(to_download):
            wait_time = 20  # 20 seconds between downloads to avoid rate limits
            logger.info(f"  ⏳ Waiting {wait_time} seconds before next download...")
            time.sleep(wait_time)

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("DOWNLOAD SUMMARY")
    logger.info("=" * 80)
    logger.info(f"✅ Successfully downloaded: {successful}")
    logger.info(f"❌ Failed downloads: {failed}")
    logger.info(f"📂 Total recordings in queue: {len(downloaded_ids) + successful}")

    # Save summary
    summary = {
        'run_date': datetime.now().isoformat(),
        'previously_downloaded': len(downloaded_ids),
        'newly_downloaded': successful,
        'failed': failed,
        'total_in_queue': len(downloaded_ids) + successful
    }

    with open('finish_downloads_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)

    logger.info(f"\n📊 Summary saved to finish_downloads_summary.json")

if __name__ == "__main__":
    main()
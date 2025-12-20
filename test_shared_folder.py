#!/usr/bin/env python3
"""
Test script to upload to shared Google Drive folder
Uses the folder you've already shared with the service account
"""

import os
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from pathlib import Path
import time

from src.config.settings import Settings
from src.ringcentral.auth import RingCentralAuth
from src.ringcentral.client import RingCentralClient
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Your shared folder ID
SHARED_FOLDER_ID = "1IbGtmzk85Q5gYAfdb2AwA9kLNE1EJLx0"


class SharedFolderUploader:
    """Upload recordings to shared Google Drive folder"""

    def __init__(self):
        """Initialize the uploader"""
        self.settings = Settings()
        self.processed_count = 0
        self.upload_count = 0
        self.failed_count = 0
        self._initialize_components()

    def _initialize_components(self):
        """Initialize all required components"""
        logger.info("Initializing components...")

        # RingCentral
        self.ringcentral_auth = RingCentralAuth(
            jwt_token=self.settings.ringcentral_jwt_token,
            client_id=self.settings.ringcentral_client_id,
            client_secret=self.settings.ringcentral_client_secret,
            sandbox=getattr(self.settings, 'ringcentral_sandbox', False)
        )
        self.ringcentral_client = RingCentralClient(auth=self.ringcentral_auth)

        # Google Drive - Direct API access
        credentials = service_account.Credentials.from_service_account_file(
            self.settings.google_credentials_path,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        self.drive_service = build('drive', 'v3', credentials=credentials)

        logger.info("✅ Components initialized successfully")
        logger.info(f"📁 Using shared folder: {SHARED_FOLDER_ID}")

    def create_folder_in_shared(self, folder_name: str, parent_id: str = None) -> str:
        """Create a folder in the shared drive"""
        parent_id = parent_id or SHARED_FOLDER_ID

        # Check if folder already exists
        query = f"name='{folder_name}' and '{parent_id}' in parents and trashed=false"
        results = self.drive_service.files().list(
            q=query,
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        files = results.get('files', [])
        if files:
            logger.info(f"  📁 Found existing folder: {folder_name} (ID: {files[0]['id']})")
            return files[0]['id']

        # Create new folder
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }

        folder = self.drive_service.files().create(
            body=file_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()

        folder_id = folder.get('id')
        logger.info(f"  📁 Created folder: {folder_name} (ID: {folder_id})")
        return folder_id

    def upload_file_to_shared(self, file_path: str, file_name: str, folder_id: str) -> str:
        """Upload a file to the shared folder"""
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }

        # Determine MIME type
        mime_type = 'audio/mpeg' if file_path.endswith('.mp3') else 'application/octet-stream'

        media = MediaFileUpload(
            file_path,
            mimetype=mime_type,
            resumable=True
        )

        file = self.drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,name,size',
            supportsAllDrives=True
        ).execute()

        logger.info(f"     ✅ Uploaded: {file_name} (ID: {file.get('id')}, Size: {file.get('size', 0):,} bytes)")
        return file.get('id')

    def fetch_recent_recordings(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch recent recordings"""
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=7)

        logger.info(f"📅 Fetching recordings from {start_date.date()} to {end_date.date()}")

        recordings = []
        try:
            for record in self.ringcentral_client.get_all_call_logs(
                date_from=start_date,
                date_to=end_date,
                recording_type='All'
            ):
                recording_info = record.get('recording', {})
                if recording_info:
                    call_data = {
                        'call_id': record.get('id'),
                        'session_id': record.get('sessionId'),
                        'start_time': record.get('startTime'),
                        'duration': record.get('duration', 0),
                        'from_name': record.get('from', {}).get('name'),
                        'from_number': record.get('from', {}).get('phoneNumber'),
                        'to_name': record.get('to', {}).get('name'),
                        'to_number': record.get('to', {}).get('phoneNumber'),
                        'direction': record.get('direction'),
                        'recording_id': recording_info.get('id'),
                    }
                    recordings.append(call_data)

                    if len(recordings) >= limit:
                        break

        except Exception as e:
            logger.error(f"Error fetching recordings: {e}")
            raise

        logger.info(f"✅ Fetched {len(recordings)} recordings")
        return recordings[:limit]

    def process_recording(self, recording: Dict[str, Any]) -> bool:
        """Process a single recording"""
        recording_id = recording['recording_id']
        self.processed_count += 1

        logger.info(f"\n{'='*60}")
        logger.info(f"📞 [{self.processed_count}/5] Processing recording {recording_id}")
        logger.info(f"  From: {recording['from_name']} ({recording['from_number']})")
        logger.info(f"  To: {recording['to_name']} ({recording['to_number']})")
        logger.info(f"  Duration: {recording['duration']} seconds")

        # Create temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Download recording
            logger.info(f"  ⬇️  Downloading audio...")
            audio_path = temp_path / f"{recording_id}.mp3"

            try:
                self.ringcentral_client.download_recording(
                    recording_id=recording_id,
                    output_path=str(audio_path)
                )

                file_size = audio_path.stat().st_size
                logger.info(f"  ✅ Downloaded: {file_size:,} bytes")

                # Parse date for folder structure
                call_datetime = datetime.fromisoformat(
                    recording['start_time'].replace('Z', '+00:00')
                )
                year = call_datetime.strftime('%Y')
                month_folder = call_datetime.strftime('%m-%B')

                # Create folder structure in shared folder
                logger.info(f"  📁 Creating folder structure...")
                year_folder_id = self.create_folder_in_shared(f"Recordings_{year}", SHARED_FOLDER_ID)
                month_folder_id = self.create_folder_in_shared(month_folder, year_folder_id)

                # Upload audio file
                logger.info(f"  ☁️  Uploading to shared folder...")
                filename = f"{call_datetime.strftime('%Y%m%d_%H%M')}_{recording_id}.mp3"

                file_id = self.upload_file_to_shared(
                    str(audio_path),
                    filename,
                    month_folder_id
                )

                self.upload_count += 1
                logger.info(f"  🎉 Successfully uploaded to shared folder")
                return True

            except Exception as e:
                logger.error(f"  ❌ Failed: {e}")
                self.failed_count += 1
                return False

    def run(self):
        """Run the test"""
        print("\n" + "="*70)
        print("🧪 TEST: UPLOAD TO SHARED GOOGLE DRIVE FOLDER")
        print(f"   Shared Folder ID: {SHARED_FOLDER_ID}")
        print("="*70)
        print("\n⚠️  IMPORTANT: Make sure you've shared the folder with:")
        print("   call-recording-uploader@snappy-elf-472517-r8.iam.gserviceaccount.com")
        print("   with Editor permissions!\n")

        try:
            # Test with just 5 recordings
            recordings = self.fetch_recent_recordings(5)

            if not recordings:
                print("❌ No recordings found")
                return

            print(f"\n📋 Processing {len(recordings)} recordings...")

            for recording in recordings:
                self.process_recording(recording)
                time.sleep(2)  # Avoid rate limiting

            # Summary
            print("\n" + "="*70)
            print("📊 SUMMARY")
            print("="*70)
            print(f"  Total Processed: {self.processed_count}")
            print(f"  ✅ Uploaded: {self.upload_count}")
            print(f"  ❌ Failed: {self.failed_count}")

            if self.upload_count > 0:
                print("\n✨ Success! Check your Google Drive folder:")
                print(f"   https://drive.google.com/drive/u/2/folders/{SHARED_FOLDER_ID}")
                print("   Look for: Recordings_2025/[Month]/ folders")
            else:
                print("\n❌ No files uploaded. Check:")
                print("   1. The folder is shared with the service account")
                print("   2. The service account has Editor permissions")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            raise
        finally:
            if hasattr(self, 'ringcentral_auth'):
                self.ringcentral_auth.close()


def main():
    """Main entry point"""
    uploader = SharedFolderUploader()
    uploader.run()


if __name__ == "__main__":
    main()
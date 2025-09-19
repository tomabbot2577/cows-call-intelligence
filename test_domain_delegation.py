#!/usr/bin/env python3
"""
Test script for Google Drive upload with domain-wide delegation
This script impersonates a Google Workspace user to upload files
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
from googleapiclient.errors import HttpError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DomainDelegationUploader:
    """Upload recordings using domain-wide delegation"""

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

        # Get the impersonation email from environment
        self.impersonate_email = os.getenv('GOOGLE_IMPERSONATE_EMAIL')

        if not self.impersonate_email:
            logger.error("❌ GOOGLE_IMPERSONATE_EMAIL not set in .env file!")
            logger.error("   Please add: GOOGLE_IMPERSONATE_EMAIL=user@yourdomain.com")
            raise ValueError("Missing GOOGLE_IMPERSONATE_EMAIL configuration")

        logger.info(f"📧 Will impersonate: {self.impersonate_email}")

        # RingCentral
        self.ringcentral_auth = RingCentralAuth(
            jwt_token=self.settings.ringcentral_jwt_token,
            client_id=self.settings.ringcentral_client_id,
            client_secret=self.settings.ringcentral_client_secret,
            sandbox=getattr(self.settings, 'ringcentral_sandbox', False)
        )
        self.ringcentral_client = RingCentralClient(auth=self.ringcentral_auth)

        # Google Drive with domain-wide delegation
        try:
            # Create credentials with domain-wide delegation
            credentials = service_account.Credentials.from_service_account_file(
                self.settings.google_credentials_path,
                scopes=['https://www.googleapis.com/auth/drive']
            )

            # Impersonate the specified user
            delegated_credentials = credentials.with_subject(self.impersonate_email)

            # Build the Drive service
            self.drive_service = build('drive', 'v3', credentials=delegated_credentials)

            logger.info("✅ Google Drive service initialized with domain-wide delegation")

            # Test the connection
            self._test_drive_connection()

        except Exception as e:
            logger.error(f"❌ Failed to initialize Google Drive with delegation: {e}")
            logger.error("   Please check:")
            logger.error("   1. Domain-wide delegation is configured in Google Admin")
            logger.error("   2. Client ID 104184775393017269477 is authorized")
            logger.error(f"   3. {self.impersonate_email} is a valid user in your domain")
            raise

    def _test_drive_connection(self):
        """Test the Google Drive connection"""
        try:
            # Try to list files (just 1) to verify connection
            results = self.drive_service.files().list(
                pageSize=1,
                fields="files(id, name)"
            ).execute()

            logger.info("✅ Successfully connected to Google Drive")
            logger.info(f"   Acting as: {self.impersonate_email}")

        except HttpError as e:
            if 'delegation denied' in str(e).lower():
                logger.error("❌ Domain-wide delegation not configured!")
                logger.error("   Please follow the steps in DOMAIN_WIDE_DELEGATION_SETUP.md")
            elif 'invalid impersonation' in str(e).lower():
                logger.error(f"❌ Cannot impersonate {self.impersonate_email}")
                logger.error("   Verify this is a valid user email in your Google Workspace")
            else:
                logger.error(f"❌ Drive connection test failed: {e}")
            raise

    def get_or_create_folder(self, folder_name: str, parent_id: str = None) -> str:
        """Get or create a folder in Google Drive"""
        # Check if folder exists
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        query += " and trashed=false"

        results = self.drive_service.files().list(
            q=query,
            fields='files(id, name)',
            supportsAllDrives=True
        ).execute()

        files = results.get('files', [])
        if files:
            folder_id = files[0]['id']
            logger.info(f"  📁 Found existing folder: {folder_name} (ID: {folder_id})")
            return folder_id

        # Create new folder
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]

        folder = self.drive_service.files().create(
            body=file_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()

        folder_id = folder.get('id')
        logger.info(f"  📁 Created new folder: {folder_name} (ID: {folder_id})")
        return folder_id

    def upload_file(self, file_path: str, file_name: str, folder_id: str) -> str:
        """Upload a file to Google Drive"""
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
            fields='id,name,size,webViewLink',
            supportsAllDrives=True
        ).execute()

        file_id = file.get('id')
        file_size = file.get('size', 0)
        web_link = file.get('webViewLink', '')

        logger.info(f"     ✅ Uploaded: {file_name}")
        logger.info(f"        Size: {int(file_size):,} bytes")
        logger.info(f"        Link: {web_link}")

        return file_id

    def fetch_recent_recordings(self, limit: int = 3) -> List[Dict[str, Any]]:
        """Fetch recent recordings for testing"""
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
        logger.info(f"📞 [{self.processed_count}/3] Processing recording {recording_id}")
        logger.info(f"  From: {recording['from_name']} ({recording['from_number']})")
        logger.info(f"  To: {recording['to_name']} ({recording['to_number']})")
        logger.info(f"  Duration: {recording['duration']} seconds")

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

                # Create folder structure
                logger.info(f"  📁 Creating folder structure...")
                root_folder_id = self.get_or_create_folder("Call Recordings")
                year_folder_id = self.get_or_create_folder(f"{year}", root_folder_id)
                month_folder_id = self.get_or_create_folder(month_folder, year_folder_id)
                audio_folder_id = self.get_or_create_folder("Audio", month_folder_id)

                # Upload audio file
                logger.info(f"  ☁️  Uploading to Google Drive...")
                filename = f"{call_datetime.strftime('%Y%m%d_%H%M')}_{recording_id}.mp3"

                file_id = self.upload_file(
                    str(audio_path),
                    filename,
                    audio_folder_id
                )

                self.upload_count += 1
                logger.info(f"  🎉 Successfully uploaded recording!")
                return True

            except Exception as e:
                logger.error(f"  ❌ Failed: {e}")
                self.failed_count += 1
                return False

    def run(self):
        """Run the test"""
        print("\n" + "="*70)
        print("🧪 TEST: DOMAIN-WIDE DELEGATION UPLOAD")
        print(f"   Impersonating: {self.impersonate_email}")
        print("="*70)

        try:
            # Test with just 3 recordings
            recordings = self.fetch_recent_recordings(3)

            if not recordings:
                print("❌ No recordings found")
                return

            print(f"\n📋 Processing {len(recordings)} test recordings...")

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
                print("\n✨ Success! Domain-wide delegation is working!")
                print("📁 Files were uploaded by the impersonated user account")
                print(f"   Check Google Drive as: {self.impersonate_email}")
                print("   Path: Call Recordings/2025/[Month]/Audio/")

                print("\n✅ Next Steps:")
                print("   1. Update your main processing scripts to use delegation")
                print("   2. Process the 15 test recordings")
                print("   3. Run the full historical backup")
            else:
                print("\n❌ No files uploaded. Please check:")
                print("   1. Domain-wide delegation is configured in Google Admin")
                print("   2. The impersonation email is correct")
                print("   3. Check the error messages above")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            raise
        finally:
            if hasattr(self, 'ringcentral_auth'):
                self.ringcentral_auth.close()


def main():
    """Main entry point"""
    # Check if impersonation email is set
    if not os.getenv('GOOGLE_IMPERSONATE_EMAIL'):
        print("\n❌ ERROR: GOOGLE_IMPERSONATE_EMAIL not configured!")
        print("\nPlease add to your .env file:")
        print("GOOGLE_IMPERSONATE_EMAIL=user@yourdomain.com")
        print("\nReplace 'user@yourdomain.com' with a real user in your Google Workspace")
        print("\nThen follow the steps in DOMAIN_WIDE_DELEGATION_SETUP.md")
        return

    uploader = DomainDelegationUploader()
    uploader.run()


if __name__ == "__main__":
    main()
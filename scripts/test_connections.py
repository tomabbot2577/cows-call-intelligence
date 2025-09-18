#!/usr/bin/env python
"""
Test script to verify API connections and credentials
"""

import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.config.settings import Settings
from src.ringcentral.auth import RingCentralAuth
from src.database.config import DatabaseConfig
from src.database.session import SessionManager
from google.oauth2 import service_account
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_database_connection():
    """Test PostgreSQL database connection"""
    print("\n" + "="*50)
    print("Testing Database Connection...")
    print("="*50)

    try:
        settings = Settings()
        db_config = DatabaseConfig(settings.database_url)
        session_manager = SessionManager(db_config)

        with session_manager.get_session() as session:
            # Test query
            result = session.execute("SELECT version()").fetchone()
            print(f"✅ Database connected successfully")
            print(f"   PostgreSQL version: {result[0]}")

            # Check tables
            tables = session.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """).fetchall()

            print(f"   Found {len(tables)} tables:")
            for table in tables:
                print(f"     - {table[0]}")

        return True

    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Check DATABASE_URL in .env file")
        print("2. Ensure PostgreSQL is running: systemctl status postgresql")
        print("3. Verify database exists: sudo -u postgres psql -l")
        return False


def test_ringcentral_connection():
    """Test RingCentral API connection"""
    print("\n" + "="*50)
    print("Testing RingCentral API Connection...")
    print("="*50)

    try:
        settings = Settings()

        # Check credentials exist
        if not all([settings.ringcentral_client_id,
                   settings.ringcentral_client_secret,
                   settings.ringcentral_jwt_token]):
            print("❌ Missing RingCentral credentials in .env file")
            print("\nRequired variables:")
            print("  - RINGCENTRAL_CLIENT_ID")
            print("  - RINGCENTRAL_CLIENT_SECRET")
            print("  - RINGCENTRAL_JWT_TOKEN")
            return False

        print(f"   Client ID: {settings.ringcentral_client_id[:10]}...")
        print(f"   Server URL: {settings.ringcentral_server_url}")

        # Test authentication
        auth = RingCentralAuth(
            client_id=settings.ringcentral_client_id,
            client_secret=settings.ringcentral_client_secret,
            jwt_token=settings.ringcentral_jwt_token,
            server_url=settings.ringcentral_server_url
        )

        auth.authenticate()

        if auth.access_token:
            print(f"✅ RingCentral authentication successful")
            print(f"   Access token obtained (expires in {auth.expires_in} seconds)")

            # Test API call
            import requests
            headers = {"Authorization": f"Bearer {auth.access_token}"}
            response = requests.get(
                f"{settings.ringcentral_server_url}/restapi/v1.0/account/~/extension/~",
                headers=headers
            )

            if response.status_code == 200:
                data = response.json()
                print(f"   Extension ID: {data.get('id')}")
                print(f"   Extension Number: {data.get('extensionNumber')}")

            return True
        else:
            print("❌ Failed to obtain access token")
            return False

    except Exception as e:
        print(f"❌ RingCentral connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Verify JWT token is valid and not expired")
        print("2. Check if using correct server URL (sandbox vs production)")
        print("3. Ensure app has required permissions in RingCentral developer console")
        return False


def test_google_drive_connection():
    """Test Google Drive API connection"""
    print("\n" + "="*50)
    print("Testing Google Drive API Connection...")
    print("="*50)

    try:
        settings = Settings()

        # Check credentials file
        if not settings.google_credentials_path:
            print("❌ GOOGLE_CREDENTIALS_PATH not set in .env file")
            return False

        if not os.path.exists(settings.google_credentials_path):
            print(f"❌ Service account key file not found: {settings.google_credentials_path}")
            print("\nTo fix:")
            print("1. Download service account JSON key from Google Cloud Console")
            print(f"2. Save it to: {settings.google_credentials_path}")
            return False

        print(f"   Credentials file: {settings.google_credentials_path}")

        # Load credentials
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_credentials_path,
            scopes=['https://www.googleapis.com/auth/drive']
        )

        print(f"   Service account: {credentials.service_account_email}")

        # Test API connection
        service = build('drive', 'v3', credentials=credentials)

        # Try to list files (limited to 1)
        results = service.files().list(
            pageSize=1,
            fields="files(id, name)"
        ).execute()

        print("✅ Google Drive API connected successfully")

        # Test folder access if configured
        if settings.google_drive_folder_id:
            try:
                folder = service.files().get(
                    fileId=settings.google_drive_folder_id
                ).execute()
                print(f"   Target folder: {folder.get('name')} (ID: {settings.google_drive_folder_id})")
            except Exception as e:
                print(f"⚠️  Cannot access target folder: {settings.google_drive_folder_id}")
                print("   Make sure to share the folder with the service account email")

        return True

    except Exception as e:
        print(f"❌ Google Drive connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Verify service account JSON key is valid")
        print("2. Ensure Google Drive API is enabled in Google Cloud Console")
        print("3. Share target folder with service account email")
        return False


def test_whisper_setup():
    """Test Whisper model setup"""
    print("\n" + "="*50)
    print("Testing Whisper Model Setup...")
    print("="*50)

    try:
        settings = Settings()
        print(f"   Model: {settings.whisper_model}")
        print(f"   Device: {settings.whisper_device}")

        import whisper

        # Try loading the model
        print(f"   Loading model '{settings.whisper_model}'...")
        model = whisper.load_model(settings.whisper_model)

        print("✅ Whisper model loaded successfully")
        print(f"   Model parameters: {sum(p.numel() for p in model.parameters()):,}")

        # Test with a simple audio if available
        import numpy as np

        # Create a short silent audio for testing
        sample_rate = 16000
        duration = 1  # 1 second
        audio = np.zeros(sample_rate * duration, dtype=np.float32)

        result = model.transcribe(audio, language='en')
        print("   Model test transcription completed")

        return True

    except Exception as e:
        print(f"❌ Whisper setup failed: {e}")
        print("\nTroubleshooting:")
        print("1. Ensure whisper is installed: pip install openai-whisper")
        print("2. For large models, ensure sufficient memory")
        print("3. Consider using smaller model: tiny, base, small")
        return False


def test_email_setup():
    """Test email configuration"""
    print("\n" + "="*50)
    print("Testing Email Configuration...")
    print("="*50)

    try:
        settings = Settings()

        if not os.getenv('SMTP_HOST'):
            print("⚠️  Email not configured (SMTP_HOST not set)")
            print("   Email alerts will be disabled")
            return True  # Not a critical failure

        print(f"   SMTP Host: {os.getenv('SMTP_HOST')}")
        print(f"   SMTP Port: {os.getenv('SMTP_PORT', 587)}")
        print(f"   SMTP User: {os.getenv('SMTP_USER', 'Not set')}")

        if os.getenv('SMTP_USER') and os.getenv('SMTP_PASSWORD'):
            import smtplib

            server = smtplib.SMTP(os.getenv('SMTP_HOST'), int(os.getenv('SMTP_PORT', 587)))
            server.starttls()
            server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD'))
            server.quit()

            print("✅ Email configuration valid")
            print(f"   Alert recipient: {os.getenv('ALERT_EMAIL', 'Not set')}")
        else:
            print("⚠️  Email credentials not fully configured")

        return True

    except Exception as e:
        print(f"⚠️  Email test failed: {e}")
        print("\nTo fix Gmail authentication:")
        print("1. Enable 2-factor authentication")
        print("2. Generate app-specific password")
        print("3. Use app password in SMTP_PASSWORD")
        return True  # Not a critical failure


def test_slack_setup():
    """Test Slack webhook configuration"""
    print("\n" + "="*50)
    print("Testing Slack Configuration...")
    print("="*50)

    webhook_url = os.getenv('SLACK_WEBHOOK')

    if not webhook_url:
        print("⚠️  Slack not configured (SLACK_WEBHOOK not set)")
        print("   Slack alerts will be disabled")
        return True  # Not a critical failure

    try:
        import requests

        print(f"   Webhook URL: {webhook_url[:50]}...")

        # Send test message
        response = requests.post(webhook_url, json={
            'text': '🔧 Call Recording System: Test connection successful'
        })

        if response.status_code == 200:
            print("✅ Slack webhook configured successfully")
            print("   Test message sent to configured channel")
        else:
            print(f"⚠️  Slack webhook returned status {response.status_code}")

        return True

    except Exception as e:
        print(f"⚠️  Slack test failed: {e}")
        return True  # Not a critical failure


def main():
    """Run all connection tests"""
    print("\n" + "="*70)
    print(" CALL RECORDING SYSTEM - CONNECTION TEST SUITE")
    print("="*70)

    # Check .env file
    if not os.path.exists('.env'):
        print("\n❌ ERROR: .env file not found!")
        print("\nTo fix:")
        print("1. Copy .env.example to .env")
        print("2. Fill in your credentials")
        sys.exit(1)

    # Run tests
    results = {
        'Database': test_database_connection(),
        'RingCentral API': test_ringcentral_connection(),
        'Google Drive API': test_google_drive_connection(),
        'Whisper Model': test_whisper_setup(),
        'Email': test_email_setup(),
        'Slack': test_slack_setup()
    }

    # Summary
    print("\n" + "="*70)
    print(" TEST RESULTS SUMMARY")
    print("="*70)

    for component, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {component:.<30} {status}")

    # Critical components that must pass
    critical = ['Database', 'RingCentral API', 'Google Drive API', 'Whisper Model']
    critical_pass = all(results[c] for c in critical)

    if critical_pass:
        print("\n✅ All critical components passed. System ready for use!")
        return 0
    else:
        print("\n❌ Some critical components failed. Please fix issues above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
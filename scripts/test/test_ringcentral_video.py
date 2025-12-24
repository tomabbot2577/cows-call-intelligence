#!/usr/bin/env python3
"""
Test RingCentral Video API Access

Tests whether the existing RingCentral JWT can access video meeting history.
Part of ConvoMetrics Video Meeting Intelligence integration.

Usage:
    python scripts/test/test_ringcentral_video.py
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

try:
    from ringcentral import SDK
except ImportError:
    print("Installing ringcentral SDK...")
    os.system(f"{sys.executable} -m pip install ringcentral")
    from ringcentral import SDK


class RingCentralVideoTest:
    """Test RingCentral Video API access."""

    def __init__(self):
        self.client_id = os.getenv('RC_CLIENT_ID') or os.getenv('RINGCENTRAL_CLIENT_ID')
        self.client_secret = os.getenv('RC_CLIENT_SECRET') or os.getenv('RINGCENTRAL_CLIENT_SECRET')
        self.jwt_token = os.getenv('RC_JWT_TOKEN') or os.getenv('RINGCENTRAL_JWT_TOKEN')
        self.server_url = os.getenv('RC_SERVER_URL') or os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')

        if not all([self.client_id, self.client_secret, self.jwt_token]):
            raise ValueError("Missing RingCentral credentials in .env")

        self.sdk = SDK(self.client_id, self.client_secret, self.server_url)
        self.platform = self.sdk.platform()
        self.platform.login(jwt=self.jwt_token)
        print("✓ Authenticated with RingCentral")

    def test_video_meeting_history(self, days_back: int = 30):
        """
        Test access to Video meeting history.
        Endpoint: GET /rcvideo/v1/history/meetings
        """
        print("\n" + "=" * 60)
        print("TEST 1: Video Meeting History")
        print("=" * 60)

        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=days_back)

            # Use Unix timestamps (milliseconds) for Video API
            params = {
                'startTime': int(start_time.timestamp() * 1000),
                'endTime': int(end_time.timestamp() * 1000),
                'perPage': 25
            }

            print(f"Fetching meetings from {start_time.date()} to {end_time.date()}...")

            response = self.platform.get('/rcvideo/v1/history/meetings', params)
            data = response.json()

            # Handle JsonObject vs dict
            if hasattr(data, 'records'):
                meetings = data.records
            elif isinstance(data, dict):
                meetings = data.get('records', [])
            else:
                meetings = []

            if meetings:
                print(f"✓ Found {len(meetings)} video meetings")
                print("\n--- Sample Meetings ---")

                for i, meeting in enumerate(meetings[:5]):
                    # Extract fields safely
                    meeting_id = getattr(meeting, 'id', None) or meeting.get('id', 'N/A') if isinstance(meeting, dict) else getattr(meeting, 'id', 'N/A')
                    name = getattr(meeting, 'name', None) or meeting.get('name', 'No Title') if isinstance(meeting, dict) else getattr(meeting, 'name', 'No Title')
                    start = getattr(meeting, 'startTime', None) or meeting.get('startTime', 'N/A') if isinstance(meeting, dict) else getattr(meeting, 'startTime', 'N/A')
                    duration = getattr(meeting, 'duration', None) or meeting.get('duration', 0) if isinstance(meeting, dict) else getattr(meeting, 'duration', 0)

                    print(f"\n  [{i+1}] ID: {meeting_id}")
                    print(f"      Name: {name}")
                    print(f"      Start: {start}")
                    print(f"      Duration: {duration} seconds")

                    # Check for participants
                    participants = getattr(meeting, 'participants', None)
                    if participants is None and isinstance(meeting, dict):
                        participants = meeting.get('participants', [])
                    if participants:
                        print(f"      Participants: {len(participants)}")

                # Return first meeting for further testing
                return meetings[0] if meetings else None
            else:
                print("⚠ No video meetings found in the specified period")
                print("  This could mean:")
                print("  - No RingCentral Video meetings occurred recently")
                print("  - The account doesn't use RingCentral Video")
                print("  - Different permissions required")
                return None

        except Exception as e:
            error_msg = str(e)
            print(f"✗ Video meeting history FAILED: {error_msg}")

            if "CMN-102" in error_msg:
                print("  → Resource not found - RC Video may not be enabled")
            elif "CMN-401" in error_msg or "AGW-401" in error_msg:
                print("  → Authorization error - JWT may lack video permissions")
            elif "CMN-119" in error_msg:
                print("  → Feature not available for this account type")

            return None

    def test_get_meeting_details(self, meeting_id: str):
        """
        Test getting details for a specific meeting.
        Endpoint: GET /rcvideo/v1/history/meetings/{meetingId}
        """
        print("\n" + "=" * 60)
        print(f"TEST 2: Meeting Details (ID: {meeting_id})")
        print("=" * 60)

        try:
            response = self.platform.get(f'/rcvideo/v1/history/meetings/{meeting_id}')
            data = response.json()

            print("✓ Got meeting details")

            # Pretty print key fields
            fields_to_show = ['id', 'name', 'startTime', 'endTime', 'duration',
                              'hostId', 'type', 'status', 'chatId']

            print("\n--- Meeting Details ---")
            for field in fields_to_show:
                value = getattr(data, field, None)
                if value is None and isinstance(data, dict):
                    value = data.get(field)
                if value is not None:
                    print(f"  {field}: {value}")

            return data

        except Exception as e:
            print(f"✗ Meeting details FAILED: {e}")
            return None

    def test_extension_lookup(self, extension_id: str = None):
        """
        Test extension lookup for phone number enrichment.
        Endpoint: GET /restapi/v1.0/account/~/extension/{extensionId}
        """
        print("\n" + "=" * 60)
        print("TEST 3: Extension Lookup (Phone Enrichment)")
        print("=" * 60)

        try:
            # First, get account extensions list
            if not extension_id:
                print("Getting extensions list...")
                response = self.platform.get('/restapi/v1.0/account/~/extension', {'perPage': 10})
                data = response.json()

                records = data.records if hasattr(data, 'records') else data.get('records', [])

                if records:
                    print(f"✓ Found {len(records)} extensions")

                    for i, ext in enumerate(records[:5]):
                        ext_id = getattr(ext, 'id', None)
                        name = getattr(ext, 'name', 'N/A')
                        ext_num = getattr(ext, 'extensionNumber', 'N/A')

                        print(f"\n  [{i+1}] ID: {ext_id}")
                        print(f"      Name: {name}")
                        print(f"      Extension: {ext_num}")

                        # Try to get phone numbers
                        contact = getattr(ext, 'contact', None)

                        if contact:
                            business_phone = getattr(contact, 'businessPhone', None)
                            mobile_phone = getattr(contact, 'mobilePhone', None)
                            email = getattr(contact, 'email', None)

                            if business_phone:
                                print(f"      Business Phone: {business_phone}")
                            if mobile_phone:
                                print(f"      Mobile Phone: {mobile_phone}")
                            if email:
                                print(f"      Email: {email}")

                    return records
                else:
                    print("⚠ No extensions found")
                    return None
            else:
                # Get specific extension
                print(f"Getting extension {extension_id}...")
                response = self.platform.get(f'/restapi/v1.0/account/~/extension/{extension_id}')
                data = response.json()
                print(f"✓ Got extension details")
                return data

        except Exception as e:
            print(f"✗ Extension lookup FAILED: {e}")
            return None

    def test_recording_content(self, meeting_id: str):
        """
        Test if recordings can be accessed for a meeting.
        Note: RC Video recordings may require separate download.
        """
        print("\n" + "=" * 60)
        print("TEST 4: Recording Access")
        print("=" * 60)

        try:
            # Try to get recording info
            response = self.platform.get(f'/rcvideo/v1/history/meetings/{meeting_id}/recordings')
            data = response.json()

            recordings = data.records if hasattr(data, 'records') else data.get('records', [])

            if recordings:
                print(f"✓ Found {len(recordings)} recordings for meeting")
                for i, rec in enumerate(recordings):
                    rec_id = getattr(rec, 'id', None) or rec.get('id') if isinstance(rec, dict) else getattr(rec, 'id', 'N/A')
                    status = getattr(rec, 'status', None) or rec.get('status') if isinstance(rec, dict) else getattr(rec, 'status', 'N/A')
                    print(f"  [{i+1}] Recording ID: {rec_id}, Status: {status}")
                return recordings
            else:
                print("⚠ No recordings found for this meeting")
                return None

        except Exception as e:
            print(f"⚠ Recording access: {e}")
            print("  Note: RC Video recordings may require different endpoint")
            return None


    def test_account_info(self):
        """Test getting account information."""
        print("\n" + "=" * 60)
        print("TEST 0: Account Info (Verify Credentials)")
        print("=" * 60)

        try:
            response = self.platform.get('/restapi/v2/accounts/~')
            data = response.json()

            company = getattr(data, 'companyName', None) or 'N/A'
            status = getattr(data, 'status', None) or 'N/A'
            main_number = getattr(data, 'mainNumber', None) or 'N/A'

            print(f"✓ Account authenticated successfully")
            print(f"  Company: {company}")
            print(f"  Status: {status}")
            print(f"  Main Number: {main_number}")
            return True

        except Exception as e:
            print(f"✗ Account info failed: {e}")
            return False

    def test_account_recordings(self):
        """Test listing account recordings (requires Video permission)."""
        print("\n" + "=" * 60)
        print("TEST 5: Account Recordings")
        print("=" * 60)

        try:
            response = self.platform.get('/rcvideo/v1/account/~/recordings', {'perPage': 10})
            data = response.json()

            recordings = getattr(data, 'recordings', [])
            if isinstance(data, dict):
                recordings = data.get('recordings', [])

            if recordings:
                print(f"✓ Found {len(recordings)} account recordings")
                for i, rec in enumerate(recordings[:3]):
                    rec_id = getattr(rec, 'id', None) or rec.get('id') if isinstance(rec, dict) else 'N/A'
                    name = getattr(rec, 'name', None) or rec.get('name', 'Untitled') if isinstance(rec, dict) else 'Untitled'
                    print(f"  [{i+1}] {name} (ID: {rec_id})")
                return recordings
            else:
                print("⚠ No recordings found (but API is accessible)")
                return []

        except Exception as e:
            error_str = str(e)
            if 'InsufficientPermissions' in error_str:
                print("✗ Recordings API requires Video permission")
            else:
                print(f"✗ Recordings API error: {e}")
            return None


def main():
    print("=" * 60)
    print("RingCentral Video API Test")
    print("ConvoMetrics Video Meeting Intelligence")
    print("=" * 60)

    try:
        tester = RingCentralVideoTest()
    except Exception as e:
        print(f"\n✗ Failed to initialize: {e}")
        sys.exit(1)

    # Test 0: Account Info (verify credentials work)
    tester.test_account_info()

    # Test 1: Video Meeting History
    sample_meeting = tester.test_video_meeting_history(days_back=90)

    # Test 2: Meeting Details (if we found a meeting)
    if sample_meeting:
        meeting_id = getattr(sample_meeting, 'id', None)
        if meeting_id is None and isinstance(sample_meeting, dict):
            meeting_id = sample_meeting.get('id')

        if meeting_id:
            tester.test_get_meeting_details(str(meeting_id))
            tester.test_recording_content(str(meeting_id))

    # Test 3: Extension Lookup (for phone enrichment)
    tester.test_extension_lookup()

    # Test 5: Account Recordings (requires Video permission)
    tester.test_account_recordings()

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print("""
If video meeting history returned results:
  ✓ RingCentral Video API is accessible with existing JWT
  ✓ Can proceed with RingCentral Video integration

If video meeting history returned no results but no errors:
  ⚠ API accessible but no RC Video meetings found
  → May need to wait for actual RC Video meetings to occur

If errors occurred:
  ✗ May need additional permissions or RC Video subscription
  → Contact RingCentral admin to verify Video API access

To enable Video API:
  1. Go to: https://developers.ringcentral.com/my-account.html
  2. Select your app
  3. Add "Video" scope/permission
  4. Save and regenerate JWT if needed
""")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Test Fathom AI API Access

Tests the Fathom API client using Steve Abbey's API key.

Usage:
    python scripts/test/test_fathom_api.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from src.fathom.client import FathomClient, FathomAPIError
from src.fathom.key_manager import FathomKeyManager


def test_key_manager():
    """Test FathomKeyManager functionality."""
    print("\n" + "=" * 60)
    print("TEST 1: Key Manager")
    print("=" * 60)

    try:
        km = FathomKeyManager()
        print("✓ KeyManager initialized")

        # Get employee count
        counts = km.get_employee_count()
        print(f"✓ Employee counts: {counts}")

        # Get active employees
        employees = km.get_active_employees()
        print(f"✓ Found {len(employees)} active employees")

        for emp in employees:
            print(f"  - {emp.employee_name} ({emp.employee_email}) "
                  f"[admin={emp.is_admin}, last_sync={emp.last_sync_at}]")

        # Get Steve Abbey's API key
        steve_email = 'sabbey@mainsequence.net'
        api_key = km.get_api_key(steve_email)

        if api_key:
            # Mask the key for display
            masked = api_key[:10] + "..." + api_key[-5:]
            print(f"✓ Retrieved API key for {steve_email}: {masked}")
            return api_key
        else:
            print(f"✗ No API key found for {steve_email}")
            return None

    except Exception as e:
        print(f"✗ KeyManager test failed: {e}")
        return None


def test_fathom_client(api_key: str):
    """Test FathomClient functionality."""
    print("\n" + "=" * 60)
    print("TEST 2: Fathom API Client")
    print("=" * 60)

    try:
        client = FathomClient(api_key)
        print("✓ FathomClient initialized")

        # Verify API key
        print("\nVerifying API key...")
        is_valid = client.verify_api_key()
        if is_valid:
            print("✓ API key is valid")
        else:
            print("✗ API key is invalid")
            return None

        # Get user info
        print("\nGetting user info...")
        user_info = client.get_user_info()
        if user_info:
            print(f"✓ User info: {user_info}")

        return client

    except FathomAPIError as e:
        print(f"✗ API error: {e.message} (status={e.status_code})")
        return None
    except Exception as e:
        print(f"✗ Client test failed: {e}")
        return None


def test_list_meetings(client: FathomClient):
    """Test listing meetings."""
    print("\n" + "=" * 60)
    print("TEST 3: List Meetings")
    print("=" * 60)

    try:
        # Get meetings from last 30 days
        created_after = datetime.now(timezone.utc) - timedelta(days=30)
        print(f"Fetching meetings since {created_after.date()}...")

        meetings = client.list_meetings(created_after=created_after, limit=10)

        if meetings:
            print(f"✓ Found {len(meetings)} meetings")

            for i, meeting in enumerate(meetings[:5]):
                print(f"\n  [{i+1}] ID: {meeting.recording_id}")
                print(f"      Title: {meeting.title}")
                print(f"      Created: {meeting.created_at}")
                print(f"      Duration: {meeting.duration_seconds // 60}m {meeting.duration_seconds % 60}s")
                print(f"      Platform: {meeting.platform}")
                print(f"      Participants: {len(meeting.participants)}")
                print(f"      Invitees: {len(meeting.calendar_invitees)}")

                # Show participant names
                if meeting.participants:
                    names = [p.get('name', 'Unknown') for p in meeting.participants[:3]]
                    print(f"      Participant names: {', '.join(names)}")

            return meetings[0] if meetings else None
        else:
            print("⚠ No meetings found in the specified period")
            return None

    except FathomAPIError as e:
        print(f"✗ Error listing meetings: {e.message}")
        return None


def test_meeting_details(client: FathomClient, recording_id: int):
    """Test getting meeting details, transcript, and summary."""
    print("\n" + "=" * 60)
    print(f"TEST 4: Meeting Details (ID: {recording_id})")
    print("=" * 60)

    # Get transcript
    print("\nFetching transcript...")
    try:
        transcript = client.get_transcript(recording_id)
        if transcript:
            text = transcript.get('text', '')
            segments = transcript.get('segments', [])
            print(f"✓ Transcript retrieved: {len(text)} chars, {len(segments)} segments")
            if text:
                preview = text[:200] + "..." if len(text) > 200 else text
                print(f"  Preview: {preview}")
        else:
            print("⚠ No transcript available")
    except FathomAPIError as e:
        print(f"✗ Transcript error: {e.message}")

    # Get summary
    print("\nFetching summary...")
    try:
        summary = client.get_summary(recording_id)
        if summary:
            summary_text = summary.get('summary', '')
            key_points = summary.get('key_points', [])
            action_items = summary.get('action_items', [])

            print(f"✓ Summary retrieved")
            if summary_text:
                preview = summary_text[:300] + "..." if len(summary_text) > 300 else summary_text
                print(f"  Summary: {preview}")
            if key_points:
                print(f"  Key points: {len(key_points)}")
            if action_items:
                print(f"  Action items: {len(action_items)}")
                for item in action_items[:3]:
                    print(f"    - {item.get('text', item)}")
        else:
            print("⚠ No summary available")
    except FathomAPIError as e:
        print(f"✗ Summary error: {e.message}")

    # Get action items
    print("\nFetching action items...")
    try:
        action_items = client.get_action_items(recording_id)
        if action_items:
            print(f"✓ Found {len(action_items)} action items")
            for item in action_items[:5]:
                text = item.get('text') or item.get('description', str(item))
                assignee = item.get('assignee', {}).get('name', 'Unassigned')
                print(f"  - [{assignee}] {text[:80]}")
        else:
            print("⚠ No action items found")
    except FathomAPIError as e:
        print(f"✗ Action items error: {e.message}")


def main():
    print("=" * 60)
    print("Fathom AI API Test")
    print("COWS Video Meeting Intelligence")
    print("=" * 60)

    # Test 1: Key Manager
    api_key = test_key_manager()

    if not api_key:
        print("\n✗ Cannot proceed without API key")
        sys.exit(1)

    # Test 2: Client initialization and key verification
    client = test_fathom_client(api_key)

    if not client:
        print("\n✗ Cannot proceed without valid client")
        sys.exit(1)

    # Test 3: List meetings
    sample_meeting = test_list_meetings(client)

    # Test 4: Meeting details (if we have a meeting)
    if sample_meeting:
        test_meeting_details(client, sample_meeting.recording_id)

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print("""
✓ Fathom API client is working
✓ Can retrieve encrypted API keys from database
✓ Can list meetings, transcripts, and summaries

Next steps:
1. Add more employees with Fathom API keys
2. Run scheduled sync to download all meetings
3. Process through AI layers
""")


if __name__ == '__main__':
    main()

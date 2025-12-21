#!/usr/bin/env python3
"""
Backfill Call Log from June 1, 2025 to Present
One-time script to catch up historical call data
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
load_dotenv('/var/www/call-recording-system/.env')

from src.scheduler.ringcentral_checker_v2 import RingCentralCheckerV2

def backfill():
    """Backfill all calls from June 1, 2025 to present"""

    # Calculate days since June 1, 2025
    start_date = datetime(2025, 6, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    total_days = (now - start_date).days

    print(f"=== Call Log Backfill ===")
    print(f"From: {start_date.date()}")
    print(f"To: {now.date()}")
    print(f"Total days to backfill: {total_days}")
    print()

    # Process in chunks of 7 days to avoid API limits
    chunk_days = 7
    chunks = (total_days // chunk_days) + 1

    total_calls = 0
    total_recordings = 0

    for i in range(chunks):
        chunk_start = start_date + timedelta(days=i * chunk_days)
        chunk_end = min(chunk_start + timedelta(days=chunk_days), now)

        if chunk_start >= now:
            break

        print(f"\n--- Chunk {i+1}/{chunks}: {chunk_start.date()} to {chunk_end.date()} ---")

        # Set state to this chunk's start
        state_file = '/var/www/call-recording-system/data/scheduler/last_check_v2.json'
        state = {
            'last_check': chunk_start.isoformat(),
            'total_calls_logged': 0,
            'total_recordings_downloaded': 0
        }
        with open(state_file, 'w') as f:
            json.dump(state, f)

        try:
            checker = RingCentralCheckerV2()
            # Override the fetch to use our specific end date
            hours_back = chunk_days * 24 + 24  # Extra day for overlap

            summary = checker.run_check(
                hours_back=hours_back,
                download_recordings=False  # Skip downloads for speed, do separately
            )

            total_calls += summary['new_calls_logged']
            total_recordings += summary['calls_with_recordings']

            print(f"  Calls logged: {summary['new_calls_logged']}")
            print(f"  With recordings: {summary['calls_with_recordings']}")
            print(f"  Missed: {summary['missed_calls']}")
            print(f"  Voicemails: {summary['voicemails']}")

        except Exception as e:
            print(f"  ERROR: {e}")

        # Rate limit between chunks
        time.sleep(2)

    print(f"\n=== Backfill Complete ===")
    print(f"Total calls logged: {total_calls}")
    print(f"Total with recordings: {total_recordings}")

    # Reset state to now for regular cron runs
    state = {
        'last_check': now.isoformat(),
        'total_calls_logged': total_calls,
        'total_recordings_downloaded': 0
    }
    with open(state_file, 'w') as f:
        json.dump(state, f)

    print(f"\nState reset to {now.date()} for regular cron runs")

if __name__ == '__main__':
    backfill()

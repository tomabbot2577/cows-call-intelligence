#!/bin/bash
# RingCentral Video Meeting Sync - Cron Wrapper
# Syncs video meetings from RingCentral Video API
#
# NOTE: Requires Video permission on RingCentral app.
# Run with --check-only to verify permission status.
#
# Cron schedule (hourly during business hours):
#   0 8-17 * * 1-5 /var/www/call-recording-system/scripts/run_ringcentral_video_sync.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Activate virtual environment
source venv/bin/activate

# Run sync
python scripts/ringcentral/sync_video_meetings.py --hours-back 12

echo "RingCentral Video sync completed at $(date)"

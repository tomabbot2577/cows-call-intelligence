#!/bin/bash
# Fathom Meeting Sync - Cron Wrapper
# Syncs video meetings from Fathom AI for all employees
#
# Cron schedule (hourly during business hours):
#   30 8-17 * * 1-5 /var/www/call-recording-system/scripts/run_fathom_sync.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Activate virtual environment
source venv/bin/activate

# Run sync
python scripts/fathom/sync_all_employees.py --hours-back 2

echo "Fathom sync completed at $(date)"

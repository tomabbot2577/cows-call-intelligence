#!/bin/bash
# RingCentral Incremental Sync
# Fetches calls from the last 30 minutes only (for 15-min cron)
# Lightweight sync to keep dashboard data current without rate limiting

cd /var/www/call-recording-system
source venv/bin/activate
source .env 2>/dev/null

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/ringcentral_incremental_$(date +%Y%m%d).log"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting incremental RingCentral sync" >> "$LOG_FILE"

# Run incremental sync (last 30 minutes only, no downloads)
python -c "
import sys
sys.path.insert(0, '/var/www/call-recording-system')
from src.scheduler.ringcentral_checker_v2 import RingCentralCheckerV2

try:
    checker = RingCentralCheckerV2()
    # Fetch only last 30 minutes of calls (quick sync)
    calls = checker.fetch_all_calls(hours_back=0.5)
    new_calls = 0
    for call in calls:
        if checker.save_call_to_db(call):
            new_calls += 1
    print(f'Incremental sync: {new_calls} new calls saved from {len(calls)} fetched')
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
" 2>&1 >> "$LOG_FILE"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Incremental sync completed successfully" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Incremental sync FAILED (exit code: $EXIT_CODE)" >> "$LOG_FILE"
fi

echo "" >> "$LOG_FILE"
exit $EXIT_CODE

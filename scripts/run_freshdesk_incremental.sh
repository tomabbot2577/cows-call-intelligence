#!/bin/bash
# Freshdesk Incremental Sync
# Fetches tickets updated in the last 30 minutes only (for 15-min cron)
# Lightweight sync to keep ticket data current

cd /var/www/call-recording-system
source venv/bin/activate
source .env 2>/dev/null

LOG_DIR="logs"
LOG_FILE="$LOG_DIR/freshdesk_incremental_$(date +%Y%m%d).log"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting incremental Freshdesk sync" >> "$LOG_FILE"

# Run incremental sync (recently updated tickets only)
python -c "
import sys
sys.path.insert(0, '/var/www/call-recording-system')
from datetime import datetime, timedelta

try:
    from rag_integration.services.freshdesk_scraper import FreshdeskScraper

    scraper = FreshdeskScraper()

    # Get tickets updated in the last 30 minutes
    since = datetime.now() - timedelta(minutes=30)
    tickets = scraper.fetch_recent_tickets(updated_since=since.isoformat())

    count = 0
    for ticket in tickets:
        scraper.save_ticket_qa(ticket)
        count += 1

    print(f'Incremental sync: {count} tickets updated')
except Exception as e:
    print(f'Error: {e}')
    # Don't fail on Freshdesk errors - may not have incremental support
" 2>&1 >> "$LOG_FILE"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Incremental Freshdesk sync completed" >> "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Incremental Freshdesk sync FAILED (exit code: $EXIT_CODE)" >> "$LOG_FILE"
fi

echo "" >> "$LOG_FILE"
exit 0  # Don't fail the cron even if Freshdesk errors

#!/bin/bash
# Layer Analysis Watchdog - runs 6-layer AI analysis on new transcribed meetings
# Called by cron every 10 minutes

cd /var/www/call-recording-system
source venv/bin/activate
source .env 2>/dev/null || true

LOG_FILE="logs/layer_analysis_watchdog.log"
LOCK_FILE="/tmp/layer_analysis.lock"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

# Check for lock file (prevent concurrent runs)
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        log "Another instance running (PID $PID), skipping"
        exit 0
    else
        log "Stale lock file found, removing"
        rm -f "$LOCK_FILE"
    fi
fi

# Check if there are pending meetings
PENDING=$(PGPASSWORD="${PG_PASSWORD:-$DB_PASSWORD}" psql -U call_insights_user -h localhost -d call_insights -t -c \
    "SELECT COUNT(*) FROM video_meetings WHERE transcript_text IS NOT NULL AND (layer1_complete IS NULL OR layer1_complete = FALSE);" 2>/dev/null | tr -d ' ')

if [ "$PENDING" -eq 0 ] 2>/dev/null; then
    log "No pending meetings for analysis"
    exit 0
fi

log "Found $PENDING meetings pending analysis"

# Create lock
echo $$ > "$LOCK_FILE"

# Run batch analysis with 2 workers (reduced - caught up)
python scripts/video_processing/batch_layer_analysis.py --limit 50 --workers 2 >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

# Remove lock
rm -f "$LOCK_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    log "Layer analysis completed successfully"
else
    log "Layer analysis failed with exit code $EXIT_CODE"
fi

exit $EXIT_CODE

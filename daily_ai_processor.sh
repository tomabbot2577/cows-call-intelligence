#!/bin/bash
# Daily AI Layer Processor
# Runs via cron to process new transcriptions through all 5 AI layers
#
# Cron setup (run every 30 minutes):
# */30 * * * * /var/www/call-recording-system/daily_ai_processor.sh >> /var/www/call-recording-system/logs/daily_ai.log 2>&1

cd /var/www/call-recording-system
source venv/bin/activate

LOGFILE="/var/www/call-recording-system/logs/daily_ai_$(date +%Y%m%d).log"
LIMIT=100  # Process up to 100 records per run

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}

log "=========================================="
log "Starting AI Layer Processing"
log "=========================================="

# Check if already running
if pgrep -f "process_all_layers_master.py" > /dev/null; then
    log "AI processor already running, skipping..."
    exit 0
fi

# Get current status
STATUS=$(python process_all_layers_master.py --status 2>&1 | grep "Total pending")
log "$STATUS"

# Check if any work to do
PENDING=$(echo "$STATUS" | grep -oP '\d+(?=,)' | head -1)
if [ -z "$PENDING" ] || [ "$PENDING" -eq 0 ]; then
    log "No pending records to process"
    exit 0
fi

log "Processing up to $LIMIT records per layer..."

# Process all layers
python process_all_layers_master.py --all --limit $LIMIT >> "$LOGFILE" 2>&1

# Final status
log "=========================================="
log "Processing Complete - Final Status:"
log "=========================================="
python process_all_layers_master.py --status 2>&1 | tee -a "$LOGFILE"

log "Done"

#!/bin/bash
# Transcription Watchdog - Auto-restart if workers stop
# Runs every 5 minutes via cron

cd /var/www/call-recording-system
source venv/bin/activate

LOG_FILE="logs/transcription_watchdog.log"
PID_FILE="data/transcription_batch.pid"
WORKERS=2
LIMIT=50

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> $LOG_FILE
}

# Check how many transcriptions are pending
PENDING=$(PGPASSWORD='REDACTED_DB_PASSWORD' psql -U call_insights_user -h localhost -d call_insights -t -c \
    "SELECT COUNT(*) FROM video_meetings WHERE source='ringcentral' AND transcript_text IS NULL;" 2>/dev/null | tr -d ' ')

COMPLETED=$(PGPASSWORD='REDACTED_DB_PASSWORD' psql -U call_insights_user -h localhost -d call_insights -t -c \
    "SELECT COUNT(*) FROM video_meetings WHERE source='ringcentral' AND transcript_text IS NOT NULL;" 2>/dev/null | tr -d ' ')

log "Status: $COMPLETED transcribed, $PENDING pending"

# If no pending, we're done
if [ "$PENDING" -eq 0 ] 2>/dev/null; then
    log "All transcriptions complete!"
    # Kill any running processes
    pkill -f "batch_transcribe_videos.py" 2>/dev/null
    rm -f $PID_FILE
    exit 0
fi

# Check if batch process is running
RUNNING_PROCS=$(ps aux | grep "batch_transcribe_videos.py" | grep -v grep | wc -l)

if [ "$RUNNING_PROCS" -eq 0 ]; then
    log "No transcription process running - STARTING with $WORKERS workers"
    
    # Start the batch process
    nohup python scripts/video_processing/batch_transcribe_videos.py --workers $WORKERS --limit $LIMIT >> logs/batch_transcribe.log 2>&1 &
    NEW_PID=$!
    echo $NEW_PID > $PID_FILE
    log "Started batch transcription PID: $NEW_PID"
    
elif [ "$RUNNING_PROCS" -lt 2 ]; then
    # Check if it's actually making progress
    # Get the last modified time of the log file
    if [ -f "logs/batch_transcribe.log" ]; then
        LAST_MOD=$(stat -c %Y logs/batch_transcribe.log 2>/dev/null || echo 0)
        NOW=$(date +%s)
        DIFF=$((NOW - LAST_MOD))
        
        # If log hasn't been updated in 10 minutes, something is stuck
        if [ "$DIFF" -gt 600 ]; then
            log "Process appears stuck (no log update in ${DIFF}s) - RESTARTING"
            pkill -f "batch_transcribe_videos.py" 2>/dev/null
            sleep 5
            nohup python scripts/video_processing/batch_transcribe_videos.py --workers $WORKERS --limit $LIMIT >> logs/batch_transcribe.log 2>&1 &
            NEW_PID=$!
            echo $NEW_PID > $PID_FILE
            log "Restarted batch transcription PID: $NEW_PID"
        else
            log "Process running normally (last update ${DIFF}s ago)"
        fi
    fi
else
    log "Process running with $RUNNING_PROCS instances"
fi

# Also check for the layer analysis
LAYER_PENDING=$(PGPASSWORD='REDACTED_DB_PASSWORD' psql -U call_insights_user -h localhost -d call_insights -t -c \
    "SELECT COUNT(*) FROM video_meetings WHERE source='ringcentral' AND transcript_text IS NOT NULL AND (layer1_complete IS NULL OR layer1_complete = FALSE);" 2>/dev/null | tr -d ' ')

if [ "$LAYER_PENDING" -gt 0 ] 2>/dev/null; then
    LAYER_RUNNING=$(ps aux | grep "batch_layer_analysis.py" | grep -v grep | wc -l)
    if [ "$LAYER_RUNNING" -eq 0 ]; then
        log "Layer analysis needed for $LAYER_PENDING meetings - will start after transcription completes"
    fi
fi
